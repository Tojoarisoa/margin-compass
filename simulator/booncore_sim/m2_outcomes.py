"""M2-01 step 4: ticket outcomes (spec §3 S4, §4 quality table, §10, §12 item 3a; m2-plan.md M2-01).

Stored as tenant x day aggregates, plus per-ticket rows for a 10% sample and for every labeled safety
event. Every ticket is drawn individually (vectorized per tenant-day), so aggregates and the per-ticket
rows always agree. F0 flags follow the recall of the tier F0 is routed to (spec §4).

Ticket counts use the same mean as telemetry (plan rate x size x calendar effects) but their own RNG
stream, so outcome totals track request volume statistically, not ticket for ticket.
Standalone and not wired into the CLI, so M1 output is unchanged. Determinism: a month depends only on
(seed, month, tenant). No ticket text exists (spec §9). All output is synthetic; parameters marked
(assumption) are labeled inputs (spec §12 item 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .config import PLANS
from .m2_catalog import TIER_QUALITY, price_on
from .m2_telemetry import ROUTING, _size_factor, day_multiplier, month_days
from .m2_tenants import MONTHS, M2Tenant

STREAM = 4  # RNG namespace: tenants [seed, i]; telemetry [seed, 3, ...]; outcomes [seed, 4, ...]
BASELINE_STREAM = 5  # per-tenant baseline remote-resolution share (month independent)
TICKET_SAMPLE_RATE = 0.10  # spec §12 item 3a
F2_TICKET_SHARE = 0.40  # spec §3: F2 handles 40% of tickets
REMOTE_SHARE_RANGE = (0.30, 0.50)  # spec §3, ADR-017
SAFETY_BASE_RATE = {  # spec §2.2 (assumption)
    "imaging": 0.010,
    "in_vitro_diagnostics": 0.008,
    "patient_monitoring": 0.015,
    "surgical": 0.012,
    "other_devices": 0.005,
}
FALSE_FLAG_RATE = 0.005  # (assumption) F0 flags on tickets with no safety event
FIELD_VISIT_AFTER_F2 = 0.60  # (assumption) F2 ticket not resolved remotely
FIELD_VISIT_OTHER = 0.15  # (assumption) ticket without F2
ESCALATION = (0.30, 0.10, 0.03)  # (assumption) by Sev-1/2/3
CSAT_P = {  # (assumption) P(csat = 1..5)
    "base": (0.03, 0.07, 0.20, 0.40, 0.30),
    "remote": (0.01, 0.03, 0.11, 0.35, 0.50),
    "escalated": (0.15, 0.25, 0.30, 0.20, 0.10),
}
EVAL_BASE = 0.85  # (assumption) eval_score of a frontier-quality answer
EVAL_SD = 0.07


@dataclass(frozen=True)
class TicketOutcome:
    ticket_id: str
    tenant_id: str
    ticket_date: date
    severity: int  # 1..3
    used_f2: bool
    resolved_remotely: bool
    field_visit_booked: bool
    escalated: bool
    csat: int
    safety_event_label: bool  # ground truth
    safety_flag: bool  # F0 output
    eval_score: float


@dataclass(frozen=True)
class DailyOutcome:
    """Tenant x day aggregate. Sums, never ratios, so rates recompute from summed counts."""

    tenant_id: str
    day: date
    tickets: int
    sev1_tickets: int
    sev2_tickets: int
    sev3_tickets: int
    f2_tickets: int
    resolved_remotely: int
    field_visits_booked: int
    escalated: int
    csat_sum: int
    safety_events_labeled: int
    safety_events_flagged: int  # labeled events that F0 flagged (true positives)
    safety_flags_total: int
    eval_score_sum: float


def baseline_remote_share(seed: int, tenant_index: int) -> float:
    rng = np.random.default_rng([seed, STREAM, BASELINE_STREAM, tenant_index])
    return float(rng.uniform(*REMOTE_SHARE_RANGE))


def _tier(feature_id: str) -> str:
    return price_on(ROUTING[feature_id], date(2026, 1, 1)).tier


def f0_recall() -> float:
    return TIER_QUALITY[_tier("F0")][2]


def f2_remote_multiplier() -> float:
    return TIER_QUALITY[_tier("F2")][1]


def eval_quality(t: M2Tenant) -> float:
    """F1 quality relative to frontier, blended by the plan's small-tier share (spec §2.1, §4)."""
    small = PLANS[t.plan].small_tier_share
    return small * TIER_QUALITY["small"][0] + (1 - small) * TIER_QUALITY["mid"][0]


