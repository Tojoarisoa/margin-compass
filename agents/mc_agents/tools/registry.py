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


TOOLS: dict[str, ToolSpec] = {t.name: t for t in (
    ToolSpec("price_plan", "1", "Revenue and margin of one tenant-month under a plan (integer cents).", price_plan),
    ToolSpec("replay_lever", "1", "Routing and caching lever replay with quality and safety-recall guardrails.", replay_lever),
    ToolSpec("churn_adjust", "1", "Churn-adjusted expected revenue, cost and margin over N months.", churn_adjust),
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
