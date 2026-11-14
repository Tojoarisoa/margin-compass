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
    assert dogfood.read_summary(p, "r1") == dogfood.summary(rows, "r1")
    s = dogfood.summary(rows, "r1")
    assert s["status"] == "ok" and s["total_cost_usd"] == 0.0035 and s["mean_latency_ms"] == 167
    assert s["by_month"] == [{"month": "2026-11", "cost_usd": 0.0035, "input_tokens": 160, "output_tokens": 35}]


def test_public_summary_has_no_model_names_or_call_counts():
    """dogfood.json is public: no model names, call counts or per-answer cost (AGENTS.md §6)."""
    s = dogfood.summary(dogfood.compact(dogfood.parse_events(LINES)), "r1")
    text = json.dumps(s).lower()
    assert "haiku" not in text and "sonnet" not in text and "model" not in text and "calls" not in text
    assert "per_question" not in text and "per_answer" not in text


def test_empty_summary():
    assert dogfood.summary([], "r1")["status"] == "awaiting_first_events"


class FakeLogs:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def filter_log_events(self, **kw):
        self.calls.append(kw)
        return self.pages[len(self.calls) - 1]


class FakeS3:
    def __init__(self, root):
        self.root = root

    def download_file(self, bucket, key, dst):
        import shutil
        shutil.copy(self.root / bucket / key, dst)

    def upload_file(self, src, bucket, key):
        import shutil
        dst = self.root / bucket / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)


def _api(model, cost):
    return json.dumps({"level": "INFO", "event": "gen_ai_call", "gen_ai.request.model": model,
                       "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 2, "mc.cost_usd": cost, "mc.latency_ms": 50})


def test_export_day_is_idempotent_and_replaces_only_that_day(tmp_path):
    s3 = FakeS3(tmp_path / "s3")
    pages = [{"events": [{"message": _api("haiku", "0.001")}], "nextToken": "t"}, {"events": [{"message": _api("haiku", "0.002")}]}]
    out = dogfood.export_day(FakeLogs(pages), s3, "b", "grp", "2026-11-06", tmp_path / "w")
    assert out == {"day": "2026-11-06", "events": 2, "rows": 1}
    again = dogfood.export_day(FakeLogs(pages), s3, "b", "grp", "2026-11-06", tmp_path / "w")
    assert again["rows"] == 1
    dogfood.export_day(FakeLogs([{"events": [{"message": _api("sonnet", "0.01")}]}]), s3, "b", "grp", "2026-11-07", tmp_path / "w")
    s = dogfood.read_summary(tmp_path / "s3" / "b" / "telemetry" / "dogfood.parquet", "r")
    assert s["total_cost_usd"] == 0.013 and s["first_date"] == "2026-11-06" and s["last_date"] == "2026-11-07"
