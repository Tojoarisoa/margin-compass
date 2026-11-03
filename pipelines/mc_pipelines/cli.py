"""`mc-pipeline run`: ingest (landing -> bronze) then `dbt build` (silver, gold), one run_id throughout.

Logs are JSON lines on stderr (PLAN.md §14): metadata only, never data content.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .ingest import IngestError, ingest

log = logging.getLogger("mc_pipelines")
TRANSFORM_DIR = Path(__file__).resolve().parent.parent / "transform"


class JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": self.run_id,
            "component": "pipeline",
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, sort_keys=True, default=str)


def run_dbt(data_root: Path, ingest_date: str, window: dict, run_id: str) -> dict:
    from dbt.cli.main import dbtRunner

    root = data_root.resolve()
    variables = {
        "bronze_path": str(root / "bronze"),
        "silver_path": str(root / "silver"),
        "gold_path": str(root / "gold"),
        "ingest_date": ingest_date,
        "window_start": window["start"],
        "window_end": window["end"],
        "run_id": run_id,
    }
    os.environ["MC_DUCKDB_PATH"] = str(root / "margin_compass.duckdb")
    (root / "silver").mkdir(parents=True, exist_ok=True)
    (root / "gold").mkdir(parents=True, exist_ok=True)
    args = [
        "build", "--project-dir", str(TRANSFORM_DIR), "--profiles-dir", str(TRANSFORM_DIR),
        "--target-path", str(root / "dbt" / "target"), "--log-path", str(root / "dbt" / "logs"),
        "--vars", json.dumps(variables), "--quiet",
    ]
    result = dbtRunner().invoke(args)
    statuses: dict[str, int] = {}
    failures = []
    for r in (result.result or []):
        status = str(r.status)
        statuses[status] = statuses.get(status, 0) + 1
        if status not in ("success", "pass"):
            failures.append({"node": r.node.unique_id, "status": status, "message": (r.message or "")[:300]})
    summary = {"success": bool(result.success), "statuses": statuses, "failures": failures}
    if result.exception:
        summary["exception"] = str(result.exception)[:300]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Margin Compass pipeline (ingest + dbt build).")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--landing", type=Path, default=Path("../data/local/landing/booncore"))
    run.add_argument("--data-root", type=Path, default=Path("../data/local"))
    run.add_argument("--ingest-date", default=date.today().isoformat())
    args = parser.parse_args(argv)

    run_id = str(uuid.uuid4())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(run_id))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False

    log.info("pipeline_started", extra={"fields": {"env": "local", "ingest_date": args.ingest_date}})
    try:
        result = ingest(args.landing, args.data_root, args.ingest_date, run_id)
    except IngestError as exc:
        log.error("ingest_failed", extra={"fields": {"reason": str(exc)}})
        return 2
    log.info("ingest_finished", extra={"fields": {"files": len(result.files), "window": result.window}})

    summary = run_dbt(args.data_root, args.ingest_date, result.window, run_id)
    level = logging.INFO if summary["success"] else logging.ERROR
    log.log(level, "dbt_build_finished", extra={"fields": summary})
    if not summary["success"]:
        return 3
    log.info("pipeline_finished", extra={"fields": {"status": "success"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
