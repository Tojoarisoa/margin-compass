"""M2-01 step 5: simulated FOCUS 1.2 shared-infrastructure export for BoonCore's own platform (S2).

One row per (day, service line, env): compute for F2 agents, vector storage and queries for F3, egress,
observability, third-party APIs, plus the PT-12 waste (an idle staging GPU 2025-12-01..2026-02-28 and an
oversized vector tier throughout). Rows carry `x-feature` and `x-env` tags. Standalone, not wired into the
CLI. Deterministic: one RNG stream per (seed, day). All output is synthetic.

Calibration (decision D3, PLAN approved 2026-11-04): shared infra is about 15% of AI COGS. Seed 42 LLM cost
is $3.58M over the 19-month window ($131k in Apr 2025 growing to $226k in Oct 2026); shared infra measures
$0.71M, 16.5% of AI COGS (test band 12-18%; measured 2026-11-06). Parameters marked (assumption) are labeled inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .m2_tenants import MONTHS, WINDOW_END, WINDOW_START, M2Tenant

STREAM = 5  # RNG namespace: tenants [seed, i]; telemetry [seed, 3, ...]; outcomes use their own; focus [seed, 5, day]
FOCUS_VERSION = "1.2"
PROVIDER = "BoonCore Cloud (simulated)"
NOISE_SIGMA = 0.03  # (assumption) daily metering noise on usage-driven lines
WEEKEND_FACTOR = 0.60  # (assumption) shared infra is less elastic than request volume
GPU_IDLE_START = date(2025, 12, 1)  # spec §8 PT-12
GPU_IDLE_END = date(2026, 2, 28)  # inclusive
GPU_IDLE_USD_PER_DAY = 96.0  # (assumption) one idle staging GPU instance, 24h at $4/h
VECTOR_OVERSIZE_USD_PER_DAY = 38.0  # (assumption) excess of the oversized tier over the right-sized tier
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Line:
    service: str  # ServiceName
    category: str  # ServiceCategory
    sku: str  # SkuId
    feature: str  # x-feature tag
    env: str  # x-env tag
    usd_per_tenant_day: float  # (assumption) scales with active tenants; 0 for fixed lines
    fixed_usd_per_day: float
    unit: str  # PricingUnit
    unit_price: float  # ListUnitPrice, used to derive ConsumedQuantity


# (assumption) Sums to about $1.0k/day at 250 tenants early and $1.6k/day at 400 tenants late.
LINES: tuple[Line, ...] = (
    Line("Agent Compute", "Compute", "agent-vcpu-hour", "F2", "prod", 1.45, 0.0, "vCPU-Hours", 0.045),
    Line("Vector Storage", "Databases", "vector-gb-month", "F3", "prod", 0.30, 55.0, "GB-Days", 0.12 / 30),
    Line("Vector Queries", "Databases", "vector-query-1m", "F3", "prod", 0.55, 0.0, "1M-Queries", 4.0),
    Line("Egress", "Networking", "egress-gb", "shared", "prod", 0.35, 0.0, "GB", 0.09),
    Line("Observability", "Management and Governance", "logs-gb", "shared", "prod", 0.45, 20.0, "GB", 0.50),
    Line("Third-Party APIs", "Other", "ocr-page-1k", "F4", "prod", 0.50, 0.0, "1K-Pages", 1.5),
    Line("Staging Environment", "Compute", "staging-baseline", "shared", "staging", 0.0, 30.0, "Hours", 30.0 / 24),
)
GPU_LINE = Line("Idle GPU Instance", "Compute", "gpu-hour", "F2", "staging", 0.0, GPU_IDLE_USD_PER_DAY, "GPU-Hours", 4.0)
OVERSIZE_LINE = Line("Vector Storage", "Databases", "vector-tier-xl", "F3", "prod", 0.0, VECTOR_OVERSIZE_USD_PER_DAY, "Tier-Days", VECTOR_OVERSIZE_USD_PER_DAY)


@dataclass(frozen=True)
class FocusRow:
    """FOCUS 1.2 columns used downstream (billed = effective = list cost; no commitments or discounts)."""

    billing_period_start: date
    billing_period_end: date  # exclusive, first of next month
    charge_period_start: date
    charge_period_end: date  # exclusive
    billing_account_id: str
    provider_name: str
    service_name: str
    service_category: str
    sku_id: str
    charge_category: str  # Usage
    charge_class: str | None
    pricing_unit: str
    consumed_quantity: float
    list_unit_price: float
    billed_cost: float
    effective_cost: float
    list_cost: float
    contracted_cost: float
    billing_currency: str
    tag_feature: str  # x-feature
    tag_env: str  # x-env


def active_tenants(tenants: list[M2Tenant], day: date) -> int:
    return sum(1 for t in tenants if t.onboarded_on <= day)


def _period_end(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _row(day: date, line: Line, cost: float) -> FocusRow:
    cost = float(Decimal(str(cost)).quantize(CENT, ROUND_HALF_UP))
    return FocusRow(
        billing_period_start=day.replace(day=1),
        billing_period_end=_period_end(day),
        charge_period_start=day,
        charge_period_end=day + timedelta(days=1),
        billing_account_id="bc-platform-001",
        provider_name=PROVIDER,
        service_name=line.service,
        service_category=line.category,
        sku_id=line.sku,
        charge_category="Usage",
        charge_class=None,
        pricing_unit=line.unit,
        consumed_quantity=round(cost / line.unit_price, 4),
        list_unit_price=line.unit_price,
        billed_cost=cost,
        effective_cost=cost,
        list_cost=cost,
        contracted_cost=cost,
        billing_currency="USD",
        tag_feature=line.feature,
        tag_env=line.env,
    )


def generate_day(seed: int, n_tenants: int, day: date) -> list[FocusRow]:
    """FOCUS rows for one day, given the number of active tenants."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    rng = np.random.default_rng([seed, STREAM, (day - WINDOW_START).days])
    weekend = WEEKEND_FACTOR if day.weekday() >= 5 else 1.0
    rows: list[FocusRow] = []
    for line in LINES:
        noise = float(rng.lognormal(0.0, NOISE_SIGMA)) if line.usd_per_tenant_day else 1.0
        cost = line.fixed_usd_per_day + line.usd_per_tenant_day * n_tenants * weekend * noise
        rows.append(_row(day, line, cost))
    rows.append(_row(day, OVERSIZE_LINE, VECTOR_OVERSIZE_USD_PER_DAY))  # PT-12, whole window
    if GPU_IDLE_START <= day <= GPU_IDLE_END:
        rows.append(_row(day, GPU_LINE, GPU_IDLE_USD_PER_DAY))  # PT-12, idle even at weekends
    return rows


def generate_all(seed: int, tenants: list[M2Tenant]) -> list[FocusRow]:
    rows: list[FocusRow] = []
    day = WINDOW_START
    while day <= WINDOW_END:
        rows += generate_day(seed, active_tenants(tenants, day), day)
        day += timedelta(days=1)
    return rows


def pt12_waste_usd_per_day(day: date) -> float:
    """Ground truth for labels/patterns: the avoidable daily cost on `day` (idle GPU + oversized vector tier)."""
    gpu = GPU_IDLE_USD_PER_DAY if GPU_IDLE_START <= day <= GPU_IDLE_END else 0.0
    return gpu + VECTOR_OVERSIZE_USD_PER_DAY


__all__ = ["FocusRow", "generate_all", "generate_day", "pt12_waste_usd_per_day", "MONTHS"]
