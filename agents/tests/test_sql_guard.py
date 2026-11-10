"""EV-05 guard tests: only allow-listed single SELECTs run; execution results are exact."""

import pytest

from mc_agents.ledger import Ledger
from mc_agents.tools import registry
from mc_agents.tools.metrics import ToolError
from mc_agents.tools.sql_guard import check_sql, make_query_gold


@pytest.fixture(scope="module")
def q(gold):
    return make_query_gold(gold)


@pytest.mark.parametrize("sql", [
    "DROP TABLE fct_tenant_margin", "DELETE FROM fct_tenant_margin", "INSERT INTO dim_tenant VALUES (1)",
    "COPY fct_tenant_margin TO 'x.csv'", "ATTACH 'x.db'", "SET enable_external_access = true",
    "SELECT 1; SELECT 2", "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM read_parquet('x.parquet')",
    "SELECT * FROM glob('/*')", "SELECT * FROM information_schema.tables", "SELECT * FROM secrets",
    "SELECT * FROM fct_tenant_margin JOIN other ON true", "SELECT * FROM (SELECT * FROM evil) s",
    "SELECT * FROM fct_tenant_margin WHERE tenant_id IN (SELECT x FROM evil)",
    "PRAGMA database_list", "CREATE VIEW v AS SELECT 1", "", "   ", "SELEC nonsense",
])
def test_rejects(sql):
    with pytest.raises(ToolError):
        check_sql(sql)


def test_cte_allowed():
    assert check_sql("WITH a AS (SELECT tenant_id FROM fct_tenant_margin) SELECT * FROM a;").startswith("WITH")


def test_runs_and_matches_direct_execution(q, gold):
    import duckdb
    got = q({"sql": "SELECT count(*) AS n, count(DISTINCT tenant_id) AS t FROM fct_tenant_margin"})
    want = duckdb.connect().execute(f"SELECT count(*), count(DISTINCT tenant_id) FROM read_parquet('{gold / 'fct_tenant_margin.parquet'}')").fetchone()
    assert got["rows"] == [list(want)] and got["columns"] == ["n", "t"] and not got["truncated"]


def test_row_cap(gold):
    got = make_query_gold(gold, max_rows=3)({"sql": "SELECT * FROM fct_tenant_margin"})
    assert got["row_count"] == 3 and got["truncated"]


def test_runtime_errors_are_tool_errors(q):
    with pytest.raises(ToolError):
        q({"sql": "SELECT no_such_column FROM fct_tenant_margin"})


def test_registry_records_evidence(gold):
    ledger = Ledger()
    ev = registry.call("query_gold", {"sql": "SELECT 1 AS one"}, ledger, extra={"query_gold": registry.query_gold_spec(gold)})
    assert ev.tool == "query_gold@3" and len(ledger.entries) == 1
    with pytest.raises(ToolError):
        registry.call("query_gold", {"sql": "DROP TABLE dim_tenant"}, ledger, extra={"query_gold": registry.query_gold_spec(gold)})
    assert len(ledger.entries) == 1


def test_cannot_read_outside_gold(q, tmp_path):
    # table functions are rejected by the parser guard; the session also blocks file access as a second layer
    with pytest.raises(ToolError):
        q({"sql": "SELECT * FROM read_csv('/etc/passwd')"})


def test_query_gold_spec_tells_the_model_sql_and_tables(gold):
    # EV-05 record run 42876410156: with a bare object schema the model sent `query` and invented tables
    from mc_agents.specialists import SPECIALISTS, tool_specs

    spec = tool_specs(SPECIALISTS["cost_to_serve"], {"query_gold": registry.query_gold_spec(gold)})[0]["toolSpec"]
    schema = spec["inputSchema"]["json"]
    assert schema["required"] == ["sql"] and schema["properties"]["sql"]["type"] == "string"
    assert "fct_tenant_margin(" in spec["description"] and "tenant_feature_days" not in spec["description"]


def test_query_gold_spec_states_types_and_units(gold):
    # EV-05 record run 42879147169: the model compared a fraction to 20 and returned months as TIMESTAMP
    desc = registry.query_gold_spec(gold).description
    assert "margin_date DATE" in desc and "gross_margin_pct DOUBLE" in desc
    assert "fractions from 0 to 1" in desc and "AS DATE" in desc
