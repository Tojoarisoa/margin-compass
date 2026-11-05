"""M2-01 step 5: simulated shared-infrastructure cost export for S2 (FOCUS 1.2 shape; m2-plan.md M2-01 item 5).

One row per (day, cost line): compute for F2 agents, vector storage and queries for F3, egress,
observability, and third-party APIs, tagged `x-feature` and `x-env`. PT-12 (spec §8) is injected here: an
idle staging GPU (2025-12-01 -> 2026-02-28) and a vector tier that is oversized throughout. The label's
`expected_impact_usd_per_day` is computed from the same parameters that generate the rows, never estimated.

Standalone and not wired into the CLI, so M1 output is unchanged. Determinism: a month depends only on
(seed, month). Usage drivers use expected ticket volume (no draws), so infra cost tracks the same
calendar effects as telemetry. All output is synthetic; parameters marked (assumption) are labeled inputs
(spec §12 item 4). Billed, effective, list, and contracted cost are equal: on-demand, no commitments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .config import PLANS
from .m2_outcomes import F2_TICKET_SHARE
from .m2_telemetry import _size_factor, day_multiplier, month_days
from .m2_tenants import MONTHS, M2Tenant

STREAM = 6  # RNG namespace: tenants [seed, i]; telemetry 3; outcomes 4/5; infra [seed, 6, month]
NOISE_SIGMA = 0.03  # (assumption) day-to-day billing noise on usage lines
PROVIDER = "Amazon Web Services"
CURRENCY = "USD"
F2_COMPUTE_PER_REQUEST = 0.003  # (assumption) $ per F2 agent step
F2_REQUESTS_PER_TICKET = 6.0  # spec §3
F3_REQUESTS_PER_TICKET = 2.0
VECTOR_QUERY_USD = 0.0001  # (assumption) per F3 query
VECTOR_RIGHT_SIZED_BASE_USD = 12.0  # (assumption) $/day for the smallest tier that fits the corpus
VECTOR_PER_TENANT_USD = 0.04  # (assumption) $/day per active tenant (corpus grows with tenants)
VECTOR_PROVISIONED_USD = 52.0  # (assumption) PT-12: fixed $/day of the oversized tier
EGRESS_MB_PER_TICKET = 6.0  # (assumption)
EGRESS_USD_PER_GB = 0.09
OBS_BASE_USD = 18.0  # (assumption) $/day
OBS_PER_TENANT_USD = 0.04
THIRD_PARTY_USD_PER_TICKET = 0.008  # (assumption) speech/OCR API per ticket
GPU_HOURLY_USD = 2.10  # (assumption) PT-12 idle staging GPU
GPU_START = date(2025, 12, 1)  # spec §8
GPU_END = date(2026, 2, 28)  # inclusive

_Q = Decimal("0.0001")


@dataclass(frozen=True)
class FocusRow:
    """Subset of FOCUS 1.2 columns used by M2-02 (ingestion, allocation)."""

    charge_period_start: date
    charge_period_end: date  # exclusive: start + 1 day
    billing_currency: str
    billed_cost: Decimal
    effective_cost: Decimal
    list_cost: Decimal
    contracted_cost: Decimal
    charge_category: str  # Usage | Purchase
    charge_class: str | None
    charge_description: str
    charge_frequency: str
    provider_name: str
    service_name: str
    service_category: str
    sub_account_id: str
    resource_id: str
    resource_type: str
    consumed_quantity: float
    consumed_unit: str
    x_feature: str
    x_env: str
    synthetic: bool = True  # spec §3 rule 10


@dataclass(frozen=True)
class InfraPatternLabel:
    """Fields of a labels/patterns row (spec §8); the pattern step wraps these."""

    pattern_id: str
    type: str
    feature: str
    start_date: date
    end_date: date | None
    affected_metric: str
    magnitude: float
    expected_impact_usd_per_day: float
    detectable_by: str


def _d(x: float) -> Decimal:
    return Decimal(repr(round(x, 6))).quantize(_Q, ROUND_HALF_UP)


def expected_tickets(tenants: list[M2Tenant], day: date) -> float:
    return sum(
        PLANS[t.plan].tickets_per_weekday * _size_factor(t) * day_multiplier(t, day) for t in tenants if t.onboarded_on <= day
    )


def vector_right_sized_usd(active_tenants: int) -> float:
    return VECTOR_RIGHT_SIZED_BASE_USD + VECTOR_PER_TENANT_USD * active_tenants


def gpu_idle(day: date) -> bool:
    return GPU_START <= day <= GPU_END


def _row(day: date, cost: float, desc: str, service: str, category: str, rtype: str, rid: str, qty: float, unit: str, feature: str, env: str, freq: str = "Usage-Based") -> FocusRow:
    c = _d(cost)
    return FocusRow(day, day + timedelta(days=1), CURRENCY, c, c, c, c, "Usage", None, desc, freq, PROVIDER, service, category,
                    f"mc-{env}", rid, rtype, round(qty, 4), unit, feature, env)


def generate_month(seed: int, tenants: list[M2Tenant], month_index: int) -> list[FocusRow]:
    """Daily shared-infrastructure cost rows for one window month."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    rng = np.random.default_rng([seed, STREAM, month_index])
    rows: list[FocusRow] = []
    for day in month_days(month_index):
        active = sum(1 for t in tenants if t.onboarded_on <= day)
        tickets = expected_tickets(tenants, day)
        noise = lambda: float(rng.lognormal(0.0, NOISE_SIGMA))  # noqa: E731
        f2_req = tickets * F2_TICKET_SHARE * F2_REQUESTS_PER_TICKET
        f3_req = tickets * F3_REQUESTS_PER_TICKET
        egress_gb = tickets * EGRESS_MB_PER_TICKET / 1024
        rows += [
            _row(day, f2_req * F2_COMPUTE_PER_REQUEST * noise(), "F2 agent runtime compute", "AWS Lambda", "Compute",
                 "Function", "mc-prod-f2-agent", f2_req, "Requests", "F2", "prod"),
            _row(day, VECTOR_PROVISIONED_USD, "Vector store provisioned tier", "Vector Store", "Databases",
                 "Index", "mc-prod-f3-vector", 1.0, "Days", "F3", "prod", "Recurring"),
            _row(day, f3_req * VECTOR_QUERY_USD * noise(), "Vector store queries", "Vector Store", "Databases",
                 "Index", "mc-prod-f3-vector", f3_req, "Queries", "F3", "prod"),
            _row(day, egress_gb * EGRESS_USD_PER_GB * noise(), "Data transfer out", "Amazon CloudFront", "Networking",
                 "Distribution", "mc-prod-egress", egress_gb, "GB", "shared", "prod"),
            _row(day, (OBS_BASE_USD + OBS_PER_TENANT_USD * active) * noise(), "Logs and metrics", "Amazon CloudWatch",
                 "Management and Governance", "LogGroup", "mc-prod-observability", float(active), "Tenants", "shared", "prod"),
            _row(day, tickets * THIRD_PARTY_USD_PER_TICKET * noise(), "Speech and OCR API", "Third-party API",
                 "Other", "Api", "mc-prod-3p-speech-ocr", tickets, "Tickets", "F2", "prod"),
        ]
        if gpu_idle(day):
            rows.append(_row(day, GPU_HOURLY_USD * 24, "GPU instance (staging)", "Amazon EC2", "Compute",
                             "Instance", "mc-staging-f2-gpu", 24.0, "Hours", "F2", "staging", "Recurring"))
    return rows


