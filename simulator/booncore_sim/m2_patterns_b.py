"""M2-01 step 8: patterns PT-08..PT-14 (spec §8, §9), mostly label-only.

Unlike PT-01..PT-07 these do not change baseline telemetry: PT-08, PT-09 and PT-11 are counterfactual
opportunities or proposals (the rows stay as they are, the label carries the computed savings), PT-13 is
the seasonality already in the baseline, PT-10 scales power tenants, and PT-14 draws renewal outcomes.
`expected_impact_usd_per_day` is computed from the rows, never estimated. Standalone, not wired into the CLI.
All output is synthetic. (assumption) marks labeled inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from .m2_catalog import SAFETY_RECALL_FLOOR, TIER_QUALITY, price_on, request_cost_usd
from .m2_outcomes import DailyOutcome
from .m2_patterns import PatternLabel, _scale_volume, row_cost
from .m2_telemetry import TelemetryRow
from .m2_tenants import PLAN_RANK, WINDOW_END, WINDOW_START, M2Tenant

PT09_START = date(2026, 9, 1)  # (assumption) date of the seeded ACT-1 proposal
PT10_COUNT = 12
PT10_FACTOR = 3  # spec §8: 3x median usage
PT11_START = date(2026, 3, 1)  # b-mid price cut (spec §4)
CHURN_STREAM = 6  # RNG namespace: tenants [seed, i]; telemetry 3; outcomes 4, 5; churn [seed, 6, i]
SENSITIVITY = {"imaging": 0.0, "in_vitro_diagnostics": 0.5, "patient_monitoring": 0.5, "surgical": 0.5, "other_devices": 1.0}
# (assumption) logistic coefficients: intercept, price change %, csat-3, tenure years, sensitivity, unresolved sev-1 rate
CHURN_BETA = (-3.2, 0.12, -0.9, -0.15, 0.6, 8.0)
DOWNGRADE_BETA = (-2.6, 0.10, -0.6, -0.10, 0.5, 6.0)
PRICE_CHANGE_PCT_RANGE = (0.0, 8.0)  # (assumption) renewal list uplift drawn per tenant


def _days(start: date, end: date) -> int:
    return (end - start).days + 1


def _savings(rows: list[TelemetryRow], pred, alt_model: str, start: date, end: date) -> float:
    """Cost of the matching rows minus the same tokens on `alt_model`, per day (positive = cheaper)."""
    gain = 0.0
    for r in rows:
        d = r.usage_ts.date()
        if start <= d <= end and pred(r):
            alt = price_on(alt_model, d)
            cached = r.gen_ai_usage_cache_read_input_tokens if alt.cache_read_usd_per_mtok is not None else 0
            alt_cost = request_cost_usd(
                alt,
                input_tokens=r.gen_ai_usage_input_tokens,
                cache_read_tokens=cached,
                output_tokens=r.gen_ai_usage_output_tokens,
                batch=r.is_batch and alt.batch_discount_pct is not None,
            )
            gain += row_cost(r) - alt_cost
    return gain / _days(start, end)


def _is_f1_mid(r: TelemetryRow) -> bool:
    return r.feature_id == "F1" and r.gen_ai_request_model == "a-mid"


def pt08_blocked_cheaper_option(rows: list[TelemetryRow], tenants: list[M2Tenant]) -> PatternLabel:
    """Tenants whose approved-model or EU clauses forbid Provider B: `b-mid` would pass quality but is not allowed.

    Rows are unchanged; the impact is the savings the constraint forbids, so the constraint check (AG-07)
    must reject any proposal to use it. (assumption) `c-small` is also forbidden but has no cached pricing, so
    only `b-mid` is priced here.
    """
    blocked = tuple(sorted(t.tenant_id for t in tenants if "b" not in t.allowed_providers))
    ids = set(blocked)
    impact = _savings(rows, lambda r: r.tenant_id in ids and _is_f1_mid(r), "b-mid", WINDOW_START, WINDOW_END)
    return PatternLabel(
        "PT-08", "blocked_cheaper_option", blocked, "F1", "b-mid", WINDOW_START, WINDOW_END, "model",
        "b-mid would pass quality but is forbidden by approved-model or EU clauses", impact, ("constraint_check",),
    )


def pt09_safety_downgrade_proposal(rows: list[TelemetryRow]) -> PatternLabel:
    """Seeded ACT-1 proposal: F0 from the mid tier to the small tier. Recall falls below the 99% floor.

    The impact is the savings the proposal claims; the verifier must reject it (EV-13) because small-tier recall
    is under KPI-08(b)'s floor. Rows are unchanged.
    """
    recall = TIER_QUALITY["small"][2]
    assert recall < SAFETY_RECALL_FLOOR
    impact = _savings(rows, lambda r: r.feature_id == "F0", "a-small", PT09_START, WINDOW_END)
    return PatternLabel(
        "PT-09", "safety_screening_downgrade", (), "F0", "a-small", PT09_START, WINDOW_END, "safety_recall",
        f"recall {recall:.1%} < {SAFETY_RECALL_FLOOR:.0%}", impact, ("verifier",),
    )


def pt10_power_tenants(
    rows: list[TelemetryRow], tenants: list[M2Tenant]
) -> tuple[list[TelemetryRow], PatternLabel]:
    """12 "unlimited AI" tenants (the first 12 by id) use 3x their baseline volume for the whole window.

    (assumption) 3x is applied to the tenant's own baseline, not to the plan median. Flat AI revenue means
    the extra cost lands straight on margin.
    """
    targets = tuple(sorted(t.tenant_id for t in tenants if t.unlimited_ai)[:PT10_COUNT])
    ids = set(targets)
    out, base, new = [], [], []
    for r in rows:
        if r.tenant_id in ids:
            r2 = _scale_volume(r, PT10_FACTOR)
            base.append(r)
            new.append(r2)
            r = r2
        out.append(r)
    impact = (sum(map(row_cost, new)) - sum(map(row_cost, base))) / _days(WINDOW_START, WINDOW_END)
    label = PatternLabel(
        "PT-10", "power_tenants", targets, "all", None, WINDOW_START, WINDOW_END, "request_count",
        "3x median usage on unlimited-AI plans", impact, ("cost_to_serve_explorer", "constraint_check"),
    )
    return out, label


def pt11_unused_cheaper_option(rows: list[TelemetryRow], tenants: list[M2Tenant]) -> PatternLabel:
    """The `b-mid` price cut on 2026-03-01 is not adopted: F1 stays on `a-mid` for tenants that may use Provider B."""
    allowed = {t.tenant_id for t in tenants if "b" in t.allowed_providers}
    impact = _savings(rows, lambda r: r.tenant_id in allowed and _is_f1_mid(r), "b-mid", PT11_START, WINDOW_END)
    return PatternLabel(
        "PT-11", "unused_cheaper_option", tuple(sorted(allowed)), "F1", "b-mid", PT11_START, WINDOW_END, "model",
        "b-mid -40% price cut not adopted", impact, ("ai_efficiency_engineer",),
    )


def pt13_seasonality_and_growth() -> PatternLabel:
    """Label for the seasonality and growth already in the baseline (spec §7). Not a leak: impact is 0 and it must not alert."""
    return PatternLabel(
        "PT-13", "seasonality_and_growth", (), "all", None, WINDOW_START, WINDOW_END, "request_count",
        "weekly, respiratory +25%, fiscal year-end +15%, +2% tenants per month", 0.0, ("forecaster",),
    )


@dataclass(frozen=True)
class RenewalEvent:
    """One renewal outcome with its true probabilities, for calibration tests (spec §9)."""

    tenant_id: str
    renewal_date: date
    price_change_pct: float
    csat_mean: float
    tenure_years: float
    p_churn: float
    p_downgrade: float  # conditional on not churning
    outcome: str  # renewed | downgraded | churned
    arr_usd: float


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def renewal_probs(
    beta: tuple[float, ...], price_change_pct: float, csat_mean: float, tenure_years: float, sensitivity: float, sev1_rate: float
) -> float:
    b0, b1, b2, b3, b4, b5 = beta
    return _sigmoid(b0 + b1 * price_change_pct + b2 * (csat_mean - 3) + b3 * tenure_years + b4 * sensitivity + b5 * sev1_rate)


def pt14_churn_events(
    seed: int, tenants: list[M2Tenant], outcomes: list[DailyOutcome]
) -> tuple[list[RenewalEvent], PatternLabel]:
    """Renewal churn and downgrade events for tenants whose renewal date falls in the window (spec §9, open loop).

    Inputs come from the tenant's outcomes before renewal. (assumption) unresolved Sev-1 rate is the Sev-1
    share of tickets times the share not resolved remotely. Downgrade is only possible for plans above starter.
    The impact is the expected ARR lost per window day.
    """
    agg: dict[str, list[float]] = {}
    for o in outcomes:
        a = agg.setdefault(o.tenant_id, [0.0] * 4)
        a[0] += o.tickets
        a[1] += o.csat_sum
        a[2] += o.sev1_tickets
        a[3] += o.resolved_remotely
    events = []
    for i, t in enumerate(tenants):
        if not WINDOW_START <= t.renewal_date <= WINDOW_END:
            continue
        rng = np.random.default_rng([seed, CHURN_STREAM, i])
        price = float(rng.uniform(*PRICE_CHANGE_PCT_RANGE))
        u_churn, u_down = float(rng.random()), float(rng.random())
        tickets, csat_sum, sev1, remote = agg.get(t.tenant_id, [0.0] * 4)
        csat = csat_sum / tickets if tickets else 3.0
        sev1_rate = (sev1 / tickets) * (1 - remote / tickets) if tickets else 0.0
        tenure = (t.renewal_date - t.onboarded_on).days / 365
        args = (price, csat, tenure, SENSITIVITY[t.segment], sev1_rate)
        p_churn = renewal_probs(CHURN_BETA, *args)
        p_down = renewal_probs(DOWNGRADE_BETA, *args) if PLAN_RANK[t.plan] > 0 else 0.0
        outcome = "churned" if u_churn < p_churn else "downgraded" if u_down < p_down else "renewed"
        events.append(
            RenewalEvent(t.tenant_id, t.renewal_date, price, csat, tenure, p_churn, p_down, outcome, float(t.arr_usd))
        )
    impact = sum(e.p_churn * e.arr_usd for e in events) / _days(WINDOW_START, WINDOW_END)
    label = PatternLabel(
        "PT-14", "churn_behavior", tuple(e.tenant_id for e in events), "all", None, WINDOW_START, WINDOW_END, "renewal_outcome",
        "logistic churn and downgrade at renewal (spec §9)", impact, ("churn_model",),
    )
    return events, label


def apply_pt08_to_pt14(
    rows: list[TelemetryRow], tenants: list[M2Tenant], seed: int, outcomes: list[DailyOutcome]
) -> tuple[list[TelemetryRow], list[PatternLabel], list[RenewalEvent]]:
    """Labels for PT-08..PT-14 in id order (PT-12 is in `m2_focus`); only PT-10 changes the rows."""
    labels = [pt08_blocked_cheaper_option(rows, tenants), pt09_safety_downgrade_proposal(rows)]
    labels.append(pt11_unused_cheaper_option(rows, tenants))
    rows, pt10 = pt10_power_tenants(rows, tenants)  # last, so PT-08/09/11 are priced on baseline rows
    labels.append(pt10)
    labels.append(pt13_seasonality_and_growth())
    events, lab = pt14_churn_events(seed, tenants, outcomes)
    labels.append(lab)
    labels.sort(key=lambda x: x.pattern_id)
    return rows, labels, events


