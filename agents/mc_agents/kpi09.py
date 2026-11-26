"""M5-04 step 4c-3: KPI-09 prediction of an ACT-2 plan price change (docs/plans/m5-plan.md).

At approval time, each tenant on the plan is priced before and after the change with the calc-spec `price_plan` tool
(`price_scenario`: pricing engine v1 + churn-adjusted revenue v1), using the tool's own churn assumption, not the
simulator's hidden response parameters (that would make the backtest circular). The result is the predicted revenue
and margin change per month after the change takes effect; step 4c-4 compares it with the observed counterfactual
difference. The calc-spec has no demand response, so the predicted cost change is 0 and margin moves with revenue,
unless the action declares an expected volume change (run 186): then each tenant's pre-period monthly AI cost is
priced after the change at (1 - volume_change) through the same tool, so margin also carries the cost side.

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


def _bps(name: str, v: Any, hi: int | None = None) -> None:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or (hi is not None and v > hi):
        raise ValueError(f"{name} must be a non-negative integer" + (f" at most {hi}" if hi is not None else ""))


def predict_plan_change(
    tenants: list[dict[str, Any]], uplift_bps: int, months: int, churn_bps: int = DEFAULT_CHURN_BPS,
    volume_change_bps: int = 0,
) -> dict[str, Any]:
    """Predicted change of an add-on price uplift of `uplift_bps` on every tenant given, for months 1..`months`.

    `volume_change_bps` is the action's declared expected drop in AI usage after the change (0 = no demand response):
    a tenant's monthly `cost_cents` becomes cost * (10000 - volume_change_bps) / 10000 in the "after" plan.
    Month k's change is the churn-adjusted change over k months minus that over k - 1 months, so the series sums to
    the tool's `churn.delta` over the whole horizon.
    """
    _bps("uplift_bps", uplift_bps)
    _bps("volume_change_bps", volume_change_bps, 10000)
    if not tenants:
        raise ValueError("no tenants on the plan")
    monthly_rev = [0] * months
    monthly_margin = [0] * months
    for t in tenants:
        plan = tenant_plan(t)
        after = {"addon_cents": round_div(plan["addon_cents"] * (10000 + uplift_bps), 10000)}
        if volume_change_bps and plan["cost_cents"]:
            after["cost_cents"] = round_div(plan["cost_cents"] * (10000 - volume_change_bps), 10000)
        prev_rev = prev_margin = 0
        for k in range(1, months + 1):
            d = price_scenario({**plan, "after": after, "churn_bps": churn_bps, "months": k})["churn"]["delta"]
            monthly_rev[k - 1] += d["adj_revenue_cents_change"] - prev_rev
            monthly_margin[k - 1] += d["adj_margin_cents_change"] - prev_margin
            prev_rev, prev_margin = d["adj_revenue_cents_change"], d["adj_margin_cents_change"]
    return {
        "tool": "price_plan", "tenants": len(tenants), "uplift_bps": uplift_bps, "churn_bps": churn_bps,
        "months": months, "volume_change_bps": volume_change_bps, "monthly_revenue_delta_cents": monthly_rev, "monthly_margin_delta_cents": monthly_margin,
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


def tenants_on_plan(tenants: list, plan: str, cost_cents: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Simulator tenants (`arr_usd`, `ai_addon_arr_usd`, `discount_pct` as Decimal) on `plan`, as cents and bps.
    `cost_cents` (tenant_id -> monthly AI cost in cents, measured before the change) adds `cost_cents` per tenant."""
    out = [{"tenant_id": t.tenant_id, "arr_cents": int(round(t.arr_usd * 100)),
            "addon_arr_cents": int(round(t.ai_addon_arr_usd * 100)), "discount_bps": int(round(t.discount_pct * 10000))}
           for t in tenants if t.plan == plan]
    if cost_cents is not None:
        out = [{**t, "cost_cents": int(cost_cents.get(t["tenant_id"], 0))} for t in out]
    return out


def months_covered(start: Any, end: Any) -> int:
    """Calendar months from `start` to `end` (dates), both included: 2026-09-01 .. 2026-10-31 -> 2."""
    return (end.year - start.year) * 12 + end.month - start.month + 1


def backtest_plan_change(tenants: list, plan: str, uplift_bps: int, effective_on: Any, window_end: Any,
                         observed_revenue_usd: float, observed_margin_usd: float, volume_change_bps: int = 0,
                         monthly_cost_cents: dict[str, int] | None = None) -> dict[str, Any]:
    """KPI-09 for one ACT-2 "plan/<plan>": prediction from the action's explicit effective date (the same date the
    simulator prices from, `booncore_sim.m5_effects.effective_on`) to the window end vs the observed difference.
    The prediction counts whole calendar months, so pick an effective date on the first of a month.
    Observed figures are the action's summed `revenue_delta_usd` and `saved_usd + revenue_delta_usd` over all its days
    (measurement status ignored: the prediction covers every day from the effective date).
    `volume_change_bps` is the action's declared demand response and `monthly_cost_cents` each tenant's AI cost in the
    calendar month before the effective date (known at approval); both default to no cost side."""
    if volume_change_bps and monthly_cost_cents is None:
        raise ValueError("volume_change_bps needs monthly_cost_cents (the pre-period AI cost per tenant)")
    pred = predict_plan_change(tenants_on_plan(tenants, plan, monthly_cost_cents), uplift_bps,
                               months_covered(effective_on, window_end), volume_change_bps=volume_change_bps)
    out = kpi09_report(pred, int(round(observed_revenue_usd * 100)), int(round(observed_margin_usd * 100)))
    return {**out, "plan": plan, "tenants": pred["tenants"], "months": pred["months"], "churn_bps": pred["churn_bps"],
            "volume_change_bps": volume_change_bps,
            "monthly_predicted_revenue_cents": pred["monthly_revenue_delta_cents"],
            "monthly_predicted_margin_cents": pred["monthly_margin_delta_cents"]}
