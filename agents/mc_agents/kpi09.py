"""M5-04 step 4c-3: KPI-09 prediction of an ACT-2 plan price change (docs/plans/m5-plan.md).

At approval time, each tenant on the plan is priced before and after the change with the calc-spec `price_plan` tool
(`price_scenario`: pricing engine v1 + churn-adjusted revenue v1), using the tool's own churn assumption, not the
simulator's hidden response parameters (that would make the backtest circular). The result is the predicted revenue
and margin change per month after the change takes effect; step 4c-4 compares it with the observed counterfactual
difference. The calc-spec has no demand response, so the predicted cost change is 0 and margin moves with revenue.

Money in cents, rates in basis points, integer arithmetic only (no new formula). Synthetic inputs only.
"""

from __future__ import annotations

from typing import Any

from mc_agents.tools.price_scenario import price_scenario
from mc_agents.tools.pricing import round_div

# Same churn assumption as AG-05 when a question gives none (mc_agents/specialists.py: "pass churn_bps 200").
DEFAULT_CHURN_BPS = 200
_TENANT_KEYS = ("tenant_id", "arr_cents", "addon_arr_cents", "discount_bps")


def tenant_plan(t: dict[str, Any]) -> dict[str, int]:
    """One tenant-month as a calc-spec plan: the non-add-on ARR as one seat, the AI add-on as `addon_cents`."""
    missing = [k for k in _TENANT_KEYS if k not in t]
    if missing:
        raise ValueError(f"tenant is missing {missing}")
    if t["addon_arr_cents"] > t["arr_cents"]:
        raise ValueError("addon_arr_cents must not exceed arr_cents")
    return {
        "seats": 1, "seat_price_cents": round_div(t["arr_cents"] - t["addon_arr_cents"], 12),
        "addon_cents": round_div(t["addon_arr_cents"], 12), "included_units": 0, "usage_units": 0,
        "overage_rate_micro": 0, "outcome_price_micro": 0, "outcomes": 0, "discount_bps": t["discount_bps"],
        "cost_cents": t.get("cost_cents", 0),
    }


def predict_plan_change(
    tenants: list[dict[str, Any]], uplift_bps: int, months: int, churn_bps: int = DEFAULT_CHURN_BPS
) -> dict[str, Any]:
    """Predicted change of an add-on price uplift of `uplift_bps` on every tenant given, for months 1..`months`.

    Month k's change is the churn-adjusted change over k months minus that over k - 1 months, so the series sums to
    the tool's `churn.delta` over the whole horizon.
    """
    if isinstance(uplift_bps, bool) or not isinstance(uplift_bps, int) or uplift_bps < 0:
        raise ValueError("uplift_bps must be a non-negative integer")
    if not tenants:
        raise ValueError("no tenants on the plan")
    monthly_rev = [0] * months
    monthly_margin = [0] * months
    for t in tenants:
        plan = tenant_plan(t)
        after = {"addon_cents": round_div(plan["addon_cents"] * (10000 + uplift_bps), 10000)}
        prev_rev = prev_margin = 0
        for k in range(1, months + 1):
            d = price_scenario({**plan, "after": after, "churn_bps": churn_bps, "months": k})["churn"]["delta"]
            monthly_rev[k - 1] += d["adj_revenue_cents_change"] - prev_rev
            monthly_margin[k - 1] += d["adj_margin_cents_change"] - prev_margin
            prev_rev, prev_margin = d["adj_revenue_cents_change"], d["adj_margin_cents_change"]
    return {
        "tool": "price_plan", "tenants": len(tenants), "uplift_bps": uplift_bps, "churn_bps": churn_bps,
        "months": months, "monthly_revenue_delta_cents": monthly_rev, "monthly_margin_delta_cents": monthly_margin,
        "revenue_delta_cents": sum(monthly_rev), "margin_delta_cents": sum(monthly_margin), "synthetic": True,
    }


# M5-04 step 4c-4: KPI-09 compares the prediction above with the observed counterfactual difference.
KPI09_TARGET_BPS = 1000  # error at most 10% (PLAN.md KPI-09)


def error_bps(predicted: int, observed: int) -> int | None:
    """|predicted - observed| / |observed| in basis points (round half up); None when nothing was observed."""
    if observed == 0:
        return None
    return round_div(abs(predicted - observed) * 10000, abs(observed))


def kpi09_report(prediction: dict[str, Any], observed_revenue_cents: int, observed_margin_cents: int) -> dict[str, Any]:
    """KPI-09 for one ACT-2: revenue and margin error against the 10% target. `passed` needs both within target."""
    rev = error_bps(prediction["revenue_delta_cents"], observed_revenue_cents)
    mar = error_bps(prediction["margin_delta_cents"], observed_margin_cents)
    return {
        "kpi": "KPI-09", "target_bps": KPI09_TARGET_BPS,
        "predicted_revenue_cents": prediction["revenue_delta_cents"], "observed_revenue_cents": observed_revenue_cents,
        "revenue_error_bps": rev,
        "predicted_margin_cents": prediction["margin_delta_cents"], "observed_margin_cents": observed_margin_cents,
        "margin_error_bps": mar,
        "passed": rev is not None and mar is not None and rev <= KPI09_TARGET_BPS and mar <= KPI09_TARGET_BPS,
        "synthetic": True,
    }
