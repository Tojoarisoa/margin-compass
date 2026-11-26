"""M5-03 step 1: closed-loop effects of approved actions (PLAN.md §8.4, docs/plans/m5-plan.md).

Pure and deterministic: the same (seed, approvals, rows) always gives the same rows. Nothing happens before an
action's approval date, and an effect ramps in with an adoption lag and only partly realizes. ACT-1 routes a feature's
requests to the batch API; ACT-2 (price/included usage) and ACT-3 (account fair-use cap, churn response) scale demand.
No approvals means unchanged rows, so existing runs are not affected. All output is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

from .m2_telemetry import TelemetryRow

LAG_MIN_DAYS, LAG_MAX_DAYS = 3, 14  # adoption lag before the effect starts (assumption)
RAMP_DAYS = 14  # days from first effect to the realized share (assumption)
REALIZATION_MIN, REALIZATION_MAX = 0.60, 0.95  # partial realization of the intended change (assumption)
# Owner decision 2026-11-26, option (b): real owner decisions come after the simulation window ends, so each one is
# placed a fixed lead before the action's data date (the last day of data behind it). The date is labeled simulated.
DECISION_LEAD_DAYS = 60


@dataclass(frozen=True)
class Approval:
    action_id: str
    action_type: str  # ACT-1 | ACT-2 | ACT-3
    target: str  # for ACT-1: "<feature_id>/<metric>", for example "F4/cost"
    approved_on: date  # the day effects can start from (simulated when `simulated_date`)
    simulated_date: bool = False  # True: approved_on = data date - DECISION_LEAD_DAYS, not the owner's decision date


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


# ACT-2 / ACT-3 demand responses (assumptions, synthetic). Revenue is not in telemetry, so these change usage volume;
# the revenue side is computed from the volume change in M5-04.
ACT2_MAX_REDUCTION = 0.12  # share of a feature's requests that go away at full effect after a price/allowance change
ACT3_MAX_REDUCTION = 0.30  # share of a tenant's requests that go away under a fair-use cap
ACT3_CHURN_PROB = 0.06  # chance the account churns after the action (seeded per action)
ACT3_CHURN_DELAY_DAYS = 45


def churn_day(seed: int, a: Approval) -> date | None:
    """Day from which an ACT-3 account no longer produces telemetry, or None if it stays."""
    if _unit(seed, a.action_id, "churn") >= ACT3_CHURN_PROB:
        return None
    return a.approved_on + timedelta(days=ACT3_CHURN_DELAY_DAYS + int(_unit(seed, a.action_id, "cd") * 30))


def _scale(r: TelemetryRow, keep: float) -> TelemetryRow:
    return replace(
        r,
        request_count=round(r.request_count * keep),
        gen_ai_usage_input_tokens=round(r.gen_ai_usage_input_tokens * keep),
        gen_ai_usage_output_tokens=round(r.gen_ai_usage_output_tokens * keep),
        gen_ai_usage_cache_read_input_tokens=round(r.gen_ai_usage_cache_read_input_tokens * keep),
    )


def plan_of(a: Approval) -> str | None:
    """Plan name of an ACT-2 "plan/<plan>" target (the nightly review's form), else None."""
    head, _, rest = a.target.partition("/")
    return rest if a.action_type == "ACT-2" and head == "plan" and rest else None


def apply_act2_act3(
    rows: list[TelemetryRow], approvals: list[Approval], seed: int, plans: dict[str, str] | None = None
) -> list[TelemetryRow]:
    """ACT-2 target "<feature_id>/price" cuts that feature's volume for all tenants; ACT-2 target "plan/<plan>" (the
    nightly review's form) cuts the volume of the tenants on that plan (`plans`: tenant_id -> plan; without it the plan
    target changes nothing); ACT-3 target "<tenant_id>/cap" cuts one tenant's volume and may churn it (rows dropped
    from the churn day)."""
    a2 = [(a, a.target.split("/")[0]) for a in approvals if a.action_type == "ACT-2" and plan_of(a) is None]
    a2p = [(a, plan_of(a)) for a in approvals if plan_of(a) is not None]
    plans = plans or {}
    a3 = [(a, a.target.split("/")[0], churn_day(seed, a)) for a in approvals if a.action_type == "ACT-3"]
    if not a2 and not a2p and not a3:
        return rows
    out = []
    for r in rows:
        day, keep, gone = r.usage_ts.date(), 1.0, False
        for a, feature in a2:
            if r.feature_id == feature:
                keep *= 1 - ACT2_MAX_REDUCTION * share(seed, a, day)
        for a, plan in a2p:
            if plans.get(r.tenant_id) == plan:
                keep *= 1 - ACT2_MAX_REDUCTION * share(seed, a, day)
        for a, tenant, cd in a3:
            if r.tenant_id == tenant:
                keep *= 1 - ACT3_MAX_REDUCTION * share(seed, a, day)
                gone = gone or (cd is not None and day >= cd)
        if gone:
            continue
        out.append(_scale(r, keep) if keep < 1.0 else r)
    return out


def apply_effects(
    rows: list[TelemetryRow], approvals: list[Approval], seed: int, plans: dict[str, str] | None = None
) -> list[TelemetryRow]:
    """All effects in a fixed order. No approvals returns the same list. `plans` (tenant_id -> plan) lets an ACT-2
    "plan/<plan>" target find its tenants."""
    return apply_act2_act3(apply_act1(rows, approvals, seed), approvals, seed, plans)


def load_approvals(path: Path | str, data_date: date | None = None) -> list[Approval]:
    """Read approvals.jsonl (action_id, action_type, target, decision, decided_at, ...). A missing file means no
    approvals. Only `approved` decisions with a known action type and a target produce effects; other lines are
    skipped. The latest line per action_id wins. With `data_date` (the last day of data the actions were proposed
    from), each approval takes effect from `data_date - DECISION_LEAD_DAYS` and is marked `simulated_date`."""
    p = Path(path)
    if not p.exists():
        return []
    latest: dict[str, dict] = {}
    for line in p.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            latest[d["action_id"]] = d
    on = None if data_date is None else data_date - timedelta(days=DECISION_LEAD_DAYS)
    return [
        Approval(d["action_id"], d["action_type"], d["target"], on or date.fromisoformat(d["decided_at"][:10]), on is not None)
        for d in latest.values()
        if d.get("decision") == "approved" and d.get("action_type") in ("ACT-1", "ACT-2", "ACT-3") and d.get("target")
    ]
