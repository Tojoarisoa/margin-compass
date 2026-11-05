"""M2-01 step 5: simulated shared-infrastructure cost export, FOCUS 1.2 shaped (S2; m2-plan.md M2-01 item 5, D3).

One row per cost line per day for BoonCore's own platform: compute for F2 agents, vector storage and
queries for F3, egress, observability, and third-party APIs, tagged `x-feature` and `x-env` (observability
carries no `x-feature` tag: it is shared and needs an allocation rule in M2-02). Includes PT-12: an idle
staging GPU (2025-12-01 to 2026-02-28) and an oversized vector tier throughout.

Variable lines are driven by the month's telemetry request counts, so infra tracks usage. Rates are
calibrated so shared infra is about 15% of AI COGS at baseline (D3, labeled assumption). Only the FOCUS
columns the pipeline needs are emitted (M2-02 maps them into `stg_focus_*`); costs are USD with no
commitments, so list, contracted, billed and effective cost are equal.

Standalone and not wired into the CLI, so M1 output is unchanged. Determinism: a month depends only on
(seed, month, that month's telemetry rows). All output is synthetic. Parameters marked (assumption) are
labeled inputs (spec §12 item 4).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .m2_telemetry import TelemetryRow, month_days
from .m2_tenants import MONTHS

STREAM = 6  # RNG namespace: tenants [seed, i]; telemetry 3; outcomes 4/5; infra [seed, 6, month]
NOISE_SD = 0.03  # (assumption) day-to-day billing noise on variable lines
REGION = "us-east-1"
PROVIDER = "BoonCore Cloud (synthetic)"
IDLE_GPU_START = date(2025, 12, 1)  # spec §7 PT-12
IDLE_GPU_END = date(2026, 2, 28)  # inclusive


@dataclass(frozen=True)
class CostLine:
    """A cost line. Variable lines are rate x requests of `drivers`; fixed lines are `fixed_usd_per_day`."""

    sku_id: str
    service_name: str
    service_category: str
    resource_type: str
    description: str
    unit: str
    feature_tag: str | None  # None = untagged shared cost
    env: str = "prod"
    drivers: tuple[str, ...] = ()  # feature IDs whose request_count drives the line
    usd_per_unit: float = 0.0
    fixed_usd_per_day: float = 0.0
    active_from: date | None = None
    active_to: date | None = None  # inclusive


# (assumption) all rates; sized so the total is ~15% of AI COGS (about $1.2k/day at the end of the window).
OVERSIZED_VECTOR_USD_PER_DAY = 120.0
RIGHT_SIZED_VECTOR_USD_PER_DAY = 45.0
IDLE_GPU_USD_PER_DAY = 60.0

LINES: tuple[CostLine, ...] = (
    CostLine("compute-f2-agents", "Compute", "Compute", "agent-runtime", "F2 agent runtime", "requests", "F2",
             drivers=("F2",), usd_per_unit=0.020),
    CostLine("vector-storage", "Vector Search", "Databases", "vector-index", "F3 vector index (oversized tier)", "days",
             "F3", fixed_usd_per_day=OVERSIZED_VECTOR_USD_PER_DAY),
    CostLine("vector-queries", "Vector Search", "Databases", "vector-index", "F3 vector queries", "requests", "F3",
             drivers=("F3",), usd_per_unit=0.005),
    CostLine("egress", "Networking", "Networking", "data-transfer", "Internet egress", "requests", "F1",
             drivers=("F1", "F2", "F4"), usd_per_unit=0.0025),
    CostLine("observability", "Observability", "Management and Governance", "log-and-trace", "Logs and traces", "requests",
             None, drivers=("F0", "F1", "F2", "F3", "F4"), usd_per_unit=0.002),
    CostLine("tp-device-manuals", "Third-party APIs", "Other", "api", "Device manual lookup API", "requests", "F2",
             drivers=("F2",), usd_per_unit=0.006),
    CostLine("tp-regulatory-db", "Third-party APIs", "Other", "api", "Regulatory database lookup API", "requests", "F0",
             drivers=("F0",), usd_per_unit=0.003),
    CostLine("staging-gpu-idle", "Compute", "Compute", "gpu-instance", "Staging GPU (idle)", "days", "F2", env="staging",
             fixed_usd_per_day=IDLE_GPU_USD_PER_DAY, active_from=IDLE_GPU_START, active_to=IDLE_GPU_END),
)


@dataclass(frozen=True)
class FocusRow:
    """FOCUS 1.2 columns used by the pipeline (one row per line per day)."""

    charge_period_start: date
    charge_period_end: date  # exclusive, FOCUS convention
    billing_period_start: date
    billing_period_end: date  # exclusive
    billing_currency: str
    provider_name: str
    invoice_issuer_name: str
    service_name: str
    service_category: str
    resource_id: str
    resource_type: str
    sku_id: str
    region_id: str
    charge_category: str
    charge_class: str | None
    charge_frequency: str
    charge_description: str
    consumed_quantity: float
    consumed_unit: str
    list_cost: float
    contracted_cost: float
    billed_cost: float
    effective_cost: float
    tags: str  # JSON object: x-env and, when tagged, x-feature


@dataclass(frozen=True)
class Pt12Label:
    """Ground truth for PT-12 (spec §7): a fixed daily waste to be found by the leak detector."""

    pattern_id: str
    component: str
    sku_id: str
    start: date
    end: date  # inclusive
    expected_impact_usd_per_day: float


def pt12_labels(window_start: date, window_end: date) -> list[Pt12Label]:
    return [
        Pt12Label("PT-12", "idle_staging_gpu", "staging-gpu-idle", IDLE_GPU_START, IDLE_GPU_END, IDLE_GPU_USD_PER_DAY),
        Pt12Label(
            "PT-12", "oversized_vector_tier", "vector-storage", window_start, window_end,
            round(OVERSIZED_VECTOR_USD_PER_DAY - RIGHT_SIZED_VECTOR_USD_PER_DAY, 2),
        ),
    ]


def _active(line: CostLine, day: date) -> bool:
    return (line.active_from is None or day >= line.active_from) and (line.active_to is None or day <= line.active_to)


def _tags(line: CostLine) -> str:
    tags = {"x-env": line.env}
    if line.feature_tag:
        tags["x-feature"] = line.feature_tag
    return json.dumps(tags, sort_keys=True)


def generate_month(seed: int, telemetry: list[TelemetryRow], month_index: int) -> list[FocusRow]:
    """Daily FOCUS rows for one window month, from that month's telemetry rows."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    days = month_days(month_index)
    first, last = days[0], days[-1]
    requests: dict[tuple[date, str], int] = defaultdict(int)
    for r in telemetry:
        d = r.usage_ts.date()
        if not first <= d <= last:
            raise ValueError(f"telemetry row on {d} is outside month {month_index}")
        requests[(d, r.feature_id)] += r.request_count
    rng = np.random.default_rng([seed, STREAM, month_index])
    billing_end = last + timedelta(days=1)
    rows: list[FocusRow] = []
    for day in days:
        for line in LINES:
            noise = float(rng.normal(1.0, NOISE_SD))  # drawn for every line-day so streams stay aligned
            if not _active(line, day):
                continue
            if line.drivers:
                qty = float(sum(requests[(day, f)] for f in line.drivers))
                if qty == 0:
                    continue
                cost = qty * line.usd_per_unit * max(0.0, noise)
            else:
                qty = 1.0
                cost = line.fixed_usd_per_day
            cost = round(cost, 6)
            rows.append(
                FocusRow(
                    day, day + timedelta(days=1), first, billing_end, "USD", PROVIDER, PROVIDER, line.service_name,
                    line.service_category, f"{line.sku_id}/{line.env}", line.resource_type, line.sku_id, REGION, "Usage",
                    None, "Usage-Based" if line.drivers else "Recurring", line.description, qty, line.unit,
                    cost, cost, cost, cost, _tags(line),
                )
            )
    return rows


def generate_all(seed: int, telemetry_by_month: list[list[TelemetryRow]]) -> list[FocusRow]:
    if len(telemetry_by_month) != MONTHS:
        raise ValueError(f"expected {MONTHS} months of telemetry")
    rows: list[FocusRow] = []
    for m, t in enumerate(telemetry_by_month):
        rows += generate_month(seed, t, m)
    return rows
