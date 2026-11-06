import duckdb
import pytest

from mc_agents.tools.m2 import M2KpiTools
from mc_agents.tools.metrics import ToolError, money


@pytest.fixture(scope="module")
def m2_gold(tmp_path_factory):
    from booncore_sim.m2_catalog import PRICE_CATALOG_V2
    from booncore_sim.m2_tenants import generate_m2_tenants
    from booncore_sim.m2_writer import _write, write_dimensions, write_focus, write_month, write_revenue
    from mc_pipelines.cli import run_m2_dbt

    root = tmp_path_factory.mktemp("m2")
    tenants, history = generate_m2_tenants(42)
    landing = root / "landing"
    write_month(landing, 42, tenants, 5)
    _write(landing, "tenants/tenants.parquet", tenants, 42, "tenants")
    write_focus(landing, 42, tenants)
    write_revenue(landing, 42, tenants, history)
    write_dimensions(landing, 42, history)
    _write(landing, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), 42, "price catalog")
    assert run_m2_dbt(landing, root / "data", "run-m2")["success"]
    return root / "data" / "gold"


def test_kpi_margin_matches_the_mart(m2_gold):
    rev, cost = duckdb.sql(
        f"select sum(revenue_usd), sum(cost_to_serve_usd) from read_parquet('{m2_gold}/fct_m2_tenant_margin.parquet')"
    ).fetchall()[0]
    out = M2KpiTools(m2_gold).kpi("gross_margin_usd")
    assert out["display"] == money(rev - cost)
    assert M2KpiTools(m2_gold).kpi("gross_margin_pct")["display"].endswith("%")


def test_unknown_metric_is_a_tool_error(m2_gold):
    with pytest.raises(ToolError):
        M2KpiTools(m2_gold).kpi("revenue_vibes")
