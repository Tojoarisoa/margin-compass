"""AWS Lambda entry point (M1-02, env dev): the same simulator -> ingest -> dbt build path as local,
run in /tmp, then uploaded to the S3 lake under landing/, bronze/, silver/, gold/, quarantine/.

Lambda's filesystem is read-only outside /tmp, so the dbt project is copied there first.
Set LAKE_BUCKET to an empty string to skip the upload (used for local container tests).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from booncore_sim.cli import run as simulate

from .cli import TRANSFORM_DIR, JsonFormatter, run_dbt
from .ingest import IngestError, ingest

log = logging.getLogger("mc_pipelines")
WORK = Path("/tmp/mc")
UPLOAD_PREFIXES = ("bronze", "silver", "gold", "quarantine")


def _configure_logging(run_id: str) -> None:
    handler = logging.StreamHandler(sys.stdout)  # Lambda forwards stdout to CloudWatch Logs
    handler.setFormatter(JsonFormatter(run_id))
    for name in ("mc_pipelines", "booncore_sim"):
        logger = logging.getLogger(name)
        logger.handlers[:] = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False


def _upload(bucket: str, local_root: Path, key_prefix: str) -> int:
    import boto3

    s3 = boto3.client("s3")
    count = 0
    for path in sorted(p for p in local_root.rglob("*") if p.is_file()):
        s3.upload_file(str(path), bucket, f"{key_prefix}/{path.relative_to(local_root).as_posix()}")
        count += 1
    return count


def handler(event: dict, context) -> dict:
    event = event or {}
    run_id = event.get("run_id") or getattr(context, "aws_request_id", "local")
    ingest_date = event.get("ingest_date") or datetime.now(timezone.utc).date().isoformat()
    bucket = os.environ.get("LAKE_BUCKET", "")
    _configure_logging(run_id)
    log.info("pipeline_started", extra={"fields": {"env": os.environ.get("MC_ENV", "dev"), "ingest_date": ingest_date}})

    shutil.rmtree(WORK, ignore_errors=True)
    landing, data, transform = WORK / "landing" / "booncore", WORK / "data", WORK / "transform"
    shutil.copytree(TRANSFORM_DIR, transform)

    simulate(event.get("profile", "m1"), event.get("seed"), landing, run_id=run_id)
    try:
        result = ingest(landing, data, ingest_date, run_id)
    except IngestError as exc:
        log.error("ingest_failed", extra={"fields": {"reason": str(exc)}})
        if bucket:
            _upload(bucket, data / "quarantine", "quarantine")
        return {"status": "ingest_failed", "run_id": run_id}

    summary = run_dbt(data, ingest_date, result.window, run_id, transform_dir=transform)
    if not summary["success"]:
        log.error("dbt_build_finished", extra={"fields": summary})
        if bucket:  # keep the evidence: quarantined bronze and the scorecard
            for prefix in ("quarantine", "gold/_quality"):
                if (data / prefix).exists():
                    _upload(bucket, data / prefix, prefix)
        return {"status": "dbt_failed", "run_id": run_id, "failures": summary["failures"], "exception": summary.get("exception")}
    log.info("dbt_build_finished", extra={"fields": summary})

    uploaded = 0
    if bucket:
        uploaded += _upload(bucket, landing, "landing/booncore")
        for prefix in UPLOAD_PREFIXES:
            if (data / prefix).exists():
                uploaded += _upload(bucket, data / prefix, prefix)
    log.info("pipeline_finished", extra={"fields": {"status": "success", "objects_uploaded": uploaded}})
    return {"status": "success", "run_id": run_id, "ingest_date": ingest_date, "objects_uploaded": uploaded, "dbt": summary["statuses"]}


if __name__ == "__main__":  # local smoke test: python -m mc_pipelines.lambda_handler
    print(json.dumps(handler({}, None)))