def _pick(rng: np.random.Generator, probs: tuple[float, ...], n: int) -> np.ndarray:
    return rng.choice(len(probs), size=n, p=probs)


def _day(rng, t: M2Tenant, day: date, n: int, remote_p: float, rate: float, quality: float):
    sev_p = (t.sev1_share, t.sev2_share, t.sev3_share)
    sev = _pick(rng, sev_p, n) + 1
    f2 = rng.random(n) < F2_TICKET_SHARE
    remote = f2 & (rng.random(n) < remote_p)
    visit_p = np.where(f2, FIELD_VISIT_AFTER_F2, FIELD_VISIT_OTHER)
    visit = ~remote & (rng.random(n) < visit_p)
    esc = (rng.random(n) < np.array(ESCALATION)[sev - 1]) & ~remote
    csat = np.empty(n, dtype=np.int64)
    kind = np.where(esc, 2, np.where(remote, 1, 0))
    for k, key in enumerate(("base", "remote", "escalated")):
        idx = kind == k
        if idx.any():
            csat[idx] = _pick(rng, CSAT_P[key], int(idx.sum())) + 1
    event = rng.random(n) < rate
    flag = np.where(event, rng.random(n) < f0_recall(), rng.random(n) < FALSE_FLAG_RATE)
    score = np.clip(rng.normal(EVAL_BASE * quality, EVAL_SD, n), 0.0, 1.0)
    return sev, f2, remote, visit, esc, csat, event, flag, score


def generate_month(
    seed: int, tenants: list[M2Tenant], month_index: int
) -> tuple[list[DailyOutcome], list[TicketOutcome]]:
    """Daily aggregates for every tenant-day, plus sampled and safety-event tickets for one window month."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    daily: list[DailyOutcome] = []
    tickets: list[TicketOutcome] = []
    for i, t in enumerate(tenants):
        rng = np.random.default_rng([seed, STREAM, month_index, i])
        remote_p = baseline_remote_share(seed, i) * f2_remote_multiplier()
        rate = SAFETY_BASE_RATE[t.segment]
        quality = eval_quality(t)
        base = PLANS[t.plan].tickets_per_weekday * _size_factor(t)
        for day in month_days(month_index):
            if day < t.onboarded_on:
                continue
            n = int(rng.poisson(base * day_multiplier(t, day)))
            if n == 0:
                continue
            sev, f2, remote, visit, esc, csat, event, flag, score = _day(rng, t, day, n, remote_p, rate, quality)
            daily.append(
                DailyOutcome(
                    t.tenant_id, day, n, int((sev == 1).sum()), int((sev == 2).sum()), int((sev == 3).sum()),
                    int(f2.sum()), int(remote.sum()), int(visit.sum()), int(esc.sum()), int(csat.sum()),
                    int(event.sum()), int((event & flag).sum()), int(flag.sum()), round(float(score.sum()), 6),
                )
            )
            keep = event | (rng.random(n) < TICKET_SAMPLE_RATE)
            for k in np.flatnonzero(keep):
                tickets.append(
                    TicketOutcome(
                        f"{t.tenant_id}-{day:%Y%m%d}-{k:05d}", t.tenant_id, day, int(sev[k]), bool(f2[k]),
                        bool(remote[k]), bool(visit[k]), bool(esc[k]), int(csat[k]), bool(event[k]),
                        bool(flag[k]), round(float(score[k]), 4),
                    )
                )
    return daily, tickets


def generate_all(seed: int, tenants: list[M2Tenant]) -> tuple[list[DailyOutcome], list[TicketOutcome]]:
    daily: list[DailyOutcome] = []
    tickets: list[TicketOutcome] = []
    for m in range(MONTHS):
        d, k = generate_month(seed, tenants, m)
        daily += d
        tickets += k
    return daily, tickets


def safety_event_recall(rows: list[DailyOutcome]) -> float:
    """Recomputed from summed counts, never averaged (m2-plan.md M2-02)."""
    labeled = sum(r.safety_events_labeled for r in rows)
    return sum(r.safety_events_flagged for r in rows) / labeled if labeled else float("nan")
