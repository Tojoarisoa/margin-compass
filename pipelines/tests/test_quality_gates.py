"""M1-03: every quality gate must actually fire. Each test breaks the landing data in a way ingest
accepts (contracted schema, matching manifest), so only the Stage 2-3 gates can catch it."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from booncore_sim.cli import run as simulate
from mc_pipelines.cli import main as pipeline_main

INGEST_DATE = "2026-11-03"
TELEMETRY = "s1_llm_telemetry/telemetry_daily.parquet"


@pytest.fixture(scope="module")
def clean_landing(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("landing")
    simulate("m1", None, d, run_id="test")
    return d


def tamper(clean: Path, tmp: Path, rel: str, change) -> Path:
    """Copy the landing folder, rewrite one file with `change(table) -> table`, and keep the
    producer manifest consistent (hash and rows), so ingest accepts it."""
    landing = tmp / "landing"
    shutil.copytree(clean, landing)
    path = landing / rel
    original = pq.read_table(path)
    table = change(original).cast(original.schema)  # same contracted schema and metadata
    pq.write_table(table, path, compression="zstd")
    manifest = json.loads((landing / "manifest.json").read_text())
    for f in manifest["files"]:
        if f["path"] == rel:
            f["sha256"], f["rows"] = hashlib.sha256(path.read_bytes()).hexdigest(), table.num_rows
    (landing / "manifest.json").write_text(json.dumps(manifest))
    return landing


def run(landing: Path, data: Path) -> tuple[int, dict]:
    code = pipeline_main(["run", "--landing", str(landing), "--data-root", str(data), "--ingest-date", INGEST_DATE])
    scorecard = json.loads((data / "gold/_quality/scorecard.json").read_text())
    return code, scorecard


def failed(scorecard: dict) -> set[str]:
    return {e["test"] for e in scorecard["errors"]}


def set_cell(table: pa.Table, column: str, row: int, value) -> pa.Table:
    values = table.column(column).to_pylist()
    values[row] = value
    return table.set_column(table.schema.get_field_index(column), column, pa.array(values, table.schema.field(column).type))


# --- Clean run ----------------------------------------------------------------------------------
def test_clean_data_passes_ev01_with_all_contracts_enforced(clean_landing, tmp_path):
    code, sc = run(clean_landing, tmp_path)
    assert code == 0 and sc["ev01_status"] == "pass"
    assert sc["contracts_enforced"] == ["agg_exec_kpis", "fct_llm_usage_daily", "fct_revenue_daily", "fct_tenant_margin"]
    assert set(sc["by_category"]) == {"contract", "preservation", "business_rule", "statistical"}
    assert (tmp_path / "gold/_quality/lineage.json").exists()
    lineage = json.loads((tmp_path / "gold/_quality/lineage.json").read_text())["models"]
    assert "slv_llm_usage_priced" in lineage["fct_llm_usage_daily"]


# --- Error gates: stop the run, quarantine the partition -----------------------------------------
def test_negative_tokens_fail_the_business_rule_and_quarantine_bronze(clean_landing, tmp_path):
    landing = tamper(clean_landing, tmp_path, TELEMETRY, lambda t: set_cell(t, "gen_ai_usage_output_tokens", 0, -5))
    code, sc = run(landing, tmp_path / "data")
    assert code == 3 and sc["ev01_status"] == "fail"
    assert "business_rule_no_negative_tokens" in failed(sc)
    assert not list((tmp_path / "data/bronze").glob(f"*/ingest_date={INGEST_DATE}"))
    assert (tmp_path / f"data/quarantine/s1_llm_telemetry/ingest_date={INGEST_DATE}/telemetry_daily.parquet").exists()
    assert (tmp_path / f"data/quarantine/_reason_ingest_date={INGEST_DATE}.json").exists()


def test_unpriced_model_fails_the_price_lookup_rule(clean_landing, tmp_path):
    landing = tamper(clean_landing, tmp_path, TELEMETRY, lambda t: set_cell(t, "gen_ai_request_model", 0, "z-unknown"))
    code, sc = run(landing, tmp_path / "data")
    assert code == 3
    assert any("price_effective_from" in name for name in failed(sc))


def test_tenant_starting_mid_window_fails_the_active_plan_rule(clean_landing, tmp_path):
    landing = tamper(clean_landing, tmp_path, "tenants/tenants.parquet", lambda t: set_cell(t, "contract_start", 0, date(2025, 9, 1)))
    code, sc = run(landing, tmp_path / "data")
    assert code == 3
    assert "business_rule_every_tenant_has_active_plan" in failed(sc)


def test_duplicate_usage_rows_fail_the_grain_contract(clean_landing, tmp_path):
    landing = tamper(clean_landing, tmp_path, TELEMETRY, lambda t: pa.concat_tables([t, t.slice(0, 1)]))
    code, sc = run(landing, tmp_path / "data")
    assert code == 3
    assert "contract_unique_usage_grain" in failed(sc)


# --- Attribution: rows warn and become unallocated; coverage below KPI-03 stops the run ------------
def test_usage_from_an_unknown_tenant_warns_and_is_shown_as_unallocated(clean_landing, tmp_path):
    landing = tamper(clean_landing, tmp_path, TELEMETRY, lambda t: set_cell(t, "tenant_id", 0, "bc-t9999"))
    code, sc = run(landing, tmp_path / "data")
    assert code == 0 and sc["ev01_status"] == "pass"
    assert any("relationships" in w["test"] for w in sc["warnings"])
    (unallocated, coverage), = duckdb.sql(f"""
        select sum(unallocated_llm_cost_usd), min(kpi03_llm_attribution_coverage_pct)
        from read_parquet('{tmp_path}/data/gold/agg_exec_kpis.parquet')""").fetchall()
    assert unallocated > 0 and coverage < 1  # visible on the dashboard
    # and the cost gate still balances (allocated + unallocated = total)
    assert sc["by_category"]["preservation"] == {"pass": 4}


def test_attribution_coverage_below_kpi03_stops_the_run(clean_landing, tmp_path):
    usage = pq.read_table(clean_landing / TELEMETRY)
    tenant_counts = pc.value_counts(usage.column("tenant_id"))
    busiest = max(tenant_counts.to_pylist(), key=lambda v: v["counts"])["values"]  # an enterprise tenant
    landing = tamper(clean_landing, tmp_path, TELEMETRY, lambda t: t.set_column(
        t.schema.get_field_index("tenant_id"), "tenant_id",
        pc.if_else(pc.equal(t.column("tenant_id"), busiest), "bc-t9999", t.column("tenant_id"))))
    code, sc = run(landing, tmp_path / "data")
    assert code == 3 and sc["ev01_status"] == "fail"
    assert "business_rule_attribution_coverage_meets_kpi03" in failed(sc)


# --- Warn gate: continue, annotate ---------------------------------------------------------------
def test_a_day_without_usage_only_warns(clean_landing, tmp_path):
    missing = date(2025, 8, 15)
    landing = tamper(clean_landing, tmp_path, TELEMETRY,
                     lambda t: t.filter(pc.not_equal(t.column("usage_date"), pa.scalar(missing, pa.date32()))))
    code, sc = run(landing, tmp_path / "data")
    assert code == 0 and sc["ev01_status"] == "pass"
    assert [w["test"] for w in sc["warnings"]] == ["statistical_every_day_has_usage"]
