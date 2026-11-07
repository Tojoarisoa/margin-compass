"""Churn-adjusted revenue and margin v1 (calc-spec/README.md, ADR-016). Integer arithmetic only. Synthetic inputs only."""

from __future__ import annotations

from typing import Any

from mc_agents.tools.pricing import round_div

_FIELDS = ("revenue_cents", "cost_cents", "churn_bps", "months")


def churn_adjust(inp: dict[str, Any]) -> dict[str, int]:
    """Expected revenue, cost and margin over `months` months when a tenant churns at `churn_bps` per month."""
    for f in _FIELDS:
        v = inp[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"{f} must be a non-negative integer")
    if inp["churn_bps"] > 10000:
        raise ValueError("churn_bps must be at most 10000")
    if not 1 <= inp["months"] <= 60:
        raise ValueError("months must be between 1 and 60")
    survival = 10000
    expected = 0
    for _ in range(inp["months"]):
        expected += survival
        survival = round_div(survival * (10000 - inp["churn_bps"]), 10000)
    revenue = round_div(inp["revenue_cents"] * expected, 10000)
    cost = round_div(inp["cost_cents"] * expected, 10000)
    return {
        "expected_months_bps": expected, "survival_bps": survival,
        "adj_revenue_cents": revenue, "adj_cost_cents": cost, "adj_margin_cents": revenue - cost,
    }
