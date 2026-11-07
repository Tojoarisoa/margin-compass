import json

import pyarrow.parquet as pq

from mc_pipelines import dogfood


def _ev(ts, model, i, o, cost, lat=100):
    return json.dumps({"timestamp": ts, "message": "gen_ai_call", "fields": {
        "gen_ai.request.model": model, "gen_ai.usage.input_tokens": i, "gen_ai.usage.output_tokens": o,
        "mc.cost_usd": cost, "mc.latency_ms": lat}})


LINES = [_ev("2026-11-06T10:00:00Z", "haiku", 100, 20, "0.001"), _ev("2026-11-06T11:00:00Z", "haiku", 50, 10, "0.0005", 300),
         _ev("2026-11-07T01:00:00Z", "sonnet", 10, 5, "0.002"), "not json", json.dumps({"message": "other"}),
         json.dumps({"message": "gen_ai_call", "fields": {}})]


def test_parse_skips_bad_lines():
    assert len(dogfood.parse_events(LINES)) == 3


def test_compact_summary_and_parquet(tmp_path):
    rows = dogfood.compact(dogfood.parse_events(LINES))
    assert [(r["date"], r["model_id"], r["calls"]) for r in rows] == [("2026-11-06", "haiku", 2), ("2026-11-07", "sonnet", 1)]
    assert dogfood.compact(dogfood.parse_events(LINES)) == rows
    p = tmp_path / "telemetry" / "dogfood.parquet"
    dogfood.write_parquet(rows, p)
    assert pq.read_table(p).num_rows == 2
    s = dogfood.summary(rows, "r1")
    assert s["status"] == "ok" and s["total_calls"] == 3 and s["total_cost_usd"] == 0.0035
    assert s["by_model"][0]["mean_latency_ms"] == 200


def test_empty_summary():
    assert dogfood.summary([], "r1")["status"] == "awaiting_first_events"
