"""AWS Lambda entry point (M1-02, env dev): the same simulator -> ingest -> dbt build path as local,
run in /tmp, then uploaded to the S3 lake under landing/, bronze/, silver/, gold/, quarantine/.
Stage 4 trains the forecaster (M1-04); Stage 5 embeds knowledge/ into S3 Vectors (M1-05); publish
writes the PG-1 snapshot to publish/ (M1-07).

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
UPLOAD_PREFIXES = ("bronze", "silver", "gold", "quarantine", "models", "publish")


def _configure_logging(run_id: str) -> None:
    handler = logging.StreamHandler(sys.stdout)  # Lambda forwards stdout to CloudWatch Logs
    handler.setFormatter(JsonFormatter(run_id))
    for name in ("mc_pipelines", "booncore_sim", "mc_rag"):
        logger = logging.getLogger(name)
        logger.handlers[:] = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False


def _upload(bucket: str, local_root: Path, key_prefix: str) -> int:
    import boto3

    s3 = boto3.client("s3")
    count = 0
    for path in sorted(p for p in local_root.rglob("*") if p.is_file()):
        s3.upload_file(str(path), bucket, f"{key_prefix}/{path.relative_to(local_root).as_posix()}", ExtraArgs=_extra_args(path))
        count += 1
    return count


CONTENT_TYPES = {".json": "application/json", ".parquet": "application/vnd.apache.parquet", ".md": "text/markdown; charset=utf-8"}


def _extra_args(path: Path) -> dict:
    """Content type for objects CloudFront serves (publish/); snapshots revalidate after 5 minutes."""
    args = {"ContentType": CONTENT_TYPES.get(path.suffix, "application/octet-stream")}
    if "publish" in path.parts:
        args["CacheControl"] = "public, max-age=300"
    return args


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

    # Stage 4 (M1-04): forecaster -> artifacts (S3 models/) + registry (DynamoDB core table in AWS).
    from mc_ml.registry import DynamoRegistry, FileRegistry
    from mc_ml.train import train_cogs_forecaster

    table = os.environ.get("REGISTRY_TABLE", "")
    registry = DynamoRegistry(table) if table else FileRegistry(data / "models" / "registry.json")
    artifact_base = f"s3://{bucket}/models" if bucket else str(data / "models")
    train = train_cogs_forecaster(data / "gold", data / "models", registry, artifact_base, run_id)

    # Stage 5 (M1-05): knowledge/ -> Titan v2 -> S3 Vectors (hashing -> local file when VECTOR_* unset).
    from .embed import embed_knowledge

    try:
        rag = embed_knowledge(data)
    except Exception as exc:  # noqa: BLE001 - includes BudgetExceeded; gold and models are still uploaded
        log.error("embed_failed", extra={"fields": {"reason": str(exc)[:300]}})
        rag = {"error": type(exc).__name__}

    # Publish (M1-07): PG-1 snapshot. A publish failure keeps the previous publish/latest in S3.
    from .publish import publish

    try:
        pub = publish(data, run_id, ingest_date)
    except Exception as exc:  # noqa: BLE001
        log.error("publish_failed", extra={"fields": {"reason": str(exc)[:300]}})
        pub = {"error": type(exc).__name__}
        shutil.rmtree(data / "publish", ignore_errors=True)

    uploaded = 0
    if bucket:
        uploaded += _upload(bucket, landing, "landing/booncore")
        for prefix in UPLOAD_PREFIXES:
            if (data / prefix).exists():
                uploaded += _upload(bucket, data / prefix, prefix)
    status = "embed_failed" if "error" in rag else "publish_failed" if "error" in pub else "success"
    log.info("pipeline_finished", extra={"fields": {"status": status, "objects_uploaded": uploaded}})
    return {"status": status, "run_id": run_id, "ingest_date": ingest_date, "objects_uploaded": uploaded,
            "dbt": summary["statuses"], "model": {k: train[k] for k in ("version", "alias", "registered", "wape")},
            "rag": {k: rag[k] for k in ("chunks", "embedded", "unchanged", "deleted", "embedding_calls", "error") if k in rag},
            "publish": {k: pub[k] for k in ("bytes", "error") if k in pub}}


if __name__ == "__main__":  # local smoke test: python -m mc_pipelines.lambda_handler
    print(json.dumps(handler({}, None)))
