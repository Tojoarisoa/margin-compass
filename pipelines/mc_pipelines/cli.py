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
from datetime import UTC, date, datetime
from pathlib import Path

from .ingest import IngestError, ingest
from .quality import quarantine_partition, write_scorecard

log = logging.getLogger("mc_pipelines")
# The dbt project; overridable because the Lambda image keeps it outside the package.
TRANSFORM_DIR = Path(os.environ.get("MC_TRANSFORM_DIR", Path(__file__).resolve().parent.parent / "transform"))


class JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "run_id": self.run_id,
            "component": "pipeline",
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, sort_keys=True, default=str)


def _make_dbt_lambda_safe() -> None:
    """AWS Lambda has no /dev/shm, so anything built on POSIX semaphores fails (ENOENT/EROFS).

    dbt touches them in two places, both replaced here with thread-only equivalents:
    1. its multiprocessing context, used only for Lock and RLock (manifest, connection manager);
    2. DbtThreadPool, a multiprocessing.pool.ThreadPool whose internal queue needs a semaphore.
       dbt only calls apply_async(func, args, callback), close, join, terminate, is_closed, and
       reads max_threads / max_microbatch_models, so a ThreadPoolExecutor-backed pool suffices.
    Must run before dbt.cli.main is imported: dbt captures both at import time.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, wait
    from math import floor

    import dbt.mp_context

    class _ThreadLockContext:
        Lock = staticmethod(threading.Lock)
        RLock = staticmethod(threading.RLock)

    class _ExecutorPool:
        def __init__(self, processes, initializer=None, initargs=()):
            self.max_threads = processes
            self.max_microbatch_models = max(1, floor(processes / 2))
            self.closed = False
            self._executor = ThreadPoolExecutor(processes, initializer=initializer, initargs=tuple(initargs))
            self._futures = []

        def apply_async(self, func, args=(), kwds=None, callback=None):
            future = self._executor.submit(func, *args, **(kwds or {}))
            if callback is not None:
                # Like multiprocessing's pool: the callback runs only on success.
                future.add_done_callback(lambda f: callback(f.result()) if f.exception() is None else None)
            self._futures.append(future)
            return future

        def close(self):
            self.closed = True

        def is_closed(self):
            return self.closed

        def terminate(self):
            self.closed = True
            for future in self._futures:
                future.cancel()

        def join(self):
            wait(self._futures)
            self._executor.shutdown(wait=True)

    # Order matters: replace the lock factory before importing anything that imports dbt's manifest
    # module (dbt.graph does), because the manifest captures get_mp_context().Lock at import time.
    dbt.mp_context._MP_CONTEXT = _ThreadLockContext()

    import dbt.graph.thread_pool

    dbt.graph.thread_pool.DbtThreadPool = _ExecutorPool


def run_dbt(data_root: Path, ingest_date: str, window: dict, run_id: str, transform_dir: Path | None = None) -> dict:
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        _make_dbt_lambda_safe()
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
        "build", "--project-dir", str(transform_dir or TRANSFORM_DIR), "--profiles-dir", str(transform_dir or TRANSFORM_DIR),
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
    target = root / "dbt" / "target"
    if (target / "run_results.json").exists() and (target / "manifest.json").exists():
        scorecard = write_scorecard(root, target, run_id, ingest_date)
        summary["ev01_status"] = scorecard["ev01_status"]
        summary["warnings"] = [w["test"] for w in scorecard["warnings"]]
    if not summary["success"]:
        summary["quarantined"] = quarantine_partition(root, ingest_date, "dbt build failed (error-severity)")
    return summary


def run_m2_dbt(landing: Path, data_root: Path, run_id: str, transform_dir: Path | None = None) -> dict:
    """Build the M2 silver and gold marts from an M2 landing tree, with the M2 gates on, then write the M2 scorecard.

    Separate from `run_dbt` so the M1 build is unchanged (the M2 models are enabled only by var `m2_landing_path`).
    Error-severity gate failures make `success` false; drift findings are warnings in `gold/_quality/m2_scorecard.json`.
    """
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        _make_dbt_lambda_safe()
    from dbt.cli.main import dbtRunner

    from .allocation import load_rules
    from .drift import write_m2_scorecard
    from .quality import publish_m2_quality, write_m2_lineage

    root = data_root.resolve()
    variables = {
        "m2_landing_path": str(landing.resolve()), "bronze_path": str(root / "bronze"), "silver_path": str(root / "silver"),
        "gold_path": str(root / "gold"), "m2_gates": True, "allocation_rules": load_rules(), "run_id": run_id,
    }
    os.environ["MC_DUCKDB_PATH"] = str(root / "margin_compass_m2.duckdb")
    (root / "silver").mkdir(parents=True, exist_ok=True)
    (root / "gold").mkdir(parents=True, exist_ok=True)
    td = str(transform_dir or TRANSFORM_DIR)
    result = dbtRunner().invoke([
        "build", "--select", "path:models/m2", "tag:m2", "--project-dir", td, "--profiles-dir", td,
        "--target-path", str(root / "dbt_m2" / "target"), "--log-path", str(root / "dbt_m2" / "logs"),
        "--vars", json.dumps(variables), "--quiet"])
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
    if result.success:
        summary["drift_warnings"] = len(write_m2_scorecard(root / "gold", run_id)["warnings"])
        write_m2_lineage(root, root / "dbt_m2" / "target", run_id)
        try:  # M3-02: margin-leak detector over the new gold; a detector problem never fails the data build
            from mc_ml.leak_detector.run import run_detector

            summary["leaks"] = run_detector(root / "gold", landing / "labels" / "patterns.parquet", run_id)
        except Exception as exc:  # noqa: BLE001
            summary["leaks"] = {"error": str(exc)[:200]}
        try:  # M3-03: churn model (EV-11) on the landing's renewal events; never fails the data build
            from mc_ml.churn.run import run_churn

            summary["churn"] = run_churn(landing / "labels" / "renewal_events.parquet", root / "gold", run_id)
        except Exception as exc:  # noqa: BLE001
            summary["churn"] = {"error": str(exc)[:200]}
        summary["published"] = publish_m2_quality(root)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Margin Compass pipeline (ingest + dbt build).")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--landing", type=Path, default=Path("../data/local/landing/booncore"))
    run.add_argument("--data-root", type=Path, default=Path("../data/local"))
    run.add_argument("--ingest-date", default=date.today().isoformat())
    m2 = sub.add_parser("run-m2", help="Build the M2 silver/gold marts (with gates) from an M2 landing tree")
    m2.add_argument("--landing", type=Path, default=Path("../data/local/landing/booncore_m2"))
    m2.add_argument("--data-root", type=Path, default=Path("../data/local"))
    args = parser.parse_args(argv)

    run_id = str(uuid.uuid4())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(run_id))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False

    if args.command == "run-m2":
        log.info("m2_pipeline_started", extra={"fields": {"env": "local"}})
        summary = run_m2_dbt(args.landing, args.data_root, run_id)
        log.log(logging.INFO if summary["success"] else logging.ERROR, "m2_dbt_build_finished", extra={"fields": summary})
        return 0 if summary["success"] else 3

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

    # Stage 4 (M1-04): train the seasonal-naive AI COGS forecaster into the local file registry.
    from mc_ml.registry import FileRegistry
    from mc_ml.train import train_cogs_forecaster

    models_dir = args.data_root.resolve() / "models"
    try:
        train_cogs_forecaster(args.data_root.resolve() / "gold", models_dir, FileRegistry(models_dir / "registry.json"),
                              artifact_base_uri=str(models_dir), run_id=run_id)
    except Exception as exc:  # noqa: BLE001 - report any training failure as a failed run
        log.error("train_failed", extra={"fields": {"reason": str(exc)[:300]}})
        return 4

    # Stage 5 (M1-05): embed the knowledge corpus (local: hashing embedder, no network).
    from .embed import embed_knowledge

    try:
        log.info("embed_finished", extra={"fields": embed_knowledge(args.data_root.resolve())})
    except Exception as exc:  # noqa: BLE001 - report any embedding failure as a failed run
        log.error("embed_failed", extra={"fields": {"reason": str(exc)[:300]}})
        return 5

    # Publish (M1-07): gold -> publish/latest/pg1.json for the dashboard.
    from .publish import publish

    try:
        log.info("publish_finished", extra={"fields": publish(args.data_root.resolve(), run_id, args.ingest_date)})
    except Exception as exc:  # noqa: BLE001 - report any publish failure as a failed run
        log.error("publish_failed", extra={"fields": {"reason": str(exc)[:300]}})
        return 6
    log.info("pipeline_finished", extra={"fields": {"status": "success"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
