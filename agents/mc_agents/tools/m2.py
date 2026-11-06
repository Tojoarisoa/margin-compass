"""Read-only M2 KPI tool over the gold marts, every figure from the metric registry (M2-03.1).

`analyst_tools` adds the `kpi` tool only when the gold directory holds every M2 mart, so M1-only gold (and the
replay fixtures recorded on it) keeps the exact M1 tool set. Same rules as `MetricTools`: no LLM arithmetic,
display strings only.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from mc_pipelines import metrics as registry
from mc_pipelines.publish import m2_kpis

from .metrics import MetricTools, ToolError, money

_PCT = {"gross_margin_pct", "attribution_coverage", "safety_event_recall"}
_USD = {"gross_margin_usd", "unit_cost_per_request_usd", "cost_per_outcome_usd"}


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
    """`MetricTools` plus the registry `kpi` tool, for gold that carries the M2 marts."""

    def __init__(self, gold_dir: Path) -> None:
        super().__init__(gold_dir)
        self.m2 = M2KpiTools(gold_dir)

    def specs(self) -> list[dict]:
        kpi = {"toolSpec": {
            "name": "kpi",
            "description": "One fully loaded KPI over the whole window from the metric registry: " + ", ".join(self.m2.names) + ".",
            "inputSchema": {"json": {"type": "object", "properties": {
                "metric": {"type": "string", "enum": list(self.m2.names)}}, "required": ["metric"],
                "additionalProperties": False}}}}
        return [*super().specs(), kpi]

    def call(self, name: str, args: dict) -> dict:
        if name != "kpi":
            return super().call(name, args)
        try:
            return self.m2.kpi(**args)
        except TypeError as exc:
            raise ToolError(f"bad arguments for kpi: {exc}") from None


def analyst_tools(gold_dir: Path) -> MetricTools:
    """The analyst's tool set: M1 tools, plus `kpi` when every M2 mart exists in `gold_dir`."""
    from mc_pipelines.publish import _m2_marts_present

    return AnalystTools(gold_dir) if _m2_marts_present(Path(gold_dir)) else MetricTools(gold_dir)
