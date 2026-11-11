import json

import pyarrow.parquet as pq
from test_dogfood import FakeLogs, FakeS3

from mc_pipelines import pipeline_runs as pr


def _ev(ts, run, event, level="INFO", **f):
    return json.dumps({"ts": ts, "level": level, "run_id": run, "component": "pipeline", "event": event, **f})


LINES = [
    _ev("2026-11-06T02:00:00+00:00", "r1", "pipeline_started"),
    _ev("2026-11-06T02:00:30+00:00", "r1", "dbt_build_finished"),
    _ev("2026-11-06T02:01:00+00:00", "r1", "pipeline_finished", status="success", objects_uploaded=9),
    _ev("2026-11-06T03:00:00+00:00", "r2", "pipeline_started"),
    _ev("2026-11-06T03:00:05+00:00", "r2", "ingest_failed", level="ERROR", reason="x"),
    _ev("2026-11-06T04:00:00+00:00", "r3", "pipeline_started"),
    "START RequestId: abc", "not json", json.dumps({"component": "api", "run_id": "x", "ts": "2026-11-06T00:00:00+00:00"}),
    json.dumps({"component": "pipeline", "event": "no_run_id", "ts": "2026-11-06T00:00:00+00:00"}),
]


def test_compact_one_row_per_run_with_status_and_errors():
    rows = pr.compact(pr.parse_events(LINES))
    assert [(r["run_id"], r["status"], r["events"], r["errors"], r["duration_s"]) for r in rows] == [
        ("r1", "success", 3, 0, 60.0), ("r2", "ingest_failed", 2, 1, 5.0), ("r3", "incomplete", 1, 0, 0.0)]
    assert pr.compact(pr.parse_events(reversed(LINES))) == rows


def test_export_day_is_idempotent_and_keeps_other_days(tmp_path):
    s3 = FakeS3(tmp_path / "s3")
    pages = [{"events": [{"message": m} for m in LINES[:3]], "nextToken": "t"}, {"events": [{"message": m} for m in LINES[3:]]}]
    logs = FakeLogs(pages)
    out = pr.export_day(logs, s3, "b", "grp", "2026-11-06", tmp_path / "w")
    assert out == {"day": "2026-11-06", "events": len(LINES), "runs": 3, "rows": 3}
    assert logs.calls[0]["filterPattern"] == pr.FILTER and logs.calls[1]["nextToken"] == "t"
    assert pr.export_day(FakeLogs(pages), s3, "b", "grp", "2026-11-06", tmp_path / "w")["rows"] == 3
    nxt = [{"events": [{"message": _ev("2026-11-07T02:00:00+00:00", "r4", "pipeline_finished", status="success")}]}]
    assert pr.export_day(FakeLogs(nxt), s3, "b", "grp", "2026-11-07", tmp_path / "w")["rows"] == 4
    t = pq.read_table(tmp_path / "s3" / "b" / pr.KEY)
    assert t.schema == pr.SCHEMA and t.column("run_id").to_pylist() == ["r1", "r2", "r3", "r4"]
