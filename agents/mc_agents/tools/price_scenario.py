"""AG-05 `price_plan` tool v2 (M4-05 step 3c-3d): one call prices a plan before and after a change, with churn.

Composition only: every number comes from the calc-spec functions `price_plan` (pricing engine v1) and
`churn_adjust` (churn-adjusted revenue v1), so no new formula and the dashboard parity (EV-12) is unchanged.

Why: with the per-question cost cap ($0.01, enforced), AG-05 could afford about two model calls, but a
before/after/churn answer took four (price, price, churn, words). Now it takes two (one tool call, words).

- No plan field given: the labelled example plan (`plan_source: "example"`). Some but not all given: error
  (never mix a given plan with example values).
- `after`: the fields that change (for example `{"discount_bps": 400}`), priced on the same plan.
- `churn_bps` (and `months`, default 12): churn-adjusted figures for before and, when given, after.
- v3 (3c-3h): every basis-point input is echoed as an exact percent string (`after.changes_pct`, `churn.churn_pct`;
  calc-spec "Display conversion": percent = bps / 100), so an answer may quote the question's "4%" from the ledger
  instead of the verifier withholding it. A unit conversion of an input, not a new formula.
- v4 (3c-3i): `after.delta` and `churn.delta` are the signed after-minus-before changes from calc-spec "Scenario
  difference v1" (`scenario_delta`), and `churn.survival_pct` echoes `survival_bps` as percent, so an answer never
  has to compute a difference or convert a rate itself.
Synthetic inputs only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from mc_agents.tools.churn_adjust import churn_adjust
from mc_agents.tools.pricing import _FIELDS, price_plan
from mc_agents.tools.scenario_delta import scenario_delta

# The prc-01..03 golden plan, labelled as an example in every answer that uses it.
EXAMPLE_PLAN: dict[str, int] = {
    "seats": 10, "seat_price_cents": 5000, "addon_cents": 0, "included_units": 1000, "usage_units": 1500,
    "overage_rate_micro": 20000, "outcome_price_micro": 0, "outcomes": 0, "discount_bps": 0, "cost_cents": 20000,
}
_PLAN_KEYS = (*_FIELDS, "usage_cap_cents")
DEFAULT_MONTHS = 12
_PLAN_DELTA = ("revenue_cents", "margin_cents", "margin_bps")
_CHURN_DELTA = ("adj_revenue_cents", "adj_margin_cents")


def _pick(d: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: d[k] for k in keys}


def bps_to_pct(bps: int) -> str:
    """calc-spec display conversion: exact percent of a basis-point value (400 -> "4", 250 -> "2.5")."""
    d = Decimal(int(bps)) / 100
    return format(d.normalize() if d == d.to_integral_value() else d, "f")


def price_scenario(inp: dict[str, Any]) -> dict[str, Any]:
    unknown = set(inp) - {*_PLAN_KEYS, "after", "churn_bps", "months"}
    if unknown:
        raise ValueError(f"unknown fields: {sorted(unknown)}")
    given = {k: inp[k] for k in _PLAN_KEYS if k in inp}
    if not given:
        plan, source = dict(EXAMPLE_PLAN), "example"
    else:
        missing = [f for f in _FIELDS if f not in given]
        if missing:
            raise ValueError(f"missing plan fields {missing}; give all of them or none (example plan)")
        plan, source = given, "given"
    out: dict[str, Any] = {"plan_source": source, "plan": plan, **price_plan(plan)}
    runs: list[tuple[str, dict[str, Any], dict[str, Any]]] = [("before", plan, out)]
    if inp.get("after") is not None:
        changes = inp["after"]
        if not isinstance(changes, dict) or not changes or set(changes) - set(_PLAN_KEYS):
            raise ValueError("after must be a non-empty object of plan fields to change")
        after_plan = {**plan, **changes}
        out["after"] = {"changes": changes, **price_plan(after_plan)}
        pct = {f"{k[:-4]}_pct": bps_to_pct(v) for k, v in changes.items() if k.endswith("_bps")}
        if pct:
            out["after"]["changes_pct"] = pct
        out["after"]["delta"] = scenario_delta({"before": _pick(out, _PLAN_DELTA), "after": _pick(out["after"], _PLAN_DELTA)})
        runs.append(("after", after_plan, out["after"]))
    if inp.get("churn_bps") is not None:
        months = inp.get("months", DEFAULT_MONTHS)
        churn: dict[str, Any] = {"churn_bps": inp["churn_bps"], "churn_pct": bps_to_pct(inp["churn_bps"]),
                                 "months": months}
        for key, p, res in runs:
            churn[key] = churn_adjust({"revenue_cents": res["revenue_cents"], "cost_cents": p["cost_cents"],
                                       "churn_bps": inp["churn_bps"], "months": months})
        churn["survival_pct"] = bps_to_pct(churn["before"]["survival_bps"])
        if "after" in churn:
            churn["delta"] = scenario_delta({"before": _pick(churn["before"], _CHURN_DELTA),
                                             "after": _pick(churn["after"], _CHURN_DELTA)})
        out["churn"] = churn
    elif "months" in inp:
        raise ValueError("months needs churn_bps")
    return out
