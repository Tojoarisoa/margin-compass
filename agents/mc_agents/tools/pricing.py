"""Pricing engine v1 (calc-spec/README.md, ADR-016). Integer arithmetic only, so results are exact to the cent.

Money in cents, usage rates in micro-dollars per unit, ratios in basis points. Synthetic inputs only.
"""

from __future__ import annotations

from typing import Any

_FIELDS = (
    "seats", "seat_price_cents", "addon_cents", "included_units", "overage_rate_micro", "usage_units",
    "outcome_price_micro", "outcomes", "discount_bps", "cost_cents",
)


def round_div(n: int, d: int) -> int:
    """Round half up of n / d for n >= 0, d > 0."""
    return (2 * n + d) // (2 * d)


def price_plan(plan: dict[str, Any]) -> dict[str, int | None]:
    """Revenue and margin for one tenant-month. `usage_cap_cents` is optional (None = no cap)."""
    for f in _FIELDS:
        v = plan[f]
        if isinstance(v, bool) or not isinstance(v, int) or (v < 0 and f != "cost_cents"):
            raise ValueError(f"{f} must be a non-negative integer")
    cap = plan.get("usage_cap_cents")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 0):
        raise ValueError("usage_cap_cents must be a non-negative integer or None")
    if plan["discount_bps"] > 10000:
        raise ValueError("discount_bps must be at most 10000")
    seat = plan["seats"] * plan["seat_price_cents"]
    overage = round_div(max(0, plan["usage_units"] - plan["included_units"]) * plan["overage_rate_micro"], 10000)
    outcome = round_div(plan["outcomes"] * plan["outcome_price_micro"], 10000)
    usage = overage + outcome if cap is None else min(overage + outcome, cap)
    gross = seat + plan["addon_cents"] + usage
    discount = round_div(gross * plan["discount_bps"], 10000)
    revenue = gross - discount
    margin = revenue - plan["cost_cents"]
    bps = None if revenue == 0 else (1 if margin >= 0 else -1) * round_div(abs(margin) * 10000, revenue)
    return {
        "seat_cents": seat, "overage_cents": overage, "outcome_cents": outcome, "usage_cents": usage,
        "gross_cents": gross, "discount_cents": discount, "revenue_cents": revenue,
        "margin_cents": margin, "margin_bps": bps,
    }