def generate_all(seed: int, tenants: list[M2Tenant]) -> list[FocusRow]:
    rows: list[FocusRow] = []
    for m in range(MONTHS):
        rows += generate_month(seed, tenants, m)
    return rows


def pt12_labels(tenants: list[M2Tenant]) -> list[InfraPatternLabel]:
    """PT-12 labels. Impact = the fixed $/day above what a right-sized configuration would cost."""
    from .m2_tenants import WINDOW_END, WINDOW_START

    n_days = (WINDOW_END - WINDOW_START).days + 1
    excess = sum(
        VECTOR_PROVISIONED_USD - vector_right_sized_usd(sum(1 for t in tenants if t.onboarded_on <= WINDOW_START + timedelta(days=k)))
        for k in range(n_days)
    ) / n_days
    return [
        InfraPatternLabel("PT-12", "shared_infra_waste", "F2", GPU_START, GPU_END, "idle_gpu_cost_usd", GPU_HOURLY_USD * 24,
                          GPU_HOURLY_USD * 24, "allocation + leak detector"),
        InfraPatternLabel("PT-12", "shared_infra_waste", "F3", WINDOW_START, None, "oversized_vector_tier_usd",
                          VECTOR_PROVISIONED_USD, round(excess, 4), "allocation + leak detector"),
    ]
