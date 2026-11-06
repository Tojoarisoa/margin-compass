"""M2-02 step 1: the M2 silver pricing model, against the simulator's own Python pricing (one month, seed 42)."""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from booncore_sim.m2_catalog import PRICE_CATALOG_V2, price_on, request_cost_usd
from booncore_sim.m2_tenants import generate_m2_tenants
from booncore_sim.m2_writer import _write, write_month
from mc_pipelines.cli import TRANSFORM_DIR

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    from dbt.cli.main import dbtRunner

    root = tmp_path_factory.mktemp("m2")
    landing = root / "landing"
    tenants = generate_m2_tenants(42)[0]
    month = 5  # 2025-09: before the b-mid price cut, so cutover is covered by a unit test below
    write_month(landing, 42, tenants, month)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    (root / "silver").mkdir()
    os.environ["MC_DUCKDB_PATH"] = str(root / "m2.duckdb")
    variables = {"m2_landing_path": str(landing), "silver_path": str(root / "silver"),
                 "bronze_path": "x", "gold_path": str(root / "gold")}
    result = dbtRunner().invoke([
        "build", "--select", "stg_m2_telemetry", "stg_m2_price_catalog", "slv_m2_llm_usage_priced",
        "--project-dir", str(TRANSFORM_DIR), "--profiles-dir", str(TRANSFORM_DIR),
        "--target-path", str(root / "target"), "--log-path", str(root / "logs"),
        "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    return root / "silver" / "slv_m2_llm_usage_priced.parquet"


def test_every_row_is_priced_and_matches_python_pricing(built):
    rows = duckdb.sql(
        f"select usage_date, model_id, is_batch, input_tokens, cached_input_tokens, output_tokens, llm_cost_usd "
        f"from '{built}' using sample 300 rows (reservoir, 1)").fetchall()
    assert rows
    for d, model, batch, i, c, o, cost in rows:
        want = request_cost_usd(price_on(model, d), input_tokens=i, cache_read_tokens=c, output_tokens=o, batch=batch)
        assert abs(float(cost) - want) < 2e-6


def test_no_unpriced_rows_and_batch_rows_are_priced(built):
    n_null, n_rows, n_batch = duckdb.sql(
        f"select count(*) filter (where llm_cost_usd is null), count(*), count(*) filter (where is_batch) from '{built}'"
    ).fetchall()[0]
    assert n_null == 0 and n_rows > 0 and n_batch > 0


def test_price_change_boundary_is_exclusive_on_effective_to():
    cut = date(2026, 3, 1)
    assert price_on("b-mid", date(2026, 2, 28)).effective_to == cut
    assert price_on("b-mid", cut).effective_from == cut


def test_focus_staging_matches_the_generator(tmp_path):
    from dbt.cli.main import dbtRunner

    from booncore_sim import m2_focus
    from booncore_sim.m2_writer import write_focus

    tenants = generate_m2_tenants(42)[0]
    landing = tmp_path / "landing"
    write_focus(landing, 42, tenants)
    os.environ["MC_DUCKDB_PATH"] = str(tmp_path / "f.duckdb")
    variables = {"m2_landing_path": str(landing), "silver_path": str(tmp_path / "s"), "bronze_path": "x",
                 "gold_path": "x"}
    result = dbtRunner().invoke([
        "build", "--select", "stg_m2_focus", "--project-dir", str(TRANSFORM_DIR), "--profiles-dir", str(TRANSFORM_DIR),
        "--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l"), "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    db = duckdb.connect(str(tmp_path / "f.duckdb"))
    n, total, untagged = db.sql("select count(*), sum(effective_cost), count(*) filter (where feature_tag is null) "
                                "from stg_m2_focus").fetchall()[0]
    rows = m2_focus.generate_all(42, tenants)
    assert n == len(rows) and abs(float(total) - sum(r.effective_cost for r in rows)) < 0.5
    assert untagged == 0


def test_revenue_daily_sums_to_each_invoice_line_to_the_cent(tmp_path):
    from dbt.cli.main import dbtRunner

    from booncore_sim.m2_writer import write_revenue

    tenants, history = generate_m2_tenants(42)
    landing = tmp_path / "landing"
    write_revenue(landing, 42, tenants, history)
    (tmp_path / "silver").mkdir()
    os.environ["MC_DUCKDB_PATH"] = str(tmp_path / "r.duckdb")
    variables = {"m2_landing_path": str(landing), "silver_path": str(tmp_path / "silver"), "bronze_path": "x",
                 "gold_path": "x"}
    result = dbtRunner().invoke([
        "build", "--select", "+slv_m2_revenue_daily", "--project-dir", str(TRANSFORM_DIR),
        "--profiles-dir", str(TRANSFORM_DIR), "--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l"),
        "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    out = tmp_path / "silver" / "slv_m2_revenue_daily.parquet"
    bad = duckdb.sql(f"""
        select count(*) from (
          select invoice_id, revenue_component, sum(amount_usd) as daily
          from '{out}' group by 1, 2) d
        join (select invoice_id, line_type, sum(amount_usd) as inv
              from '{landing}/s3_revenue/invoices.parquet' group by 1, 2) i
          on i.invoice_id = d.invoice_id and i.line_type = d.revenue_component
        where d.daily <> i.inv""").fetchall()[0][0]
    assert bad == 0
    n_days, n_neg = duckdb.sql(f"select count(*), count(*) filter (where amount_usd < 0) from '{out}'").fetchall()[0]
    assert n_days > 0 and n_neg > 0


def test_outcomes_daily_joins_usage_at_tenant_day(tmp_path):
    from dbt.cli.main import dbtRunner

    from booncore_sim import m2_outcomes

    tenants = generate_m2_tenants(42)[0]
    landing = tmp_path / "landing"
    month = 5
    write_month(landing, 42, tenants, month)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    (tmp_path / "silver").mkdir()
    os.environ["MC_DUCKDB_PATH"] = str(tmp_path / "o.duckdb")
    variables = {"m2_landing_path": str(landing), "silver_path": str(tmp_path / "silver"), "bronze_path": "x",
                 "gold_path": "x"}
    result = dbtRunner().invoke([
        "build", "--select", "+slv_m2_outcomes_daily", "stg_m2_tickets", "--project-dir", str(TRANSFORM_DIR),
        "--profiles-dir", str(TRANSFORM_DIR), "--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l"),
        "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    out = tmp_path / "silver" / "slv_m2_outcomes_daily.parquet"
    daily, _ = m2_outcomes.generate_month(42, tenants, month)
    n, tickets, dup, with_usage = duckdb.sql(
        f"select count(*), sum(tickets), count(*) - count(distinct (tenant_id, outcome_date)), "
        f"count(*) filter (where requests > 0) from '{out}'").fetchall()[0]
    assert n == len(daily) and tickets == sum(r.tickets for r in daily)
    assert dup == 0  # the usage join must not fan out outcome rows
    assert with_usage > 0.9 * n
    db = duckdb.connect(str(tmp_path / "o.duckdb"))
    assert db.sql("select count(*) from stg_m2_tickets").fetchall()[0][0] > 0


@pytest.fixture(scope="module")
def allocated(tmp_path_factory):
    from dbt.cli.main import dbtRunner

    from booncore_sim.m2_writer import write_focus, write_revenue
    from mc_pipelines.allocation import load_rules

    root = tmp_path_factory.mktemp("alloc")
    landing = root / "landing"
    tenants = generate_m2_tenants(42)[0]
    month = 5  # 2025-09
    write_month(landing, 42, tenants, month)
    write_focus(landing, 42, tenants)
    write_revenue(landing, 42, *generate_m2_tenants(42))
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    (root / "silver").mkdir()
    (root / "gold").mkdir()
    os.environ["MC_DUCKDB_PATH"] = str(root / "a.duckdb")
    variables = {"m2_landing_path": str(landing), "silver_path": str(root / "silver"), "bronze_path": "x",
                 "gold_path": str(root / "gold"), "allocation_rules": load_rules()}
    result = dbtRunner().invoke([
        "build", "--select", "+fct_infra_cost_allocated", "+fct_cost_to_serve", "+fct_unit_cost", "+fct_quality", "+fct_m2_tenant_margin", "--project-dir", str(TRANSFORM_DIR),
        "--profiles-dir", str(TRANSFORM_DIR), "--target-path", str(root / "t"), "--log-path", str(root / "l"),
        "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    return root / "gold" / "fct_infra_cost_allocated.parquet", landing


def test_infra_allocated_plus_unallocated_equals_billed_exactly(allocated):
    out, landing = allocated
    # Billed is read straight from the landed FOCUS file, independent of the allocation model.
    # September 2025 only: the focus file spans the window, the telemetry chunk does not.
    billed = duckdb.sql(f"select sum(effective_cost) from '{landing}/s2_focus/focus.parquet' "
                        f"where cast(charge_period_start as date) between date '2025-09-01' and date '2025-09-30'"
                        ).fetchall()[0][0]
    got, unalloc = duckdb.sql(
        f"select sum(allocated_cost_usd), sum(allocated_cost_usd) filter (where rule_id = 'UNALLOCATED') "
        f"from '{out}' where cost_date between date '2025-09-01' and date '2025-09-30'").fetchall()[0]
    assert got == Decimal(str(round(billed, 4)))  # exact, 4-decimal units
    assert unalloc > 0  # staging overhead is shown, not hidden


def test_infra_allocation_uses_each_rule_and_never_negative(allocated):
    out, _ = allocated
    rules = {r[0] for r in duckdb.sql(f"select distinct rule_id from '{out}'").fetchall()}
    assert {"AR-01-agent-compute", "AR-02-vector-storage", "AR-04-egress", "UNALLOCATED"} <= rules
    assert duckdb.sql(f"select count(*) from '{out}' where allocated_cost_usd < 0").fetchall()[0][0] == 0
    # Unallocated rows carry no tenant; allocated rows always do.
    bad = duckdb.sql(f"select count(*) from '{out}' where (rule_id = 'UNALLOCATED') <> (tenant_id is null)").fetchall()[0][0]
    assert bad == 0


def test_cost_to_serve_preserves_llm_and_allocated_infra(allocated):
    out, _ = allocated
    gold = out.parent
    silver = out.parent.parent / "silver"
    llm_billed, infra_alloc = duckdb.sql(
        f"select (select sum(llm_cost_usd) from '{silver}/slv_m2_llm_usage_priced.parquet'), "
        f"(select sum(allocated_cost_usd) from '{out}' where rule_id <> 'UNALLOCATED')").fetchall()[0]
    llm, infra, total, dup = duckdb.sql(
        f"select sum(llm_cost_usd), sum(infra_cost_usd), sum(cost_to_serve_usd), "
        f"count(*) - count(distinct (cost_date, tenant_id, feature_id)) from '{gold}/fct_cost_to_serve.parquet'"
    ).fetchall()[0]
    assert llm == llm_billed and infra == infra_alloc  # no cost lost or doubled by the full outer join
    assert total == llm + infra
    assert dup == 0


def test_unit_cost_and_quality_recompute_from_sums(allocated):
    from booncore_sim import m2_outcomes

    out, _ = allocated
    gold = out.parent
    silver = gold.parent / "silver"
    billed = duckdb.sql(f"select sum(llm_cost_usd), sum(request_count) from '{silver}/slv_m2_llm_usage_priced.parquet'").fetchall()[0]
    cost, reqs, dup = duckdb.sql(
        f"select sum(llm_cost_usd), sum(requests), count(*) - count(distinct (cost_date, feature_id, model_id)) "
        f"from '{gold}/fct_unit_cost.parquet'").fetchall()[0]
    assert cost == billed[0] and reqs == billed[1] and dup == 0
    # Safety recall rolled up from summed counts equals the generator's recomputed recall.
    tenants = generate_m2_tenants(42)[0]
    daily, _ = m2_outcomes.generate_month(42, tenants, 5)
    flagged, labeled = duckdb.sql(
        f"select sum(safety_events_flagged), sum(safety_events_labeled) from '{gold}/fct_quality.parquet'").fetchall()[0]
    assert abs(flagged / labeled - m2_outcomes.safety_event_recall(daily)) < 1e-12


def test_fully_loaded_margin_keeps_revenue_and_cost(allocated):
    out, landing = allocated
    gold = out.parent
    rev_src = duckdb.sql(f"select sum(amount_usd) from '{landing}/s3_revenue/invoices.parquet'").fetchall()[0][0]
    cost_src = duckdb.sql(f"select sum(cost_to_serve_usd) from '{gold}/fct_cost_to_serve.parquet'").fetchall()[0][0]
    rev, cost, margin, dup, discounts = duckdb.sql(
        f"select sum(revenue_usd), sum(cost_to_serve_usd), sum(margin_usd), "
        f"count(*) - count(distinct (margin_date, tenant_id)), sum(discount_usd) "
        f"from '{gold}/fct_m2_tenant_margin.parquet'").fetchall()[0]
    assert rev == rev_src and cost == cost_src and dup == 0
    assert margin == rev - cost
    assert discounts < 0  # discounts stay visible as their own negative component
