"""Guarded SQL tool over the gold marts (M4-02, PLAN.md §8.6, EV-05).

The model may write SQL, but only this module runs it. Checks, in order: one statement; it parses as a
SELECT (DuckDB's own parser, so no regex tricks); every table is an allow-listed gold mart (CTE names
excepted); no table functions (`read_csv`, `glob`, ...); the session has external access disabled and
reads only the mart views; result rows are capped. Nothing is ever written. Numbers come back as the
database computed them, never from the model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from mc_agents.tools.metrics import ToolError

MAX_ROWS = 200
MAX_SQL_CHARS = 4000
MARTS = ("fct_tenant_margin", "fct_cost_to_serve", "fct_unit_cost", "fct_quality", "fct_infra_cost_allocated",
         "dim_tenant", "dim_feature", "dim_model_price")


def _walk(node: Any, tables: set[str], ctes: set[str]) -> None:
    if isinstance(node, dict):
        t = node.get("type")
        if t == "BASE_TABLE":
            tables.add(str(node.get("table_name", "")).lower())
        elif t == "TABLE_FUNCTION":
            raise ToolError(f"table function {node.get('function', {}).get('function_name')!r} is not allowed")
        for key in ("map",):  # CTE definitions: {"map": [{"key": name, ...}]}
            for entry in node.get(key) or []:
                if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                    ctes.add(entry["key"].lower())
        for v in node.values():
            _walk(v, tables, ctes)
    elif isinstance(node, list):
        for v in node:
            _walk(v, tables, ctes)


def check_sql(sql: str, allowed: set[str] | frozenset[str] = frozenset(MARTS)) -> str:
    """Return the cleaned SQL or raise ToolError."""
    if not isinstance(sql, str) or not sql.strip():
        raise ToolError("sql must be a non-empty string")
    if len(sql) > MAX_SQL_CHARS:
        raise ToolError(f"sql is longer than {MAX_SQL_CHARS} characters")
    sql = sql.strip().rstrip(";").strip()
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise ToolError(f"sql does not parse: {e}") from None
    if len(statements) != 1:
        raise ToolError("exactly one statement is allowed")
    tree = json.loads(duckdb.connect().execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    if tree.get("error"):
        raise ToolError("only SELECT statements are allowed")
    tables: set[str] = set()
    ctes: set[str] = set()
    _walk(tree, tables, ctes)
    bad = sorted(t for t in tables - ctes if t not in allowed)
    if bad:
        raise ToolError(f"table(s) not allowed: {bad}; allowed: {sorted(allowed)}")
    return sql


def mart_columns(gold_dir: Path) -> dict[str, list[str]]:
    """Column names of each allow-listed mart present in `gold_dir` (read from the parquet schema), so
    the model is told the real tables instead of guessing them (EV-05)."""
    gold = Path(gold_dir)
    out = {}
    for m in MARTS:
        path = gold / f"{m}.parquet"
        if path.exists():
            out[m] = [r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]
    return out


def make_query_gold(gold_dir: Path, *, max_rows: int = MAX_ROWS) -> Callable[[dict[str, Any]], dict[str, Any]]:
    gold = Path(gold_dir)
    present = {m for m in MARTS if (gold / f"{m}.parquet").exists()}
    if not present:
        raise FileNotFoundError(f"no gold marts in {gold}")

    def query_gold(args: dict[str, Any]) -> dict[str, Any]:
        sql = check_sql(args["sql"], present)
        con = duckdb.connect()
        con.execute("SET threads = 1")
        for m in sorted(present):
            con.execute(f"CREATE VIEW {m} AS SELECT * FROM read_parquet('{gold / (m + '.parquet')}')")
        con.execute(f"SET allowed_directories = ['{gold.resolve()}']")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        try:
            cur = con.execute(f"SELECT * FROM ({sql}) LIMIT {max_rows + 1}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except duckdb.Error as e:
            raise ToolError(f"query failed: {e}") from None
        truncated = len(rows) > max_rows
        return {"sql": sql, "columns": cols, "rows": [[_cell(v) for v in r] for r in rows[:max_rows]],
                "row_count": min(len(rows), max_rows), "truncated": truncated}
    return query_gold


def _cell(v: Any) -> Any:
    return v if v is None or isinstance(v, (int, float, str, bool)) else str(v)
