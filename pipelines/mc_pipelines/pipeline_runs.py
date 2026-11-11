"""M6-01 telemetry lake (PLAN.md §14): the pipeline's own structured logs -> `telemetry/pipeline_runs.parquet`.

One row per `run_id` and UTC day: first and last event time, final status, event and error counts. Only metadata
from the JSON log lines (`JsonFormatter`), never data content. Compacted daily by the `telemetry` profile.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import pyarrow as pa

from .dogfood import fetch_day, merge_day

KEY = "telemetry/pipeline_runs.parquet"
FILTER = '{ $.component = "pipeline" }'
SCHEMA = pa.schema([
    ("date", pa.date32()), ("run_id", pa.string()), ("first_ts", pa.string()), ("last_ts", pa.string()),
    ("duration_s", pa.float64()), ("status", pa.string()), ("events", pa.int64()), ("errors", pa.int64()),
])


def parse_events(lines: Iterable[str]) -> list[dict]:
    """Keep pipeline JSON log lines with a `run_id` and a timestamp; skip everything else."""
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
            if not isinstance(ev, dict) or ev.get("component") != "pipeline" or not ev.get("run_id"):
                continue
            ts = datetime.fromisoformat(str(ev["ts"]))
        except (ValueError, KeyError):
            continue
        out.append({"ts": ts, "run_id": str(ev["run_id"]), "level": str(ev.get("level", "")),
                    "event": str(ev.get("event", "")), "status": ev.get("status")})
    return out


def _status(evs: list[dict]) -> str:
    for e in reversed(evs):
        if e["event"] == "pipeline_finished" and e["status"]:
            return str(e["status"])
    failed = [e["event"] for e in evs if e["event"].endswith("_failed")]
    return failed[-1] if failed else "incomplete"


def compact(events: list[dict]) -> list[dict]:
    """One row per (day, run_id), sorted; the same events always give the same rows."""
    by: dict[tuple[str, str], list[dict]] = {}
    for e in sorted(events, key=lambda e: e["ts"]):
        by.setdefault((e["ts"].date().isoformat(), e["run_id"]), []).append(e)
    return [{"date": d, "run_id": r, "first_ts": evs[0]["ts"].isoformat(), "last_ts": evs[-1]["ts"].isoformat(),
             "duration_s": round((evs[-1]["ts"] - evs[0]["ts"]).total_seconds(), 3), "status": _status(evs),
             "events": len(evs), "errors": sum(e["level"] in ("ERROR", "CRITICAL") for e in evs)}
            for (d, r), evs in sorted(by.items())]


def export_day(logs, s3, bucket: str, log_group: str, day: str, work: Path) -> dict:
    """Compact one UTC day of the pipeline log group into `telemetry/pipeline_runs.parquet` (idempotent per day)."""
    lines = fetch_day(logs, log_group, FILTER, day)
    rows = [r for r in compact(parse_events(lines)) if r["date"] == day]
    n = merge_day(s3, bucket, KEY, rows, day, work / "pipeline_runs.parquet", SCHEMA,
                  sort_key=lambda r: (r["date"], r["first_ts"], r["run_id"]))
    return {"day": day, "events": len(lines), "runs": len(rows), "rows": n}
