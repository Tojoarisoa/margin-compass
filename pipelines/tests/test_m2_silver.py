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
from mc_pipelines import metrics
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
        "build", "--select", "+fct_infra_cost_allocated", "+fct_cost_to_serve", "+fct_unit_cost", "+fct_quality", "+fct_m2_tenant_margin", "+agg_m2_cost_per_outcome", "--project-dir", str(TRANSFORM_DIR),
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


def test_dimensions_scd2_has_one_current_row_and_no_gaps(tmp_path):
    from dbt.cli.main import dbtRunner

    from booncore_sim.m2_writer import write_dimensions

    tenants, history = generate_m2_tenants(42)
    landing = tmp_path / "landing"
    _write(landing, "tenants/tenants.parquet", tenants, 42, "tenants")
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    write_dimensions(landing, 42, history)
    (tmp_path / "gold").mkdir()
    os.environ["MC_DUCKDB_PATH"] = str(tmp_path / "d.duckdb")
    variables = {"m2_landing_path": str(landing), "silver_path": str(tmp_path / "s"), "bronze_path": "x",
                 "gold_path": str(tmp_path / "gold")}
    result = dbtRunner().invoke([
        "build", "--select", "dim_tenant", "dim_feature", "dim_model_price", "stg_m2_price_catalog",
        "--project-dir", str(TRANSFORM_DIR), "--profiles-dir", str(TRANSFORM_DIR), "--target-path", str(tmp_path / "t"),
        "--log-path", str(tmp_path / "l"), "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    g = tmp_path / "gold"
    bad_current = duckdb.sql(
        f"select count(*) from (select tenant_id from '{g}/dim_tenant.parquet' group by 1 "
        f"having count(*) filter (where is_current) <> 1)").fetchall()[0][0]
    # Versions of a tenant are contiguous: each valid_to equals the next valid_from.
    gaps = duckdb.sql(
        f"select count(*) from (select valid_to, lead(valid_from) over (partition by tenant_id order by valid_from) as nxt "
        f"from '{g}/dim_tenant.parquet') where valid_to is not null and valid_to <> nxt").fetchall()[0][0]
    assert bad_current == 0 and gaps == 0
    assert duckdb.sql(f"select count(*) from '{g}/dim_feature.parquet'").fetchall()[0][0] == 5
    assert duckdb.sql(f"select count(distinct tenant_id) from '{g}/dim_tenant.parquet'").fetchall()[0][0] == len(tenants)


M2_GATES = ["m2_preservation_infra_cost", "m2_preservation_llm_cost", "m2_preservation_revenue_invoice_line",
            "m2_preservation_revenue_period"]


def test_m2_scorecard_lists_drift_warnings_as_warnings(allocated):
    from mc_pipelines.drift import write_m2_scorecard

    out, _ = allocated
    card = write_m2_scorecard(out.parent, "run-test")
    on_disk = json.loads((out.parent / "_quality" / "m2_scorecard.json").read_text())
    assert on_disk == json.loads(json.dumps(card)) and on_disk["synthetic"] is True
    assert set(on_disk["checks"]) == {"volume_requests", "ratio_tokens_per_request", "ratio_cost_per_request"}
    for w in on_disk["warnings"]:  # drift never fails a build
        assert w["severity"] == "warn" and w["category"] == "statistical" and w["check"] in on_disk["checks"]


def test_cost_per_outcome_mart_matches_sources_and_registry(allocated):
    out, _ = allocated
    gold = out.parent
    cost, outcomes = duckdb.sql(
        f"select sum(cost_to_serve_usd), sum(resolved_remotely) from '{gold}/agg_m2_cost_per_outcome.parquet'").fetchall()[0]
    src_cost = duckdb.sql(f"select sum(cost_to_serve_usd) from '{gold}/fct_m2_tenant_margin.parquet'").fetchall()[0][0]
    src_out = duckdb.sql(f"select sum(resolved_remotely) from '{gold}/fct_quality.parquet'").fetchall()[0][0]
    assert (cost, outcomes) == (src_cost, src_out)  # full outer join: nothing lost or doubled
    assert duckdb.sql(f"select count(*) - count(distinct (metric_date, tenant_id)) from '{gold}/agg_m2_cost_per_outcome.parquet'").fetchall()[0][0] == 0
    m = metrics.load()["cost_per_outcome_usd"]
    got = duckdb.sql(f"select {metrics.to_sql(m)} from '{gold}/agg_m2_cost_per_outcome.parquet'").fetchall()[0][0]
    assert abs(Decimal(str(got)) - Decimal(str(cost)) / Decimal(str(outcomes))) < Decimal("1e-9")


def _dbt(root: Path, args: list[str], variables: dict):
    from dbt.cli.main import dbtRunner

    return dbtRunner().invoke([
        *args, "--project-dir", str(TRANSFORM_DIR), "--profiles-dir", str(TRANSFORM_DIR),
        "--target-path", str(root / "t"), "--log-path", str(root / "l"), "--vars", json.dumps(variables), "--quiet"])


def test_m2_gates_pass_and_break_on_purpose(allocated):
    out, landing = allocated
    root = out.parent.parent
    os.environ["MC_DUCKDB_PATH"] = str(root / "a.duckdb")  # the views built by the fixture
    variables = {"m2_landing_path": str(landing), "silver_path": str(root / "silver"), "bronze_path": "x",
                 "gold_path": str(root / "gold"), "m2_gates": True,
                 "allocation_rules": __import__("mc_pipelines.allocation", fromlist=["load_rules"]).load_rules()}
    ok = _dbt(root, ["test", "--select", *M2_GATES], variables)
    assert ok.success, ok.exception
    assert len(ok.result.results) == len(M2_GATES)
    # Break each gate on purpose: drop rows from the facts they guard, and the gates must fail.
    gold = root / "gold"
    for f in ("fct_infra_cost_allocated", "fct_cost_to_serve", "fct_unit_cost", "fct_m2_tenant_margin"):
        path = gold / f"{f}.parquet"
        keep = path.with_suffix(".keep")
        path.rename(keep)
        duckdb.sql(f"copy (select * from read_parquet('{keep}') using sample 90 percent (bernoulli, 3)) to '{path}' (format parquet)")
    silver = root / "silver" / "slv_m2_revenue_daily.parquet"
    keep = silver.with_suffix(".keep")
    silver.rename(keep)
    duckdb.sql(f"copy (select * from read_parquet('{keep}') using sample 90 percent (bernoulli, 3)) to '{silver}' (format parquet)")
    bad = _dbt(root, ["test", "--select", *M2_GATES], variables)
    failed = [r.node.name for r in bad.result.results if r.status != "pass"]
    assert set(failed) == set(M2_GATES), failed


def test_run_m2_dbt_builds_all_marts_with_gates_and_writes_the_scorecard(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt

    tenants, history = generate_m2_tenants(42)
    landing = tmp_path / "landing"
    write_month(landing, 42, tenants, 5)
    _write(landing, "tenants/tenants.parquet", tenants, 42, "tenants")
    write_focus(landing, 42, tenants)
    write_revenue(landing, 42, tenants, history)
    write_dimensions(landing, 42, history)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    summary = run_m2_dbt(landing, tmp_path / "data", "run-m2")
    assert summary["success"], summary
    gold = tmp_path / "data" / "gold"
    for mart in ("fct_infra_cost_allocated", "fct_cost_to_serve", "fct_unit_cost", "fct_quality", "fct_m2_tenant_margin",
                 "agg_m2_cost_per_outcome", "dim_tenant", "dim_feature", "dim_model_price"):
        assert (gold / f"{mart}.parquet").exists(), mart
    assert (gold / "_quality" / "m2_scorecard.json").exists()
    assert summary["statuses"].get("pass", 0) >= len(M2_GATES)  # the four gates ran


def test_cli_run_m2_builds_the_marts_and_returns_zero(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import main

    tenants, history = generate_m2_tenants(42)
    landing = tmp_path / "landing"
    write_month(landing, 42, tenants, 5)
    _write(landing, "tenants/tenants.parquet", tenants, 42, "tenants")
    write_focus(landing, 42, tenants)
    write_revenue(landing, 42, tenants, history)
    write_dimensions(landing, 42, history)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    assert main(["run-m2", "--landing", str(landing), "--data-root", str(tmp_path / "data")]) == 0
    assert (tmp_path / "data" / "gold" / "fct_m2_tenant_margin.parquet").exists()


def test_publish_m2_kpis_come_from_the_registry_and_match_the_marts(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt
    from mc_pipelines.publish import m2_kpis

    tenants, history = generate_m2_tenants(42)
    landing = tmp_path / "landing"
    write_month(landing, 42, tenants, 5)
    _write(landing, "tenants/tenants.parquet", tenants, 42, "tenants")
    write_focus(landing, 42, tenants)
    write_revenue(landing, 42, tenants, history)
    write_dimensions(landing, 42, history)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    assert run_m2_dbt(landing, tmp_path / "data", "run-m2")["success"]
    gold = tmp_path / "data" / "gold"
    kpis = m2_kpis(gold)
    rev, cost = duckdb.sql(
        f"select sum(revenue_usd), sum(cost_to_serve_usd) from read_parquet('{gold}/fct_m2_tenant_margin.parquet')").fetchall()[0]
    assert kpis["gross_margin_usd"] == pytest.approx(float(rev - cost), abs=1e-6)
    assert kpis["gross_margin_pct"] == pytest.approx(float((rev - cost) / rev), abs=1e-6)
    assert set(kpis) >= {"unit_cost_per_request_usd", "cost_per_outcome_usd", "safety_event_recall", "attribution_coverage"}


def test_pg1_snapshot_carries_m2_kpis_only_when_the_m2_marts_exist(tmp_path):
    from mc_pipelines.publish import _m2_marts_present

    assert not _m2_marts_present(tmp_path)  # M1-only gold: the snapshot stays as before
