"""M5-04 step 1: realized cost effect per action x day by counterfactual difference (PLAN.md §8.4).

For each approval the effect is measured against the same rows without it (same seed, so the only difference is the
action). Cost side only: `saved_usd` = counterfactual cost - actual cost (negative when the action raised cost).
Revenue from the volume change comes in a later step. Savings count as realized only after the 14-day measurement
window since approval; before that the row is `pending_verification` (PLAN.md §8.4). Synthetic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .m2_patterns import row_cost
from .m2_telemetry import TelemetryRow
from .m5_effects import Approval, apply_effects

MEASUREMENT_WINDOW_DAYS = 14


@dataclass(frozen=True)
class RealizedRow:
    action_id: str
    day: date
    counterfactual_cost_usd: float
    actual_cost_usd: float
    saved_usd: float
    status: str  # realized | pending_verification


def _daily_cost(rows: list[TelemetryRow]) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for r in rows:
        out[r.usage_ts.date()] += row_cost(r)
    return out


def realized_by_action(rows: list[TelemetryRow], approvals: list[Approval], seed: int) -> list[RealizedRow]:
    """`rows` is the baseline (no approvals). One output row per action and day on which its cost differs."""
    base = _daily_cost(rows)
    out: list[RealizedRow] = []
    for a in sorted(approvals, key=lambda x: x.action_id):
        actual = _daily_cost(apply_effects(rows, [a], seed))
        cutoff = a.approved_on + timedelta(days=MEASUREMENT_WINDOW_DAYS)
        for day in sorted(base):
            cf, ac = base[day], actual.get(day, 0.0)
            if abs(cf - ac) < 1e-9:
                continue
            status = "realized" if day >= cutoff else "pending_verification"
            out.append(RealizedRow(a.action_id, day, round(cf, 6), round(ac, 6), round(cf - ac, 6), status))
    return out
