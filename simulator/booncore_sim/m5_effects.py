"""M5-03 step 1: closed-loop effects of approved actions (PLAN.md §8.4, docs/plans/m5-plan.md).

Pure and deterministic: the same (seed, approvals, rows) always gives the same rows. Nothing happens before an
action's approval date, and an effect ramps in with an adoption lag and only partly realizes. This step covers
ACT-1 (route a feature's requests to the batch API); ACT-2 and ACT-3 effects come in later steps.
No approvals means unchanged rows, so existing runs are not affected. All output is synthetic.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, timedelta

from .m2_telemetry import TelemetryRow

LAG_MIN_DAYS, LAG_MAX_DAYS = 3, 14  # adoption lag before the effect starts (assumption)
RAMP_DAYS = 14  # days from first effect to the realized share (assumption)
REALIZATION_MIN, REALIZATION_MAX = 0.60, 0.95  # partial realization of the intended change (assumption)


@dataclass(frozen=True)
class Approval:
    action_id: str
    action_type: str  # ACT-1 | ACT-2 | ACT-3
    target: str  # for ACT-1: "<feature_id>/<metric>", for example "F4/cost"
    approved_on: date


def _unit(*parts: object) -> float:
    """Deterministic value in [0, 1) from the parts."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def lag_days(seed: int, a: Approval) -> int:
    return LAG_MIN_DAYS + int(_unit(seed, a.action_id, "lag") * (LAG_MAX_DAYS - LAG_MIN_DAYS + 1))


def realization(seed: int, a: Approval) -> float:
    return REALIZATION_MIN + _unit(seed, a.action_id, "real") * (REALIZATION_MAX - REALIZATION_MIN)


def share(seed: int, a: Approval, day: date) -> float:
    """Fraction of the affected traffic that has switched on `day`: 0 before approval plus lag, then a linear ramp."""
    start = a.approved_on + timedelta(days=lag_days(seed, a))
    if day < start:
        return 0.0
    return realization(seed, a) * min(1.0, (day - start).days / RAMP_DAYS)


def apply_act1(rows: list[TelemetryRow], approvals: list[Approval], seed: int) -> list[TelemetryRow]:
    """Switch the targeted feature's rows to batch, a growing share of them over time (cheaper batch pricing)."""
    acts = [(a, a.target.split("/")[0]) for a in approvals if a.action_type == "ACT-1"]
    if not acts:
        return rows
    out = []
    for r in rows:
        for a, feature in acts:
            if r.feature_id == feature and not r.is_batch:
                p = share(seed, a, r.usage_ts.date())
                if p > 0 and _unit(seed, a.action_id, r.tenant_id, r.usage_ts.isoformat()) < p:
                    r = replace(r, is_batch=True)
        out.append(r)
    return out
