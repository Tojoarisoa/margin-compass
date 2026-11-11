"""Lambda modes for the M2 chunked backfill (M2-01.8): one event shape per Step Functions state.

- `{"profile": "m2", "step": "month", "month": 0..18}`: simulate one month into `landing/booncore_m2/` in S3.
- `{"profile": "m2", "step": "static"}`: the month-independent tables (tenants, price catalog, labels, FOCUS, invoices, dimensions).
- `"approvals": true` (opt-in, M5-03): the static step exports the owner's recorded decisions from the core table
  (`mc_agents.owner.export_approvals`) to `approvals/approvals.jsonl` in the lake; month steps read that file and apply
  the closed-loop effects. Without the flag nothing changes.
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
UPLOAD_PREFIXES = ("silver", "gold", "publish", "models")
APPROVALS_KEY = "approvals/approvals.jsonl"


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


FOCUS_PREFIX = "focus-1-2"


def fetch_focus_export(s3: Any, bucket: str, dest: Path) -> str | None:
    """S7: copy the AWS FOCUS export Parquet files (read-only bucket) under `dest`; return the glob for PG-8, or None.

    A missing or empty export is not an error: PG-8 then shows `awaiting_first_export`.
    """
    n = 0
    try:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=FOCUS_PREFIX + "/"):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith(".parquet"):
                    continue
                target = dest / obj["Key"]
                target.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, obj["Key"], str(target))
                n += 1
    except Exception as e:  # noqa: BLE001 - the export is optional; never fail the build for it
        log.warning("focus_export_unavailable", extra={"fields": {"reason": str(e)[:200]}})
        return None
    return f"{dest}/{FOCUS_PREFIX}/**/*.parquet" if n else None


def export_approvals(s3: Any, bucket: str, table: Any, dest: Path) -> int:
    """M5-03: write the owner's latest decision per action to `dest` and the lake; returns the number of decisions."""
    from mc_agents.owner import export_approvals as scan
    from mc_agents.owner import to_jsonl

    rows = scan(table)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(to_jsonl(rows))
    if bucket:
        s3.upload_file(str(dest), bucket, APPROVALS_KEY, ExtraArgs={"ContentType": "application/x-ndjson"})
    return len(rows)


def fetch_approvals(s3: Any, bucket: str, dest: Path) -> bool:
    """Copy the exported approvals next to the month chunk; False when the static step has not exported them."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        s3.download_file(bucket, APPROVALS_KEY, str(dest))
    except Exception as e:  # noqa: BLE001 - reported as a step status, not a crash
        log.error("approvals_missing", extra={"fields": {"reason": str(e)[:200]}})
        return False
    return True


RUN_HISTORY_KEY = "publish/latest/runs.json"
RUN_HISTORY_KEEP = 30


def append_run_history(s3: Any, bucket: str, data: Path, run_id: str, summary: dict, now: str) -> int:
    """Add this build to `publish/latest/runs.json` (newest first, last 30); written under `data/` so the upload ships it."""
    import json

    old: list[dict] = []
    if bucket:
        tmp = WORK / "runs_old.json"
        try:
            s3.download_file(bucket, RUN_HISTORY_KEY, str(tmp))
            old = json.loads(tmp.read_text())["runs"]
        except Exception as e:  # first build: no history yet
            if "404" not in str(e) and "NoSuchKey" not in str(e) and not isinstance(e, FileNotFoundError):
                raise
    entry = {"run_id": run_id, "finished_at": now, "status": "success", "models": len(summary.get("statuses") or {})}
    runs = ([entry] + [r for r in old if r.get("run_id") != run_id])[:RUN_HISTORY_KEEP]
    out = data / RUN_HISTORY_KEY
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"runs": runs, "synthetic": True}))
    return len(runs)


def _brief(part: Any) -> Any:
    """Short view of a detector or churn result for the execution output (errors and gate verdicts, no lists)."""
    if not isinstance(part, dict):
        return None
    out = {k: v for k, v in part.items() if isinstance(v, (str, int, float, bool))}
    for gate in ("ev03", "ev11"):
        if isinstance(part.get(gate), dict):
            out[gate] = {k: v for k, v in part[gate].items() if isinstance(v, (int, float, bool)) or v is None}
    return out


def handle(event: dict, run_id: str, s3: Any = None, table: Any = None) -> dict:
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
        approvals_path, decisions = None, None
        if event.get("approvals") is True:  # M5-03 opt-in: closed-loop effects from the owner's decisions
            approvals_path = WORK / "approvals.jsonl"
            if step == "static":
                if table is None:
                    import boto3

                    table = boto3.resource("dynamodb").Table(os.environ["REGISTRY_TABLE"])
                decisions = export_approvals(s3, bucket, table, approvals_path)
                log.info("approvals_exported", extra={"fields": {"decisions": decisions}})
            elif bucket and not fetch_approvals(s3, bucket, approvals_path):
                return {"status": "no_approvals", "run_id": run_id, "month": month}
        manifest = run_m2(seed, landing, step, month if step == "month" else None,
                          approvals_path if step == "month" else None)
        uploaded = _upload(s3, bucket, landing, LANDING_PREFIX, _extra_args) if bucket else 0
        out = {"status": "success", "run_id": run_id, "step": step, "month": month,
               "files": len(manifest["files"]), "rows": sum(f["rows"] for f in manifest["files"]), "objects_uploaded": uploaded}
        if decisions is not None:
            out["approvals"] = decisions
        return out

    if step == "build":
        from .cli import run_m2_dbt

        data = WORK / "data"
        if bucket:
            fetched = _download(s3, bucket, LANDING_PREFIX, landing)
            if not fetched:
                return {"status": "no_landing", "run_id": run_id}
        billing = os.environ.get("MC_BILLING_BUCKET")
        if billing and s3 is not None:
            focus = fetch_focus_export(s3, billing, WORK / "billing")
            if focus:
                os.environ["MC_FINOPS_FOCUS_GLOB"] = focus
        summary = run_m2_dbt(landing, data, run_id, transform_dir=_copy_transform() if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else None)
        if not summary["success"]:
            log.error("m2_dbt_build_finished", extra={"fields": summary})
            if bucket and (data / "gold" / "_quality").exists():
                _upload(s3, bucket, data / "gold" / "_quality", "gold/_quality", _extra_args)
            return {"status": "dbt_failed", "run_id": run_id, "failures": summary.get("failures")}
        from datetime import UTC, datetime

        append_run_history(s3, bucket, data, run_id, summary, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        uploaded = 0
        if bucket:
            for prefix in UPLOAD_PREFIXES:
                if (data / prefix).exists():
                    uploaded += _upload(s3, bucket, data / prefix, prefix, _extra_args)
        return {"status": "success", "run_id": run_id, "step": "build", "objects_uploaded": uploaded,
                "dbt": summary.get("statuses"), "leaks": _brief(summary.get("leaks")), "churn": _brief(summary.get("churn")),
                "forecast": _brief(summary.get("forecast"))}

    return {"status": "bad_event", "run_id": run_id, "reason": "step must be month, static or build"}


def _copy_transform() -> Path:
    """Lambda's filesystem is read-only outside /tmp, so dbt runs from a copy of the project."""
    from .cli import TRANSFORM_DIR

    dest = WORK / "transform"
    shutil.copytree(TRANSFORM_DIR, dest)
    return dest
