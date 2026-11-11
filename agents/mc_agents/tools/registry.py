"""Versioned tool contracts for the calculators (M4-02, PLAN.md §8.6).

Each tool is pure, read-only and idempotent. `call` validates the name, runs the tool, records the
call in the evidence ledger and returns the evidence, so every number the agents show comes from a tool
and carries an evidence reference. Errors surface as `ToolError` (returned to the model as a tool error).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mc_agents.ledger import Evidence, Ledger
from mc_agents.tools.churn_adjust import churn_adjust
from mc_agents.tools.levers import replay_lever
from mc_agents.tools.metrics import ToolError
from mc_agents.tools.pricing import price_plan
from mc_agents.tools.roi import roi_multiple


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    fn: Callable[[dict[str, Any]], dict[str, Any]]
    read_only: bool = True
    input_schema: dict[str, Any] | None = None  # JSON schema offered to the model (None: a bare object)


def _int_schema(fields: dict[str, str], required: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": "integer", "minimum": 0, "description": d}
                                             for k, d in fields.items()}, "required": list(required)}


# 3c-3c: explicit input schemas, so the model can call the pricing tools instead of asking for a plan.
_PRICE_PLAN_FIELDS = {
    "seats": "Number of seats.", "seat_price_cents": "Price per seat per month, in cents.",
    "addon_cents": "Flat AI add-on per month, in cents (0 if none).",
    "included_units": "Usage units included in the plan.", "usage_units": "Usage units consumed in the month.",
    "overage_rate_micro": "Overage price per unit above the included units, in micro-dollars.",
    "outcome_price_micro": "Price per billed outcome, in micro-dollars (0 if none).",
    "outcomes": "Billed outcomes in the month (0 if none).",
    "discount_bps": "Discount in basis points (500 = 5%), at most 10000.",
    "cost_cents": "AI cost of goods for the month, in cents.",
    "usage_cap_cents": "Optional cap on overage plus outcome charges, in cents.",
}
_CHURN_FIELDS = {
    "revenue_cents": "Monthly revenue, in cents (for example price_plan's revenue_cents).",
    "cost_cents": "Monthly cost, in cents.", "churn_bps": "Monthly churn probability in basis points, at most 10000.",
    "months": "Horizon in months, 1 to 60.",
}

TOOLS: dict[str, ToolSpec] = {t.name: t for t in (
    ToolSpec("price_plan", "1", "Revenue and margin of one tenant-month under a plan (integer cents).", price_plan,
             input_schema=_int_schema(_PRICE_PLAN_FIELDS, tuple(f for f in _PRICE_PLAN_FIELDS if f != "usage_cap_cents"))),
    ToolSpec("replay_lever", "1", "Routing and caching lever replay with quality and safety-recall guardrails.", replay_lever),
    ToolSpec("churn_adjust", "1", "Churn-adjusted expected revenue, cost and margin over N months.", churn_adjust,
             input_schema=_int_schema(_CHURN_FIELDS, tuple(_CHURN_FIELDS))),
    ToolSpec("roi_multiple", "1", "KPI-13 platform ROI multiple (bps) and payback months, integer arithmetic.", roi_multiple),
)}


def search_knowledge_spec(**deps: Any) -> ToolSpec:
    from mc_agents.tools.retrieval import make_search_knowledge
    return ToolSpec("search_knowledge", "1", "Tenant-filtered hybrid retrieval over contracts, policies, playbooks and schema cards.",
                    make_search_knowledge(**deps))


def query_gold_spec(gold_dir: Any) -> ToolSpec:
    from mc_agents.tools.sql_guard import make_query_gold, mart_schema
    marts = "; ".join(f"{m}({', '.join(f'{c} {t}' for c, t in cols)})" for m, cols in mart_schema(gold_dir).items())
    return ToolSpec("query_gold", "3", "Guarded read-only DuckDB SELECT over the gold marts (allow-listed tables, "
                    "200-row cap). Pass one SELECT in `sql`. Columns ending in `_pct` are fractions from 0 to 1 "
                    "(20% is 0.2). Return dates and months as DATE, not TIMESTAMP (for example "
                    f"CAST(date_trunc('month', d) AS DATE)). Tables and columns: {marts}.",
                    make_query_gold(gold_dir),
                    input_schema={"type": "object", "properties": {"sql": {
                        "type": "string", "description": "One DuckDB SELECT over the listed tables only."}},
                        "required": ["sql"]})


def catalog() -> list[dict[str, Any]]:
    return [{"name": t.name, "version": t.version, "description": t.description, "read_only": t.read_only}
            for t in TOOLS.values()]


def call(name: str, args: dict[str, Any], ledger: Ledger, extra: dict[str, ToolSpec] | None = None) -> Evidence:
    """`extra` holds tools that need runtime dependencies (for example `search_knowledge`, which needs a store)."""
    spec = TOOLS.get(name) or (extra or {}).get(name)
    if spec is None:
        raise ToolError(f"unknown tool {name!r}; available: {sorted({*TOOLS, *(extra or {})})}")
    if not isinstance(args, dict):
        raise ToolError("tool arguments must be an object")
    try:
        result = spec.fn(dict(args))
    except (ValueError, KeyError, TypeError) as e:
        raise ToolError(f"{name}: invalid input ({e})") from None
    return ledger.add(f"{name}@{spec.version}", args, result)
