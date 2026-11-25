"""Expire old CDK asset images (owner decision 2026-11-26, AWS spend fix (a)).

Ops task `ecr-cleanup`. Lists the CDK bootstrap container-assets repository and deletes images that are
(1) not used by any Lambda function in the account, (2) not among the newest KEEP_NEWEST pushes, and
(3) older than MIN_AGE_DAYS. Dry run unless `--apply`. Only the AWS CLI and the standard library.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

KEEP_NEWEST = 4  # current pipeline + API images and the previous pair (a rollback target)
MIN_AGE_DAYS = 14
BATCH = 100  # BatchDeleteImage limit


def aws(*args: str) -> dict:
    out = subprocess.run(["aws", *args, "--output", "json"], check=True, capture_output=True, text=True).stdout
    return json.loads(out or "{}")


def _pushed(image: dict) -> datetime:
    value = image["imagePushedAt"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def select_deletions(images: list[dict], in_use: set[str], now: datetime,
                     keep_newest: int = KEEP_NEWEST, min_age_days: int = MIN_AGE_DAYS) -> list[dict]:
    """Images safe to delete: unused, not among the newest `keep_newest`, pushed more than `min_age_days` ago."""
    newest = sorted(images, key=_pushed, reverse=True)
    keep = {i["imageDigest"] for i in newest[:keep_newest]}
    cutoff = now - timedelta(days=min_age_days)
    return [i for i in newest
            if i["imageDigest"] not in keep and i["imageDigest"] not in in_use and _pushed(i) < cutoff]


def digests_in_use() -> set[str]:
    """Digests used by the account's image-based Lambda functions; stops if any is not an `mc-*` function."""
    used: set[str] = set()
    token = None
    while True:
        page = aws("lambda", "list-functions", *(["--starting-token", token] if token else []), "--max-items", "50")
        for fn in page.get("Functions", []):
            if fn.get("PackageType") != "Image":
                continue
            if not fn["FunctionName"].startswith("mc-"):  # another app shares the CDK bootstrap: don't touch it
                raise SystemExit(f"image function outside mc-*: {fn['FunctionName']}; nothing deleted")
            code = aws("lambda", "get-function", "--function-name", fn["FunctionName"]).get("Code", {})
            uri = code.get("ResolvedImageUri") or code.get("ImageUri") or ""
            if "@" in uri:
                used.add(uri.split("@", 1)[1])
            elif uri:  # tag only: can't resolve here, so refuse to clean up rather than guess
                raise SystemExit(f"cannot resolve the image digest of {fn['FunctionName']}; nothing deleted")
        token = page.get("NextToken")
        if not token:
            return used


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    images = aws("ecr", "describe-images", "--repository-name", a.repository).get("imageDetails", [])
    in_use = digests_in_use()
    doomed = select_deletions(images, in_use, datetime.now(UTC))
    size = sum(i.get("imageSizeInBytes", 0) for i in doomed) / 1e9
    print(f"images: {len(images)}, in use by Lambda: {len(in_use)}, to delete: {len(doomed)} ({size:.2f} GB)"
          f"{'' if a.apply else ' (dry run)'}")
    if a.apply:
        for start in range(0, len(doomed), BATCH):
            ids = [{"imageDigest": i["imageDigest"]} for i in doomed[start:start + BATCH]]
            res = aws("ecr", "batch-delete-image", "--repository-name", a.repository,
                      "--image-ids", json.dumps(ids))
            if res.get("failures"):
                print(json.dumps(res["failures"])[:2000])
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
