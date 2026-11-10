"""M5-04 step 1: realized cost effect per action x day by counterfactual difference (PLAN.md §8.4).

For each approval the effect is measured against the same rows without it (same seed, so the only difference is the
action). Cost side only: `saved_usd` = counterfactual cost - actual cost (negative when the action raised cost).
`revenue_delta_usd` is the revenue side: the AI add-on is flat, so volume cuts change no revenue; only an ACT-3 churn
loses the account's net daily revenue (ARR after discount / 365, current price; assumption) from the churn day. Savings count as realized only after the 14-day measurement
window since approval; before that the row is `pending_verification` (PLAN.md §8.4). Synthetic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .m2_patterns import row_cost
from .m2_telemetry import TelemetryRow
from .m5_effects import Approval, apply_effects, churn_day

MEASUREMENT_WINDOW_DAYS = 14


@dataclass(frozen=True)
class RealizedRow:
    action_id: str
    day: date
    counterfactual_cost_usd: float
    actual_cost_usd: float
    saved_usd: float
    revenue_delta_usd: float  # <= 0: revenue lost to churn; 0 when no tenants are given
    status: str  # realized | pending_verification


def _daily_cost(rows: list[TelemetryRow]) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for r in rows:
        out[r.usage_ts.date()] += row_cost(r)
    return out


def _daily_revenue(tenants: list) -> dict[str, float]:
    return {t.tenant_id: float(t.arr_usd * (1 - t.discount_pct)) / 365 for t in tenants}


def realized_by_action(
    rows: list[TelemetryRow], approvals: list[Approval], seed: int, tenants: list | None = None
) -> list[RealizedRow]:
    """`rows` is the baseline (no approvals). One output row per action and day on which its cost or revenue differs."""
    base = _daily_cost(rows)
    revenue = _daily_revenue(tenants or [])
    out: list[RealizedRow] = []
    for a in sorted(approvals, key=lambda x: x.action_id):
        actual = _daily_cost(apply_effects(rows, [a], seed))
        lost = 0.0
        cd = churn_day(seed, a) if a.action_type == "ACT-3" else None
        if cd is not None:
            lost = revenue.get(a.target.split("/")[0], 0.0)
        cutoff = a.approved_on + timedelta(days=MEASUREMENT_WINDOW_DAYS)
        for day in sorted(base):
            cf, ac = base[day], actual.get(day, 0.0)
            rev = -round(lost, 6) if cd is not None and day >= cd else 0.0
            if abs(cf - ac) < 1e-9 and rev == 0.0:
                continue
            status = "realized" if day >= cutoff else "pending_verification"
            out.append(RealizedRow(a.action_id, day, round(cf, 6), round(ac, 6), round(cf - ac, 6), rev, status))
    return out
