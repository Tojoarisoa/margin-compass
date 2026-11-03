"""M1-02: ingest gate (Stage 1) and the local end-to-end pipeline (ingest + dbt build)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from booncore_sim.cli import run as simulate
from mc_pipelines.cli import main as pipeline_main
from mc_pipelines.ingest import IngestError, ingest

INGEST_DATE = "2026-11-03"


@pytest.fixture(scope="module")
def landing(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("landing")
    simulate("m1", None, d, run_id="test")
    return d


def copy_landing(landing: Path, tmp_path: Path) -> Path:
    target = tmp_path / "landing"
    shutil.copytree(landing, target)
    return target


# --- Ingest gate -------------------------------------------------------------------------------
def test_ingest_copies_every_file_into_a_dated_bronze_partition(landing, tmp_path):
    result = ingest(landing, tmp_path, INGEST_DATE, run_id="r1")
    assert len(result.files) == 6 and not result.quarantined
    assert (tmp_path / "bronze/s1_llm_telemetry/ingest_date=2026-11-03/telemetry_daily.parquet").exists()
    manifest = json.loads((tmp_path / "bronze/_manifests/ingest_date=2026-11-03/ingestion_manifest.json").read_text())
    assert manifest["run_id"] == "r1" and manifest["synthetic"] is True
    assert {f["path"] for f in manifest["files"]} == {f["path"] for f in result.files}


def test_every_manifest_file_lands_in_bronze(landing, tmp_path):
    """Files that share a partition (s3_revenue: subscriptions and invoices) must all survive."""
    result = ingest(landing, tmp_path, INGEST_DATE, run_id="r1")
    for record in result.files:
        source, name = record["path"].split("/", 1)
        landed = tmp_path / "bronze" / source / f"ingest_date={INGEST_DATE}" / name
        assert landed.exists(), record["path"]
        assert pq.read_metadata(landed).num_rows == record["rows"]


def test_reingesting_the_same_date_replaces_the_partition(landing, tmp_path):
    ingest(landing, tmp_path, INGEST_DATE, run_id="r1")
    stray = tmp_path / "bronze/tenants/ingest_date=2026-11-03/stray.parquet"
    stray.write_bytes(b"x")
    ingest(landing, tmp_path, INGEST_DATE, run_id="r2")
    assert not stray.exists()


def test_tampered_file_is_quarantined_and_bronze_is_untouched(landing, tmp_path):
    bad = copy_landing(landing, tmp_path)
    path = bad / "s3_revenue/invoices.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(IngestError):
        ingest(bad, tmp_path / "data", INGEST_DATE, run_id="r1")
    assert (tmp_path / "data/quarantine/s3_revenue/ingest_date=2026-11-03/invoices.parquet").exists()
    assert not (tmp_path / "data/bronze").exists()


def _rewrite(path: Path, table: pa.Table, manifest_path: Path) -> None:
    """Rewrite a landing file and update its manifest entry so only the contract check can catch it."""
    import hashlib

    pq.write_table(table, path)
    manifest = json.loads(manifest_path.read_text())
    rel = str(path.relative_to(manifest_path.parent))
    for f in manifest["files"]:
        if f["path"] == rel:
            f["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            f["rows"] = table.num_rows
    manifest_path.write_text(json.dumps(manifest))


def test_schema_drift_is_quarantined(landing, tmp_path):
    bad = copy_landing(landing, tmp_path)
    path = bad / "tenants/tenants.parquet"
    table = pq.read_table(path)
    table = table.rename_columns(["customer_id", *table.column_names[1:]])  # drifted column name
    _rewrite(path, table, bad / "manifest.json")
    with pytest.raises(IngestError, match="quarantined"):
        ingest(bad, tmp_path / "data", INGEST_DATE, run_id="r1")


def test_file_without_synthetic_label_is_quarantined(landing, tmp_path):
    bad = copy_landing(landing, tmp_path)
    path = bad / "tenants/tenants.parquet"
    table = pq.read_table(path).replace_schema_metadata({})
    _rewrite(path, table, bad / "manifest.json")
    with pytest.raises(IngestError):
        ingest(bad, tmp_path / "data", INGEST_DATE, run_id="r1")


# --- End to end (local) ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def built(landing, tmp_path_factory) -> Path:
    data = tmp_path_factory.mktemp("data")
    code = pipeline_main(["run", "--landing", str(landing), "--data-root", str(data), "--ingest-date", INGEST_DATE])
    assert code == 0
    return data


def q(sql: str):
    return duckdb.connect().sql(sql).fetchall()


def test_all_four_gold_marts_exist(built):
    for mart in ("fct_llm_usage_daily", "fct_revenue_daily", "fct_tenant_margin", "agg_exec_kpis"):
        assert (built / "gold" / f"{mart}.parquet").exists(), mart


def test_daily_revenue_adds_up_to_every_invoice_line_exactly(built):
    inv = built / "bronze/s3_revenue/ingest_date=2026-11-03/invoices.parquet"
    (matching, total), = q(f"""
        select count(*) filter (where d.total = i.amount_usd), count(*)
        from (select invoice_id, revenue_component, sum(amount_usd) as total
              from read_parquet('{built}/silver/slv_revenue_daily.parquet') group by all) d
        join read_parquet('{inv}') i on i.invoice_id = d.invoice_id and i.line_type = d.revenue_component""")
    assert matching == total == 120


def test_every_usage_row_is_priced(built):
    (unpriced,), = q(f"select count(*) from read_parquet('{built}/gold/fct_llm_usage_daily.parquet') where price_effective_from is null")
    assert unpriced == 0


def test_margin_covers_every_tenant_day_and_is_labeled_f1_only(built):
    (rows, scopes), = q(f"select count(*), list(distinct feature_scope) from read_parquet('{built}/gold/fct_tenant_margin.parquet')")
    assert rows == 20 * 90 and scopes == ["F1 only (M1)"]


def test_exec_kpis_have_one_row_per_day_with_full_attribution(built):
    (days, coverage), = q(f"select count(distinct kpi_date), min(kpi03_llm_attribution_coverage_pct) from read_parquet('{built}/gold/agg_exec_kpis.parquet')")
    assert days == 90 and coverage == 1


def test_pipeline_fails_cleanly_when_landing_is_missing(tmp_path):
    assert pipeline_main(["run", "--landing", str(tmp_path / "nope"), "--data-root", str(tmp_path), "--ingest-date", INGEST_DATE]) == 2


def test_lambda_safe_dbt_path_works_without_posix_semaphores(landing, tmp_path):
    """Reproduces AWS Lambda (no /dev/shm) on any machine: every POSIX semaphore fails, as it does in
    Lambda. The Lambda-only dbt patches (thread locks, executor-backed pool) must still give a passing
    build. Runs in a subprocess so neither the failure nor the patches leak into other tests.
    """
    import os
    import subprocess
    import sys

    script = f"""
