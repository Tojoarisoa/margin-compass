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
