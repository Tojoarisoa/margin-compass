"""Read-only M2 KPI tool over the gold marts, every figure from the metric registry (M2-03.1).

Not yet registered with the analyst (that changes the agent tool set, which needs the image to carry
`mc_pipelines`; see docs/progress.md). Same rules as `MetricTools`: no LLM arithmetic, display strings only.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from mc_pipelines import metrics as registry
from mc_pipelines.publish import m2_kpis

from .metrics import ToolError, money

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
