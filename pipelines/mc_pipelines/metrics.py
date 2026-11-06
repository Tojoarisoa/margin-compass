"""The metric registry (`metrics/metrics.yml`) compiled to SQL and to Python (m2-plan.md D4, M2-03.1).

Metrics are sums and ratios of sums, so a roll-up never averages row-level ratios. `to_sql` gives the select
expression for dbt marts; `compute` gives the same number from a list of row dicts for the publish step, agent
tools and evaluations. A parity test runs both on the same rows.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "metrics" / "metrics.yml"


def load(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    """Metrics by name. Rejects duplicate names, unknown kinds, and ratios without both sides."""
    out: dict[str, dict] = {}
    for m in yaml.safe_load(path.read_text())["metrics"]:
        if m["name"] in out:
            raise ValueError(f"duplicate metric {m['name']}")
        if m["kind"] == "sum" and "terms" not in m:
            raise ValueError(f"{m['name']}: sum needs terms")
        if m["kind"] == "ratio" and not (m.get("numerator") and m.get("denominator")):
            raise ValueError(f"{m['name']}: ratio needs numerator and denominator")
        if m["kind"] not in ("sum", "ratio"):
            raise ValueError(f"{m['name']}: unknown kind {m['kind']!r}")
        out[m["name"]] = m
    return out


def _cond_sql(where: dict) -> str:
    parts = []
    for col, cond in where.items():
        (op, value), = cond.items()
        sql_op = {"eq": "=", "ne": "<>"}[op]
        parts.append(f"{col} {sql_op} '{str(value).replace(chr(39), chr(39) * 2)}'")
    return " and ".join(parts)


def _term_sql(t: dict) -> str:
    s = f"sum({t['col']})"
    if t.get("where"):
        s += f" filter (where {_cond_sql(t['where'])})"
    return s


def _side_sql(terms: list[dict]) -> str:
    out = ""
    for i, t in enumerate(terms):
        neg = t.get("sign", 1) < 0
        out += (" - " if neg else " + " if i else "") if i else ("-" if neg else "")
        out += _term_sql(t)
    return out


def to_sql(metric: dict) -> str:
    """Select expression over the metric's source table."""
    if metric["kind"] == "sum":
        return _side_sql(metric["terms"])
    return f"({_side_sql(metric['numerator'])}) / nullif({_side_sql(metric['denominator'])}, 0)"


def _matches(row: dict, where: dict | None) -> bool:
    for col, cond in (where or {}).items():
        (op, value), = cond.items()
        if (row[col] == value) != (op == "eq"):
            return False
    return True


def _side(terms: list[dict], rows: list[dict]) -> Decimal:
    total = Decimal(0)
    for t in terms:
        total += t.get("sign", 1) * sum((Decimal(str(r[t["col"]])) for r in rows if _matches(r, t.get("where"))), Decimal(0))
    return total


def compute(metric: dict, rows: list[dict]) -> Decimal | None:
    """The metric over `rows`; None when a ratio's denominator is 0 (SQL NULL)."""
    if metric["kind"] == "sum":
        return _side(metric["terms"], rows)
    den = _side(metric["denominator"], rows)
    return None if den == 0 else _side(metric["numerator"], rows) / den
