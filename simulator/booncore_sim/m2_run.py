"""M2-01 step 9: compose the M2 generators and the injected patterns into one deterministic run (spec §8, §10).

`patterned_month` is the unit of the chunked backfill: pattern transforms are row-wise and date-conditioned, so
a month generated alone equals the same month inside a full run. `generate_patterned` is the full run and also
computes the labels (impacts over each pattern's whole span, so they need all months). Standalone, not wired into
the CLI or the landing writer, so M1 output is unchanged. All output is synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import m2_focus, m2_outcomes, m2_patterns, m2_patterns_b, m2_telemetry
from .m2_patterns import PatternLabel
from .m2_patterns_b import RenewalEvent
from .m2_telemetry import RawRequest, TelemetryRow
from .m2_tenants import WINDOW_END, WINDOW_START, M2Tenant, generate_m2_tenants
from .m5_effects import Approval, apply_effects


@dataclass
class PatternedRun:
    tenants: list[M2Tenant]
    telemetry: list[TelemetryRow]
    raw_requests: list[RawRequest]
    labels: list[PatternLabel]
    renewal_events: list[RenewalEvent]
    outcomes: list[m2_outcomes.DailyOutcome]


def _transform(rows: list[TelemetryRow], tenants: list[M2Tenant]) -> tuple[list[TelemetryRow], list[PatternLabel]]:
    """PT-01..PT-07 and PT-10 (the patterns that change rows), in a fixed order."""
    rows, labels = m2_patterns.apply_pt01_to_pt04(rows, tenants)
    rows, more = m2_patterns.apply_pt05_to_pt07(rows, tenants)
    labels += more
    rows, pt10 = m2_patterns_b.pt10_power_tenants(rows, tenants)
    return rows, [*labels, pt10]


def patterned_month(seed: int, tenants: list[M2Tenant], month_index: int) -> tuple[list[TelemetryRow], list[RawRequest]]:
    """One backfill chunk: baseline telemetry with the row-changing patterns applied."""
    rows, raw = m2_telemetry.generate_month(seed, tenants, month_index)
    return _transform(rows, tenants)[0], raw


def pt12_label() -> PatternLabel:
    days = (WINDOW_END - WINDOW_START).days + 1
    total = sum(m2_focus.pt12_waste_usd_per_day(WINDOW_START + timedelta(days=i)) for i in range(days))
    return PatternLabel(
        "PT-12", "shared_infra_waste", (), "all", None, WINDOW_START, WINDOW_END, "shared_infra_cost",
        "idle staging GPU 2025-12-01..2026-02-28 plus an oversized vector tier", total / days,
        ("allocation", "leak_detector"),
    )


def generate_patterned(seed: int, approvals: list[Approval] | None = None) -> PatternedRun:
    """Full run. `approvals` (M5-03, opt-in) apply closed-loop effects to the telemetry after the patterns;
    None or empty leaves every row unchanged."""
    tenants = generate_m2_tenants(seed)[0]
    base, raw = m2_telemetry.generate_all(seed, tenants)
    outcomes = m2_outcomes.generate_all(seed, tenants)[0]
    # Opportunity and proposal labels are priced on the baseline rows, before PT-10 scales anything.
    pt08 = m2_patterns_b.pt08_blocked_cheaper_option(base, tenants)
    pt09 = m2_patterns_b.pt09_safety_downgrade_proposal(base)
    pt11 = m2_patterns_b.pt11_unused_cheaper_option(base, tenants)
    rows, labels = _transform(base, tenants)
    if approvals:
        rows = apply_effects(rows, approvals, seed)
    events, pt14 = m2_patterns_b.pt14_churn_events(seed, tenants, outcomes)
    labels += [pt08, pt09, pt11, pt12_label(), m2_patterns_b.pt13_seasonality_and_growth(), pt14]
    labels.sort(key=lambda x: x.pattern_id)
    return PatternedRun(tenants, rows, raw, labels, events, outcomes)


def renewal_events(seed: int) -> list[RenewalEvent]:
    """PT-14 renewal events for one seed without generating telemetry (training data for the churn model)."""
    tenants = generate_m2_tenants(seed)[0]
    return m2_patterns_b.pt14_churn_events(seed, tenants, m2_outcomes.generate_all(seed, tenants)[0])[0]


__all__ = ["PatternedRun", "generate_patterned", "patterned_month", "pt12_label", "renewal_events"]
