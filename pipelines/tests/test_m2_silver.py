"""M2-02 step 1: the M2 silver pricing model, against the simulator's own Python pricing (one month, seed 42)."""

from __future__ import annotations

import json
import os
from datetime import date
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