import sys, _multiprocessing
class _NoShmSemLock:  # keeps the class constant multiprocessing reads at import; creation fails
    SEM_VALUE_MAX = _multiprocessing.SemLock.SEM_VALUE_MAX
    def __init__(self, *args, **kwargs):
        raise OSError(30, "Read-only file system (simulated: Lambda has no /dev/shm)")
_multiprocessing.SemLock = _NoShmSemLock
from mc_pipelines.cli import main
sys.exit(main(["run", "--landing", {str(landing)!r}, "--data-root", {str(tmp_path)!r}, "--ingest-date", {INGEST_DATE!r}]))
"""
    env = {**os.environ, "AWS_LAMBDA_FUNCTION_NAME": "pytest-lambda-path"}
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    events = [json.loads(line) for line in proc.stderr.splitlines() if line.startswith("{")]
    dbt = next(e for e in events if e["event"] == "dbt_build_finished")
    # Same outcome as a normal build: all 10 models built, every test passed, nothing failed or warned.
    assert dbt["success"] and set(dbt["statuses"]) == {"success", "pass"} and dbt["statuses"]["success"] == 10


def test_simulated_lambda_without_the_patches_fails(landing, tmp_path):
    """Guards the test above: without AWS_LAMBDA_FUNCTION_NAME the patches are off and dbt must fail."""
    import os
    import subprocess
    import sys

    script = f"""
import sys, _multiprocessing
class _NoShmSemLock:  # keeps the class constant multiprocessing reads at import; creation fails
    SEM_VALUE_MAX = _multiprocessing.SemLock.SEM_VALUE_MAX
    def __init__(self, *args, **kwargs):
        raise OSError(30, "Read-only file system (simulated)")
_multiprocessing.SemLock = _NoShmSemLock
from mc_pipelines.cli import main
sys.exit(main(["run", "--landing", {str(landing)!r}, "--data-root", {str(tmp_path)!r}, "--ingest-date", {INGEST_DATE!r}]))
"""
    env = {k: v for k, v in os.environ.items() if k != "AWS_LAMBDA_FUNCTION_NAME"}
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 3  # dbt build failed
