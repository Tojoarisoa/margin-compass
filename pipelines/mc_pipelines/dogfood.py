"""M2-04 dogfood telemetry (S7): the agent API's `gen_ai_call` log events -> daily Parquet + a PG-8 summary.

Events carry no content (ADR-015), only model, token counts, cost and latency. They are compacted by day and model
and kept apart from BoonCore's margin (tenant `mc-demo`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TENANT = "mc-demo"
_SCHEMA = pa.schema([
    ("tenant_id", pa.string()), ("date", pa.date32()), ("model_id", pa.string()), ("calls", pa.int64()),
    ("input_tokens", pa.int64()), ("output_tokens", pa.int64()), ("cost_usd", pa.decimal128(18, 6)),
    ("latency_ms_total", pa.int64()),
])


def parse_events(lines: Iterable[str], date: str | None = None) -> list[dict]:
    """Keep well-formed `gen_ai_call` events; skip everything else (other log lines, bad JSON).

    The API logs `{"level", "event": "gen_ai_call", <flat fields>}` with no timestamp, so `date` (the UTC day of the
    CloudWatch event) is used when the line has none.
    """
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("event", ev.get("message", ev.get("msg"))) != "gen_ai_call":
            continue
        f = ev.get("fields", ev)
        try:
            out.append({"date": str(ev.get("timestamp", ev.get("ts", date)))[:10], "model_id": str(f["gen_ai.request.model"]),
                        "input_tokens": int(f["gen_ai.usage.input_tokens"]),
                        "output_tokens": int(f["gen_ai.usage.output_tokens"]),
                        "cost_usd": Decimal(str(f["mc.cost_usd"])), "latency_ms": int(f.get("mc.latency_ms", 0))})
        except (KeyError, ValueError, ArithmeticError):
            continue
    return out


def compact(events: list[dict]) -> list[dict]:
    """Sum events by (date, model); the same events always give the same rows."""
    agg: dict[tuple[str, str], dict] = {}
    for e in events:
        r = agg.setdefault((e["date"], e["model_id"]), {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                       "cost_usd": Decimal(0), "latency_ms_total": 0})
        r["calls"] += 1
        r["input_tokens"] += e["input_tokens"]
        r["output_tokens"] += e["output_tokens"]
        r["cost_usd"] += e["cost_usd"]
        r["latency_ms_total"] += e["latency_ms"]
    return [{"tenant_id": TENANT, "date": d, "model_id": m, **v} for (d, m), v in sorted(agg.items())]


def write_parquet(rows: list[dict], path: Path, schema: pa.Schema = _SCHEMA) -> None:
    from datetime import date
    cols = {k: [(date.fromisoformat(r[k]) if k == "date" else r[k]) for r in rows] for k in schema.names}
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=schema), path)


def summary(rows: list[dict], run_id: str) -> dict:
    """PG-8 block: the platform's own model spend by month, tokens and mean latency. `awaiting_first_events` while empty.

    `dogfood.json` is public (dashboard), so it carries no model names, call counts or per-answer cost (AGENTS.md §6
    public surfaces). Those stay in the internal `telemetry/dogfood.parquet`.
    """
    base = {"schema_version": "dogfood.v1", "run_id": run_id, "data_label": "real", "tenant_id": TENANT}
    if not rows:
        return {**base, "status": "awaiting_first_events", "by_month": [], "total_cost_usd": 0.0}
    by: dict[str, dict] = {}
    for r in rows:
        m = by.setdefault(r["date"][:7], {"cost": Decimal(0), "in": 0, "out": 0})
        m["cost"] += r["cost_usd"]; m["in"] += r["input_tokens"]; m["out"] += r["output_tokens"]  # noqa: E702
    months = [{"month": k, "cost_usd": float(round(v["cost"], 6)), "input_tokens": v["in"], "output_tokens": v["out"]}
              for k, v in sorted(by.items())]
    calls = sum(r["calls"] for r in rows)
    return {**base, "status": "ok", "by_month": months, "first_date": min(r["date"] for r in rows),
            "last_date": max(r["date"] for r in rows),
            "total_cost_usd": float(round(sum((v["cost"] for v in by.values()), Decimal(0)), 6)),
            "mean_latency_ms": round(sum(r["latency_ms_total"] for r in rows) / calls) if calls else 0}


def read_summary(path: Path, run_id: str) -> dict:
    """Summary of a compacted `telemetry/dogfood.parquet`."""
    rows = [{**r, "date": r["date"].isoformat()} for r in pq.read_table(path).to_pylist()]
    return summary(rows, run_id)


def fetch_day(logs, log_group: str, filter_pattern: str, day: str) -> list[str]:
    """All messages of one UTC day in `log_group` that match `filter_pattern` (every page)."""
    from datetime import UTC, datetime, timedelta
    start = datetime.fromisoformat(day).replace(tzinfo=UTC)
    kw = {"logGroupName": log_group, "filterPattern": filter_pattern,
          "startTime": int(start.timestamp() * 1000), "endTime": int((start + timedelta(days=1)).timestamp() * 1000) - 1}
    lines: list[str] = []
    while True:
        page = logs.filter_log_events(**kw)
        lines += [e["message"] for e in page.get("events", [])]
        if not page.get("nextToken"):
            break
        kw["nextToken"] = page["nextToken"]
    return lines


def merge_day(s3, bucket: str, key: str, rows: list[dict], day: str, path: Path, schema: pa.Schema,
              sort_key=lambda r: (r["date"], r["model_id"])) -> int:
    """Replace `day`'s rows in the Parquet object `key` with `rows` (idempotent); returns the stored row count."""
    from datetime import date
    path.parent.mkdir(parents=True, exist_ok=True)
    old: list[dict] = []
    try:
        s3.download_file(bucket, key, str(path))
        old = [{**r, "date": r["date"].isoformat()} for r in pq.read_table(path).to_pylist() if r["date"] != date.fromisoformat(day)]
    except Exception as e:  # first run: nothing stored yet
        if "404" not in str(e) and "NoSuchKey" not in str(e) and not isinstance(e, FileNotFoundError):
            raise
    merged = sorted(old + rows, key=sort_key)
    write_parquet(merged, path, schema)
    s3.upload_file(str(path), bucket, key)
    return len(merged)


def export_day(logs, s3, bucket: str, log_group: str, day: str, work: Path) -> dict:
    """Compact one UTC day of `gen_ai_call` events from CloudWatch Logs into `telemetry/dogfood.parquet`.

    Re-running a day replaces that day's rows, so the export is idempotent. `logs` and `s3` are boto3 clients.
    """
    lines = fetch_day(logs, log_group, '"gen_ai_call"', day)
    rows = compact(parse_events(lines, day))
    n = merge_day(s3, bucket, "telemetry/dogfood.parquet", rows, day, work / "dogfood.parquet", _SCHEMA)
    return {"day": day, "events": len(lines), "rows": n}
