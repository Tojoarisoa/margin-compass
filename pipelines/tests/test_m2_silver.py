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
    assert "error" not in summary["leaks"] and (gold / "fct_margin_leaks.parquet").exists()
    assert summary["statuses"].get("pass", 0) >= len(M2_GATES)  # the four gates ran
    import json

    lineage = json.loads((tmp_path / "data" / "gold" / "_quality" / "m2_lineage.json").read_text())
    assert "fct_m2_tenant_margin" in lineage["models"] and lineage["metrics_by_mart"]["fct_m2_tenant_margin"]
    latest = {p for p in summary["published"] if not p.startswith("publish/history/")}
    assert latest == {"publish/latest/m2_scorecard.json", "publish/latest/m2_lineage.json", "publish/latest/pg3.json",
                      "publish/latest/finops.json", "publish/latest/pg1.json", "publish/latest/explore.parquet",
                      "publish/latest/pg2.json"}
    assert [p for p in summary["published"] if p.startswith("publish/history/")] == [
        p for p in summary["published"] if p.endswith("/pg1.json") and "/history/" in p]
    assert (tmp_path / "data" / "publish" / "latest" / "m2_lineage.json").exists()


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


def test_publish_m2_feature_costs_sum_to_the_mart_total(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt
    from mc_pipelines.publish import m2_feature_costs

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
    feats = m2_feature_costs(gold)
    total = duckdb.sql(f"select sum(cost_to_serve_usd) from read_parquet('{gold}/fct_cost_to_serve.parquet')").fetchall()[0][0]
    assert sum(f["cost_to_serve_usd"] for f in feats) == pytest.approx(float(total), abs=0.05)
    assert sum(f["cost_share"] for f in feats) == pytest.approx(1.0, abs=0.001)
    assert all(f["feature_name"] for f in feats)


def test_publish_m2_at_risk_counts_negative_margin_tenants(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt
    from mc_pipelines.publish import m2_at_risk

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
    risk = m2_at_risk(gold)
    n = duckdb.sql(f"select count(*) from (select tenant_id from read_parquet('{gold}/fct_m2_tenant_margin.parquet') "
                   "group by tenant_id having sum(margin_usd) < 0)").fetchall()[0][0]
    assert risk["unprofitable_tenants"] == n
    assert risk["arr_at_risk_usd"] >= 0
    assert all(w["margin_usd"] < 0 for w in risk["worst"])
    assert [w["margin_usd"] for w in risk["worst"]] == sorted(w["margin_usd"] for w in risk["worst"])


def test_explore_parquet_sums_equal_the_mart_and_stay_small(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt
    from mc_pipelines.publish import EXPLORE_MAX_BYTES, write_explore_parquet

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
    out = tmp_path / "publish" / "latest" / "explore.parquet"
    size = write_explore_parquet(gold, out)
    assert 0 < size <= EXPLORE_MAX_BYTES
    a = duckdb.sql(f"select sum(cost_to_serve_usd), sum(requests), count(*) from read_parquet('{out}')").fetchall()[0]
    b = duckdb.sql(f"select sum(cost_to_serve_usd), sum(requests) from read_parquet('{gold}/fct_cost_to_serve.parquet')").fetchall()[0]
    assert (a[0], a[1]) == (b[0], b[1]) and a[2] > 0


def test_pg2_views_each_total_to_the_cost_to_serve_mart(tmp_path):
    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt
    from mc_pipelines.publish import PG2_MAX_BYTES, build_pg2

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
    pg2 = build_pg2(gold, "r1")
    total = duckdb.sql(f"select sum(cost_to_serve_usd), sum(requests) from read_parquet('{gold}/fct_cost_to_serve.parquet')").fetchall()[0]
    for view in ("by_tenant", "by_feature", "by_month", "by_tenant_feature"):
        assert pg2[view], view
        assert sum(r["cost_to_serve_usd"] for r in pg2[view]) == pytest.approx(float(total[0]), abs=0.01 * len(pg2[view])), view  # rows are rounded to cents
        assert sum(r["requests"] for r in pg2[view]) == total[1], view
    assert all(r["feature_name"] for r in pg2["by_feature"])
    mart = duckdb.sql(f"select sum(margin_usd), count(distinct tenant_id) from read_parquet('{gold}/fct_m2_tenant_margin.parquet')").fetchall()[0]
    wf = pg2["margin_waterfall"]
    assert len(wf) == mart[1] and sum(r["margin_usd"] for r in wf) == pytest.approx(float(mart[0]), abs=0.01 * len(wf))
    assert [r["margin_usd"] for r in wf] == sorted(r["margin_usd"] for r in wf)
    used = {r["tenant_id"]: r["requests"] for r in pg2["by_tenant"]}
    assert all(r["requests"] == used.get(r["tenant_id"], 0) for r in wf)  # tenants with no usage rows plot at 0
    assert pg2["attribution_by_month"] and all(0 <= r["coverage"] <= 1 for r in pg2["attribution_by_month"])
    assert len(json.dumps(pg2)) <= PG2_MAX_BYTES


def test_margin_forecast_band_is_ordered_and_matches_hand_values():
    from datetime import date

    from mc_pipelines.publish import margin_forecast

    recent = [(100, 40), (100, 40)]  # mean daily revenue 100
    fc = [(date(2026, 1, 1), date(2026, 1, 2), 30, 40, 55, "v1", "champion")]
    out = margin_forecast(recent, fc)
    assert out["daily_revenue_usd"] == 100.0
    p = out["points"][0]
    assert (p["low"], p["mid"], p["high"]) == (0.45, 0.6, 0.7)  # P90 cost gives the low margin
    assert p["low"] <= p["mid"] <= p["high"]
    assert margin_forecast([], fc)["points"] == []


def test_pg1_snapshot_carries_m2_kpis_only_when_the_m2_marts_exist(tmp_path):
    from mc_pipelines.publish import _m2_marts_present

    assert not _m2_marts_present(tmp_path)  # M1-only gold: the snapshot stays as before


def test_finops_awaits_the_first_export_then_sums_by_stage(tmp_path):
    import duckdb

    from mc_pipelines.publish import build_finops

    pattern = str(tmp_path / "focus" / "*.parquet")
    empty = build_finops(pattern, "r1")
    assert empty["status"] == "awaiting_first_export" and empty["by_stage"] == []
    (tmp_path / "focus").mkdir()
    duckdb.sql("""COPY (SELECT * FROM (VALUES
        (TIMESTAMP '2026-11-01', 'AWS Lambda', 0.10, '{"stage":"dev"}'),
        (TIMESTAMP '2026-11-02', 'Amazon S3', 0.05, '{"stage":"dev"}'),
        (TIMESTAMP '2026-11-02', 'Amazon S3', 0.30, NULL))
        t(ChargePeriodStart, ServiceName, BilledCost, Tags)) TO '{tmp_path}/focus/a.parquet' (FORMAT PARQUET)""".replace("{tmp_path}", str(tmp_path)))
    out = build_finops(pattern, "r1")
    assert out["status"] == "ok"
    assert {r["key"]: r["cost_usd"] for r in out["by_stage"]} == {"untagged": 0.3, "dev": 0.15}
    assert out["latest_month_usd"] == 0.45
    assert not {"budget_usd", "budget_used"} & set(out) and not {"budget_usd", "budget_used"} & set(empty)  # public: no budget
    assert "account" not in str(out).lower()


def test_fct_realized_margin_counts_only_verified_rows(tmp_path):
    from dbt.cli.main import dbtRunner

    from booncore_sim.m2_writer import _write

    landing = tmp_path / "landing"
    from booncore_sim.m5_realized import RealizedRow

    rows = [RealizedRow("a", date(2026, 3, 1), 10.0, 8.0, 2.0, 0.0, "pending_verification"),
            RealizedRow("a", date(2026, 3, 20), 10.0, 7.0, 3.0, 0.0, "realized"),
            RealizedRow("b", date(2026, 3, 21), 10.0, 0.0, 10.0, -4.0, "realized")]
    _write(landing, "s5_realized/realized_cost.parquet", rows, 42, "realized cost")
    os.environ["MC_DUCKDB_PATH"] = str(tmp_path / "o.duckdb")
    variables = {"m2_landing_path": str(landing), "m2_realized": True, "silver_path": "x", "bronze_path": "x",
                 "gold_path": str(tmp_path)}
    result = dbtRunner().invoke([
        "build", "--select", "+fct_realized_margin", "--project-dir", str(TRANSFORM_DIR),
        "--profiles-dir", str(TRANSFORM_DIR), "--target-path", str(tmp_path / "t"), "--log-path", str(tmp_path / "l"),
        "--vars", json.dumps(variables), "--quiet"])
    assert result.success, result.exception
    out = tmp_path / "fct_realized_margin.parquet"
    assert duckdb.sql(f"select sum(realized_margin_usd), count(*) from '{out}'").fetchall()[0] == (9.0, 3)


def test_publish_realized_totals(tmp_path):
    from mc_pipelines.publish import publish_realized

    gold = tmp_path / "gold"
    gold.mkdir()
    duckdb.sql(
        "copy (select * from (values ('a', 'realized', 3.0, 0.0, 3.0), ('b', 'realized', 10.0, -4.0, 6.0), "
        "('b', 'pending_verification', 2.0, 0.0, 0.0)) t(action_id, status, saved_usd, revenue_delta_usd, realized_margin_usd)) "
        f"to '{gold / 'fct_realized_margin.parquet'}' (format parquet)")
    assert publish_realized(tmp_path, "r1") == ["publish/latest/realized.json"]
    body = json.loads((tmp_path / "publish" / "latest" / "realized.json").read_text())
    assert (body["realized_margin_usd"], body["saved_usd"], body["revenue_delta_usd"]) == ("9.00", "13.00", "-4.00")
    assert (body["actions_realized"], body["actions_pending"], body["realization_rate"]) == (2, 1, "0.666667")
    assert publish_realized(tmp_path / "none", "r1") == []


def test_m2_build_publishes_pg1_with_m2_sections(tmp_path):
    """The M2 build writes pg1.json from the M2 marts (the M1 publish cannot run there), so the dashboard shows M2."""
    import json

    from booncore_sim.m2_writer import write_dimensions, write_focus, write_revenue
    from mc_pipelines.cli import run_m2_dbt
    from mc_pipelines.publish import MAX_BYTES

    tenants, history = generate_m2_tenants(42)
    landing = tmp_path / "landing"
    write_month(landing, 42, tenants, 5)
    _write(landing, "tenants/tenants.parquet", tenants, 42, "tenants")
    write_focus(landing, 42, tenants)
    write_revenue(landing, 42, tenants, history)
    write_dimensions(landing, 42, history)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    summary = run_m2_dbt(landing, tmp_path / "data", "run-m2")
    assert summary["success"] and "pg1_error" not in summary
    assert {"publish/latest/pg1.json", "publish/latest/pg2.json", "publish/latest/explore.parquet"} <= set(summary["published"])
    root = tmp_path / "data"
    body = (root / "publish" / "latest" / "pg1.json").read_bytes()
    assert len(body) <= MAX_BYTES
    snap = json.loads(body)
    assert snap["schema_version"] == "pg1.v0" and snap["data_label"] == "synthetic"
    assert {"m2_kpis", "m2_at_risk", "m2_margin_forecast", "m2_features"} <= set(snap)
    # headline AI revenue is the ai_addon invoice lines over the cost window; cost is fct_cost_to_serve
    gold, silver = root / "gold", root / "silver"
    lo, hi, cost = duckdb.sql(f"select min(cost_date), max(cost_date), sum(cost_to_serve_usd) "
                              f"from read_parquet('{gold}/fct_cost_to_serve.parquet')").fetchall()[0]
    ai = duckdb.sql(f"select sum(amount_usd) from read_parquet('{silver}/slv_m2_revenue_daily.parquet') "
                    f"where revenue_component = 'ai_addon' and revenue_date between DATE '{lo}' and DATE '{hi}'").fetchall()[0][0]
    w = snap["headline"]["window"]
    assert w["ai_revenue_usd"] == pytest.approx(float(ai), abs=0.01)
    assert w["ai_cost_to_serve_usd"] == pytest.approx(float(cost), abs=0.01)
    assert snap["window"] == {"from": lo.isoformat(), "to": hi.isoformat(), "days": len(snap["trend"])}
    assert snap["headline"]["tenants"] == len(snap["tenants"]) > 0
    # one forecast point per day (features summed), compared with fully loaded cost
    dates = [p["date"] for p in snap["forecast"]["points"]]
    assert len(dates) == len(set(dates)) and dates == sorted(dates)
    if dates:
        assert "non-LLM" in snap["forecast"]["assumption"]
        assert all(p["p10"] <= p["p50"] <= p["p90"] for p in snap["forecast"]["points"])
    # internal codes stay off public surfaces (AGENTS.md §6)
    assert "M1" not in snap["feature_scope"] and "F1" not in snap["feature_scope"]


def test_finops_reads_the_nested_aws_export_with_map_tags(tmp_path):
    """The AWS export nests files under <export>/data/billing_period=YYYY-MM/ and writes Tags as a MAP."""
    import duckdb

    from mc_pipelines.publish import build_finops

    part = tmp_path / "focus-1-2" / "mc-export" / "data" / "billing_period=2026-11"
    part.mkdir(parents=True)
    duckdb.sql(f"""COPY (SELECT * FROM (VALUES
        (TIMESTAMP '2026-11-01', 'AWS Lambda', 0.10, MAP {{'stage': 'dev'}}),
        (TIMESTAMP '2026-11-02', 'Amazon S3', 0.05, MAP {{'user:stage': 'dev'}}),
        (TIMESTAMP '2026-11-02', 'Amazon S3', 0.30, MAP {{'other': 'x'}}))
        t(ChargePeriodStart, ServiceName, BilledCost, Tags)) TO '{part}/a.snappy.parquet' (FORMAT PARQUET)""")
    out = build_finops(f"{tmp_path}/focus-1-2/**/*.parquet", "r1")
    assert out["status"] == "ok"
    assert {r["key"]: r["cost_usd"] for r in out["by_stage"]} == {"untagged": 0.3, "dev": 0.15}


def test_finops_unreadable_export_does_not_fail_the_build(tmp_path):
    from mc_pipelines.publish import build_finops

    (tmp_path / "f").mkdir()
    (tmp_path / "f" / "bad.parquet").write_bytes(b"not parquet")
    out = build_finops(f"{tmp_path}/f/**/*.parquet", "r1")
    assert out["status"] == "export_unreadable" and out["by_stage"] == [] and out["schema_version"] == "finops.v0"
