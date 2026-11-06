"""Lambda modes for the M2 chunked backfill (M2-01.8): one event shape per Step Functions state.

- `{"profile": "m2", "step": "month", "month": 0..18}`: simulate one month into `landing/booncore_m2/` in S3.
- `{"profile": "m2", "step": "static"}`: the month-independent tables (tenants, price catalog, labels, FOCUS, invoices, dimensions).
- `{"profile": "m2", "step": "build"}`: pull the landing tree from S3, run the M2 dbt build with gates, and upload
  bronze/silver/gold/publish. Gates failing returns `dbt_failed` and uploads only the quality evidence.

Each step is idempotent: output depends only on (seed, month). Set LAKE_BUCKET to "" to run without S3 (tests).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger("mc_pipelines")
WORK = Path("/tmp/mc_m2")
LANDING_PREFIX = "landing/booncore_m2"
UPLOAD_PREFIXES = ("silver", "gold", "publish")


def _upload(s3: Any, bucket: str, root: Path, prefix: str, extra) -> int:
    n = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        s3.upload_file(str(path), bucket, f"{prefix}/{path.relative_to(root).as_posix()}", ExtraArgs=extra(path))
        n += 1
    return n


def _download(s3: Any, bucket: str, prefix: str, dest: Path) -> int:
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            target = dest / obj["Key"][len(prefix) + 1:]
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, obj["Key"], str(target))
            n += 1
    return n


def handle(event: dict, run_id: str, s3: Any = None) -> dict:
    from .lambda_handler import _extra_args

    step = event.get("step")
    bucket = os.environ.get("LAKE_BUCKET", "")
    seed = event.get("seed")
    if bucket and s3 is None:
        import boto3

        s3 = boto3.client("s3")
    shutil.rmtree(WORK, ignore_errors=True)
    landing = WORK / "landing"

    if step in ("month", "static"):
        from booncore_sim.cli import run_m2
        from booncore_sim.m2_tenants import MONTHS

        month = event.get("month")
        if step == "month" and (not isinstance(month, int) or not 0 <= month < MONTHS):
            return {"status": "bad_event", "run_id": run_id, "reason": f"month must be an int in 0..{MONTHS - 1}"}
        manifest = run_m2(seed, landing, step, month if step == "month" else None)
        uploaded = _upload(s3, bucket, landing, LANDING_PREFIX, _extra_args) if bucket else 0
        return {"status": "success", "run_id": run_id, "step": step, "month": month,
                "files": len(manifest["files"]), "rows": sum(f["rows"] for f in manifest["files"]), "objects_uploaded": uploaded}

    if step == "build":
        from .cli import run_m2_dbt

        data = WORK / "data"
        if bucket:
            fetched = _download(s3, bucket, LANDING_PREFIX, landing)
            if not fetched:
                return {"status": "no_landing", "run_id": run_id}
        summary = run_m2_dbt(landing, data, run_id, transform_dir=_copy_transform() if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else None)
        if not summary["success"]:
            log.error("m2_dbt_build_finished", extra={"fields": summary})
            if bucket and (data / "gold" / "_quality").exists():
                _upload(s3, bucket, data / "gold" / "_quality", "gold/_quality", _extra_args)
            return {"status": "dbt_failed", "run_id": run_id, "failures": summary.get("failures")}
        uploaded = 0
        if bucket:
            for prefix in UPLOAD_PREFIXES:
                if (data / prefix).exists():
                    uploaded += _upload(s3, bucket, data / prefix, prefix, _extra_args)
        return {"status": "success", "run_id": run_id, "step": "build", "objects_uploaded": uploaded,
                "dbt": summary.get("statuses")}

    return {"status": "bad_event", "run_id": run_id, "reason": "step must be month, static or build"}


def _copy_transform() -> Path:
    """Lambda's filesystem is read-only outside /tmp, so dbt runs from a copy of the project."""
    from .cli import TRANSFORM_DIR

    dest = WORK / "transform"
    shutil.copytree(TRANSFORM_DIR, dest)
    return dest
