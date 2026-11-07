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


def write_parquet(rows: list[dict], path: Path) -> None:
    from datetime import date
    cols = {k: [(date.fromisoformat(r[k]) if k == "date" else r[k]) for r in rows] for k in _SCHEMA.names}
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=_SCHEMA), path)


def summary(rows: list[dict], run_id: str) -> dict:
    """PG-8 block: calls, tokens, cost and mean latency by model. Status `awaiting_first_events` while empty."""
    base = {"schema_version": "dogfood.v0", "run_id": run_id, "data_label": "real", "tenant_id": TENANT}
    if not rows:
        return {**base, "status": "awaiting_first_events", "by_model": [], "total_calls": 0, "total_cost_usd": 0.0}
    by: dict[str, dict] = {}
    for r in rows:
        m = by.setdefault(r["model_id"], {"calls": 0, "cost": Decimal(0), "lat": 0, "in": 0, "out": 0})
        m["calls"] += r["calls"]; m["cost"] += r["cost_usd"]; m["lat"] += r["latency_ms_total"]  # noqa: E702
        m["in"] += r["input_tokens"]; m["out"] += r["output_tokens"]  # noqa: E702
    models = [{"model_id": k, "calls": v["calls"], "input_tokens": v["in"], "output_tokens": v["out"],
               "cost_usd": float(round(v["cost"], 6)), "mean_latency_ms": round(v["lat"] / v["calls"])}
              for k, v in sorted(by.items())]
    return {**base, "status": "ok", "by_model": models, "first_date": min(r["date"] for r in rows),
            "last_date": max(r["date"] for r in rows), "total_calls": sum(m["calls"] for m in models),
            "total_cost_usd": float(round(sum(v["cost"] for v in by.values()), 6))}


def read_summary(path: Path, run_id: str) -> dict:
    """Summary of a compacted `telemetry/dogfood.parquet`."""
    rows = [{**r, "date": r["date"].isoformat()} for r in pq.read_table(path).to_pylist()]
    return summary(rows, run_id)


def export_day(logs, s3, bucket: str, log_group: str, day: str, work: Path) -> dict:
    """Compact one UTC day of `gen_ai_call` events from CloudWatch Logs into `telemetry/dogfood.parquet`.

    Re-running a day replaces that day's rows, so the export is idempotent. `logs` and `s3` are boto3 clients.
    """
    from datetime import UTC, date, datetime, timedelta
    start = datetime.fromisoformat(day).replace(tzinfo=UTC)
    kw = {"logGroupName": log_group, "filterPattern": '"gen_ai_call"',
          "startTime": int(start.timestamp() * 1000), "endTime": int((start + timedelta(days=1)).timestamp() * 1000) - 1}
    lines: list[str] = []
    while True:
        page = logs.filter_log_events(**kw)
        lines += [e["message"] for e in page.get("events", [])]
        if not page.get("nextToken"):
            break
        kw["nextToken"] = page["nextToken"]
    rows = compact(parse_events(lines, day))
    key, path = "telemetry/dogfood.parquet", work / "dogfood.parquet"
    work.mkdir(parents=True, exist_ok=True)
    old: list[dict] = []
    try:
        s3.download_file(bucket, key, str(path))
        old = [{**r, "date": r["date"].isoformat()} for r in pq.read_table(path).to_pylist() if r["date"] != date.fromisoformat(day)]
    except Exception as e:  # first run: nothing stored yet
        if "404" not in str(e) and "NoSuchKey" not in str(e) and not isinstance(e, FileNotFoundError):
            raise
    merged = sorted(old + rows, key=lambda r: (r["date"], r["model_id"]))
    write_parquet(merged, path)
    s3.upload_file(str(path), bucket, key)
    return {"day": day, "events": len(lines), "rows": len(merged)}
