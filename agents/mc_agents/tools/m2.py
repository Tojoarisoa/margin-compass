"""Read-only M2 KPI tool over the gold marts, every figure from the metric registry (M2-03.1).

`analyst_tools` adds the `kpi` tool only when the gold directory holds every M2 mart, so M1-only gold (and the
replay fixtures recorded on it) keeps the exact M1 tool set. Same rules as `MetricTools`: no LLM arithmetic,
display strings only.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import duckdb

from mc_pipelines import metrics as registry
from mc_pipelines.publish import m2_kpis

from .metrics import _TENANT, MetricTools, ToolError, _date, money, pct

_PCT = {"gross_margin_pct", "attribution_coverage", "safety_event_recall"}
_USD = {"gross_margin_usd", "unit_cost_per_request_usd", "cost_per_outcome_usd"}
_FEATURE = re.compile(r"^F[0-4]$")
# fct_cost_to_serve components (M2-02): LLM tokens plus allocated shared infrastructure by service group.
COMPONENTS = ("llm_cost_usd", "agent_compute_usd", "vector_usd", "network_observability_usd", "third_party_usd")


class CostBreakdownTools:
    """AG-03 on fully loaded cost (M2-04 step 5a): `fct_cost_to_serve` by component, day x tenant x feature."""

    def __init__(self, gold_dir: Path) -> None:
        self.path = Path(gold_dir) / "fct_cost_to_serve.parquet"
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} not found: run the M2 pipeline first")
        self.con = duckdb.connect()
        self.con.execute("SET threads = 1")
        self.window = self.con.execute(f"SELECT min(cost_date), max(cost_date) FROM read_parquet('{self.path}')").fetchall()[0]

    def cost_breakdown(self, start_date: str, end_date: str, tenant_id: str | None = None,
                       feature_id: str | None = None) -> dict[str, Any]:
        """Fully loaded cost to serve and its components over a period, optionally for one tenant and/or feature."""
        s, e = _date("start_date", start_date), _date("end_date", end_date)
        if s > e:
            raise ToolError("start_date must be on or before end_date")
        lo, hi = self.window
        if e < lo or s > hi:
            raise ToolError(f"no data in {s}..{e}; gold covers {lo}..{hi}")
        s, e = max(s, lo), min(e, hi)
        where, params = ["cost_date BETWEEN ? AND ?"], [s, e]
        if tenant_id is not None:
            if not isinstance(tenant_id, str) or not _TENANT.match(tenant_id):
                raise ToolError(f"tenant_id must look like bc-t0001, got {tenant_id!r}")
            where.append("tenant_id = ?")
            params.append(tenant_id)
        if feature_id is not None:
            if not isinstance(feature_id, str) or not _FEATURE.match(feature_id):
                raise ToolError(f"feature_id must be one of F0..F4, got {feature_id!r}")
            where.append("feature_id = ?")
            params.append(feature_id)
        cols = ", ".join(f"coalesce(sum({c}), 0)" for c in (*COMPONENTS, "cost_to_serve_usd"))
        row = self.con.execute(
            f"SELECT count(*), coalesce(sum(requests), 0), {cols} FROM read_parquet('{self.path}') WHERE {' AND '.join(where)}",
            params).fetchall()[0]
        if row[0] == 0:
            raise ToolError("no cost rows for that tenant/feature in the period")
        requests, parts, total = int(row[1]), [Decimal(v) for v in row[2:-1]], Decimal(row[-1])
        return {"tenant_id": tenant_id or "all", "feature_id": feature_id or "all", "cost_to_serve_usd": money(total),
                "components": {c: {"usd": money(v), "share_pct": pct(v, total)} for c, v in zip(COMPONENTS, parts, strict=True)},
                "request_count": requests,
                "cost_per_request_usd": f"${(total / requests).quantize(Decimal('0.0001'), ROUND_HALF_UP)}" if requests else None,
                "covered_from": s.isoformat(), "covered_to": e.isoformat(), "days": (e - s).days + 1,
                "feature_scope": "F0-F4 (fully loaded)", "data_label": "synthetic"}


class M2KpiTools:
    def __init__(self, gold_dir: Path) -> None:
        self.gold = Path(gold_dir)
        self.names = tuple(registry.load())

    def kpi(self, metric: str) -> dict:
        """One registry KPI over the whole window, as a display string."""
        if metric not in self.names:
            raise ToolError(f"unknown metric {metric!r}; choose one of {', '.join(self.names)}")
        value = m2_kpis(self.gold, (metric,))[metric]
        if value is None:
            return {"metric": metric, "display": None}
        d = Decimal(str(value))
        if metric in _PCT:
            shown = f"{(d * 100).quantize(Decimal('0.01'), ROUND_HALF_UP)}%"
        elif metric in _USD:
            shown = money(d) if abs(d) >= 1 else f"${d.quantize(Decimal('0.0001'), ROUND_HALF_UP)}"
        else:
            shown = str(d)
        return {"metric": metric, "description": registry.load()[metric]["description"], "display": shown}


class AnalystTools(MetricTools):
    """`MetricTools` plus the registry `kpi` and fully loaded `cost_breakdown` tools, for gold with the M2 marts."""

    def __init__(self, gold_dir: Path) -> None:
        super().__init__(gold_dir)
        self.m2 = M2KpiTools(gold_dir)
        self.costs = CostBreakdownTools(gold_dir)

    def specs(self) -> list[dict]:
        kpi = {"toolSpec": {
            "name": "kpi",
            "description": "One fully loaded KPI over the whole window from the metric registry: " + ", ".join(self.m2.names) + ".",
            "inputSchema": {"json": {"type": "object", "properties": {
                "metric": {"type": "string", "enum": list(self.m2.names)}}, "required": ["metric"],
                "additionalProperties": False}}}}
        lo, hi = self.costs.window
        breakdown = {"toolSpec": {
            "name": "cost_breakdown",
            "description": "Fully loaded cost to serve over a period (LLM plus allocated shared infrastructure), split by "
                           "component with each share, plus requests and cost per request. Optional tenant and feature filters.",
            "inputSchema": {"json": {"type": "object", "properties": {
                "start_date": {"type": "string", "description": f"ISO date, inclusive. Data covers {lo} to {hi}."},
                "end_date": {"type": "string", "description": "ISO date, inclusive."},
                "tenant_id": {"type": "string", "description": "Optional tenant ID like bc-t0003."},
                "feature_id": {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4"], "description": "Optional feature."}},
                "required": ["start_date", "end_date"], "additionalProperties": False}}}}
        return [*super().specs(), kpi, breakdown]

    def call(self, name: str, args: dict) -> dict:
        fn = {"kpi": self.m2.kpi, "cost_breakdown": self.costs.cost_breakdown}.get(name)
        if fn is None:
            return super().call(name, args)
        try:
            return fn(**args)
        except TypeError as exc:
            raise ToolError(f"bad arguments for {name}: {exc}") from None


def analyst_tools(gold_dir: Path) -> MetricTools:
    """The analyst's tool set: M1 tools, plus `kpi` and `cost_breakdown` when every M2 mart exists in `gold_dir`."""
    from mc_pipelines.publish import _m2_marts_present

    gold = Path(gold_dir)
    full = _m2_marts_present(gold) and (gold / "fct_cost_to_serve.parquet").exists()
    return AnalystTools(gold_dir) if full else MetricTools(gold_dir)
