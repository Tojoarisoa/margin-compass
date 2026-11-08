"""ROI calculators v1 (PLAN.md §4.3, KPI-13). Integer arithmetic only. Synthetic inputs only."""

from __future__ import annotations

from typing import Any

from mc_agents.tools.pricing import round_div


def _nonneg(inp: dict[str, Any], f: str) -> int:
    v = inp[f]
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError(f"{f} must be a non-negative integer")
    return v


def roi_multiple(inp: dict[str, Any]) -> dict[str, int]:
    """KPI-13: (margin recovered - platform cost) / platform cost, in bps (10000 = 1.0x). Payback in months."""
    recovered = _nonneg(inp, "margin_recovered_cents")
    cost = _nonneg(inp, "platform_cost_cents")
    if cost == 0:
        raise ValueError("platform_cost_cents must be positive")
    net = recovered - cost
    out = {"net_cents": net, "roi_bps": round_div(net * 10000, cost)}
    if "monthly_saving_cents" in inp:
        monthly = _nonneg(inp, "monthly_saving_cents")
        out["payback_months"] = -(-cost // monthly) if monthly else -1  # ceil; -1 means never
    return out
