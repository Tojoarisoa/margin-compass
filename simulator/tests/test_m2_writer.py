"""M2-01 step 10: Parquet landing, one chunk per month."""

from __future__ import annotations

from datetime import date

import pyarrow.parquet as pq
import pytest

from booncore_sim import m2_patterns_b as pb
from booncore_sim import m2_run
from booncore_sim import m2_tenants as mt
from booncore_sim import m2_writer as w

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


def test_month_chunk_is_deterministic_and_synthetic(tenants, tmp_path):
    a = w.write_month(tmp_path / "a", SEED, tenants, 0)
    b = w.write_month(tmp_path / "b", SEED, tenants, 0)
    assert a == b
    assert {f["path"].split("/")[0] for f in a} == {"s1_llm_telemetry", "s4_outcomes"}
    assert all("month=2025-04" in f["path"] for f in a) and all(f["rows"] > 0 for f in a)
    meta = pq.read_metadata(tmp_path / "a" / a[0]["path"]).schema.to_arrow_schema().metadata
    assert meta[b"synthetic"] == b"true" and meta[b"seed"] == b"42"
    assert pq.read_table(tmp_path / "a" / a[0]["path"]).num_rows == a[0]["rows"]


def test_static_tables_and_manifest(tenants, tmp_path):
    ev = pb.RenewalEvent("bc-t0001", date(2026, 5, 1), 3.0, 4.0, 2.0, 0.1, 0.05, "renewed", 100000.0)
    run = m2_run.PatternedRun(tenants, [], [], [pb.pt13_seasonality_and_growth()], [ev], [])
    files = w.write_static(tmp_path, SEED, run)
    manifest = w.write_manifest(tmp_path, SEED, files)
    assert [f["path"] for f in manifest["files"]] == sorted(f["path"] for f in files)
    assert next(f for f in files if f["path"] == "tenants/tenants.parquet")["rows"] == 400
    assert manifest["synthetic"] is True and (tmp_path / "manifest.json").exists()
