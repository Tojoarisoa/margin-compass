import json
import shutil
from pathlib import Path

import pyarrow.parquet as pq

from mc_pipelines import m2_lambda
from mc_pipelines.lambda_handler import handler


class FakeS3:
    """A bucket on local disk: just the four calls m2_lambda makes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def upload_file(self, src, bucket, key, ExtraArgs=None):  # noqa: N803
        dst = self.root / bucket / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)

    def download_file(self, bucket, key, dst):
        shutil.copy(self.root / bucket / key, dst)

    def delete_object(self, Bucket, Key):  # noqa: N803
        (self.root / Bucket / Key).unlink(missing_ok=True)

    def get_paginator(self, _name):
        outer = self

        class P:
            def paginate(self, Bucket, Prefix):  # noqa: N803
                base = outer.root / Bucket
                keys = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
                yield {"Contents": [{"Key": k} for k in keys if k.startswith(Prefix)]}

        return P()


def test_bad_events_are_rejected(monkeypatch):
    monkeypatch.setenv("LAKE_BUCKET", "")
    assert handler({"profile": "m2", "step": "month", "month": 99}, None)["status"] == "bad_event"
    assert handler({"profile": "m2", "step": "nope"}, None)["status"] == "bad_event"


def test_month_chunk_is_uploaded_and_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_BUCKET", "lake")
    monkeypatch.setattr(m2_lambda, "WORK", tmp_path / "work")
    s3 = FakeS3(tmp_path / "s3")
    out = m2_lambda.handle({"profile": "m2", "step": "month", "month": 0}, "r1", s3)
    assert out["status"] == "success" and out["objects_uploaded"] >= 4
    key = tmp_path / "s3" / "lake" / m2_lambda.LANDING_PREFIX / "s1_llm_telemetry" / "month=2025-04" / "telemetry.parquet"
    assert key.exists()
    first = pq.read_table(key).num_rows
    assert first > 0
    m2_lambda.handle({"profile": "m2", "step": "month", "month": 0}, "r2", s3)  # re-run is idempotent
    assert pq.read_table(key).num_rows == first


def test_static_month_and_build_round_trip_through_s3(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_BUCKET", "lake")
    monkeypatch.setattr(m2_lambda, "WORK", tmp_path / "work")
    s3 = FakeS3(tmp_path / "s3")
    assert m2_lambda.handle({"profile": "m2", "step": "static"}, "r", s3)["status"] == "success"
    assert m2_lambda.handle({"profile": "m2", "step": "month", "month": 5}, "r", s3)["status"] == "success"
    out = m2_lambda.handle({"profile": "m2", "step": "build"}, "r", s3)
    assert out["status"] == "success", out
    assert (tmp_path / "s3" / "lake" / "gold" / "fct_cost_to_serve.parquet").exists()
    assert (tmp_path / "s3" / "lake" / "gold" / "_quality" / "m2_scorecard.json").exists()
    assert "forecast" in out  # M3-01: the build tries to train the forecaster (one month is too short, so it reports an error)
    runs = tmp_path / "s3" / "lake" / "publish" / "latest" / "runs.json"
    assert json.loads(runs.read_text())["runs"][0]["run_id"] == "r"
    m2_lambda.handle({"profile": "m2", "step": "build"}, "r2", s3)  # a second build is added, newest first
    assert [r["run_id"] for r in json.loads(runs.read_text())["runs"]] == ["r2", "r"]


def test_build_without_landing_reports_it(tmp_path, monkeypatch):
    monkeypatch.setenv("LAKE_BUCKET", "lake")
    monkeypatch.setattr(m2_lambda, "WORK", tmp_path / "work")
    (tmp_path / "s3" / "lake").mkdir(parents=True)
    assert m2_lambda.handle({"profile": "m2", "step": "build"}, "r", FakeS3(tmp_path / "s3"))["status"] == "no_landing"


def test_focus_export_is_fetched_and_missing_export_is_not_an_error(tmp_path):
    s3 = FakeS3(tmp_path / "s3")
    assert m2_lambda.fetch_focus_export(s3, "billing", tmp_path / "w") is None  # empty bucket
    f = tmp_path / "s3" / "billing" / "focus-1-2" / "data" / "a.parquet"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    (f.parent / "manifest.json").write_text("{}")
    glob = m2_lambda.fetch_focus_export(s3, "billing", tmp_path / "w")
    assert glob == f"{tmp_path / 'w'}/focus-1-2/**/*.parquet"
    assert (tmp_path / "w" / "focus-1-2" / "data" / "a.parquet").exists()
    assert not (tmp_path / "w" / "focus-1-2" / "data" / "manifest.json").exists()


def _fake_owner(monkeypatch, rows):
    """Stands in for mc_agents.owner (not installed in the pipelines env; tested in agents/tests/test_owner.py)."""
    import sys
    import types

    pkg, mod = types.ModuleType("mc_agents"), types.ModuleType("mc_agents.owner")
    mod.export_approvals = lambda table: rows
    mod.to_jsonl = lambda rs: "".join(json.dumps(r, sort_keys=True) + "\n" for r in rs)
    pkg.owner = mod
    monkeypatch.setitem(sys.modules, "mc_agents", pkg)
    monkeypatch.setitem(sys.modules, "mc_agents.owner", mod)


def test_approvals_are_exported_by_static_and_applied_by_months(tmp_path, monkeypatch):
    import booncore_sim.cli as sim_cli

    monkeypatch.setenv("LAKE_BUCKET", "lake")
    monkeypatch.setattr(m2_lambda, "WORK", tmp_path / "work")
    s3 = FakeS3(tmp_path / "s3")
    row = {"action_id": "act-000000000001", "action_type": "ACT-1", "target": "F4/cost", "decision": "approved",
           "approver": "owner", "rationale": "", "decided_at": "2025-07-01T00:00:00+00:00"}
    _fake_owner(monkeypatch, [row])
    calls = []

    def fake_run_m2(seed, out, mode, month, approvals_path=None):
        calls.append((mode, month, approvals_path and approvals_path.read_text()))
        return {"files": []}

    monkeypatch.setattr(sim_cli, "run_m2", fake_run_m2)
    out = m2_lambda.handle({"profile": "m2", "step": "static", "input": {"approvals": True}}, "r1", s3, table=object())
    assert out["status"] == "success" and out["approvals_exported"] == 1
    stored = (tmp_path / "s3" / "lake" / m2_lambda.APPROVALS_KEY).read_text()
    assert json.loads(stored) == row
    month = m2_lambda.handle({"profile": "m2", "step": "month", "month": 3}, "r1", s3)
    assert month["status"] == "success" and month["approvals_applied"] is True
    assert calls == [("static", None, None), ("month", 3, stored)]

    # The next backfill without the flag removes the export, so its months run without effects.
    assert m2_lambda.handle({"profile": "m2", "step": "static", "input": {}}, "r2", s3)["status"] == "success"
    assert not (tmp_path / "s3" / "lake" / m2_lambda.APPROVALS_KEY).exists()
    assert "approvals_applied" not in m2_lambda.handle({"profile": "m2", "step": "month", "month": 3}, "r2", s3)
    assert calls[-1] == ("month", 3, None)


def test_without_the_flag_approvals_are_neither_exported_nor_applied(tmp_path, monkeypatch):
    import booncore_sim.cli as sim_cli

    monkeypatch.setenv("LAKE_BUCKET", "lake")
    monkeypatch.setattr(m2_lambda, "WORK", tmp_path / "work")
    _fake_owner(monkeypatch, [{"action_id": "act-000000000001"}])
    s3 = FakeS3(tmp_path / "s3")
    calls = []
    monkeypatch.setattr(sim_cli, "run_m2", lambda seed, out, mode, month, approvals_path=None: calls.append(approvals_path) or {"files": []})
    for event in ({"step": "static"}, {"step": "static", "input": {"approvals": "yes"}}, {"step": "month", "month": 0}):
        out = m2_lambda.handle({"profile": "m2", **event}, "r1", s3, table=object())
        assert out["status"] == "success" and "approvals_exported" not in out
    assert calls == [None, None, None] and not (tmp_path / "s3" / "lake" / m2_lambda.APPROVALS_KEY).exists()
