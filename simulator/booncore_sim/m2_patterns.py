"""M2-01 step 6: injected patterns PT-01..PT-04 (spec §8), applied to baseline telemetry rows.

Patterns are post-hoc transforms of the baseline rows from `m2_telemetry`, so the baseline stays unchanged and
every pattern is switchable. Each returns a `PatternLabel` for `labels/patterns` whose
`expected_impact_usd_per_day` is computed (patterned cost minus baseline cost over the pattern's days), never
estimated. Standalone, not wired into the CLI. All output is synthetic. (assumption) marks labeled inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from .m2_catalog import price_on, request_cost_usd
from .m2_telemetry import TelemetryRow
from .m2_tenants import WINDOW_END, M2Tenant

PT01_START = date(2025, 9, 15)
PT01_INPUT_FACTOR = 1.40  # spec §8: +40% input tokens per request
PT02_OUTAGE = date(2026, 1, 20)
PT02_DAYS = 9
PT02_RETRY_FACTOR = 4  # spec §8: retries x4
PT03_SWITCH = date(2025, 11, 3)
PT03_BEFORE_MODEL = "a-mid"  # F4 ran on the mid tier until the silent upgrade
PT04_START = date(2026, 4, 7)
PT04_HIT_BASELINE = 0.70
PT04_HIT_AFTER = 0.15


@dataclass(frozen=True)
class PatternLabel:
    pattern_id: str
    type: str
    tenant_ids: tuple[str, ...]  # empty = all tenants
    feature: str
    model: str | None
    start_date: date
    end_date: date
    affected_metric: str
    magnitude: str
    expected_impact_usd_per_day: float
    detectable_by: tuple[str, ...]


def row_cost(r: TelemetryRow) -> float:
    p = price_on(r.gen_ai_request_model, r.usage_ts.date())
    return request_cost_usd(
        p,
        input_tokens=r.gen_ai_usage_input_tokens,
        cache_read_tokens=r.gen_ai_usage_cache_read_input_tokens,
        output_tokens=r.gen_ai_usage_output_tokens,
        batch=r.is_batch,
    )


def _impact(base: list[TelemetryRow], new: list[TelemetryRow], start: date, end: date) -> float:
    days = (end - start).days + 1
    return (sum(map(row_cost, new)) - sum(map(row_cost, base))) / days


def _select(rows, pred):
    return [r for r in rows if pred(r)]


def pt01_prompt_regression(rows: list[TelemetryRow]) -> tuple[list[TelemetryRow], PatternLabel]:
    """F1 input tokens +40% for all tenants from 2025-09-15; cached prefix tokens are unchanged."""
    hit = lambda r: r.feature_id == "F1" and r.usage_ts.date() >= PT01_START  # noqa: E731
    out, base, new = [], [], []
    for r in rows:
        if hit(r):
            extra = round((r.gen_ai_usage_input_tokens - r.gen_ai_usage_cache_read_input_tokens) * (PT01_INPUT_FACTOR - 1))
            r2 = replace(r, gen_ai_usage_input_tokens=r.gen_ai_usage_input_tokens + extra)
            base.append(r)
            new.append(r2)
            r = r2
        out.append(r)
    label = PatternLabel(
        "PT-01", "prompt_regression", (), "F1", None, PT01_START, WINDOW_END, "input_tokens_per_request",
        "+40% uncached input tokens", _impact(base, new, PT01_START, WINDOW_END), ("leak_detector",),
    )
    return out, label


def pt02_retry_loop(
    rows: list[TelemetryRow], tenants: list[M2Tenant]
) -> tuple[list[TelemetryRow], PatternLabel]:
    """F2 retries x4 for the first imaging tenant (by id) for 9 days from the connector outage on 2026-01-20.

    (assumption) Each added retry re-sends an average request, so billed tokens grow by the added retries.
    """
    target = sorted(t.tenant_id for t in tenants if t.segment == "imaging" and t.onboarded_on <= PT02_OUTAGE)[0]
    end = PT02_OUTAGE + timedelta(days=PT02_DAYS - 1)
    out, base, new = [], [], []
    for r in rows:
        d = r.usage_ts.date()
        if r.feature_id == "F2" and r.tenant_id == target and PT02_OUTAGE <= d <= end and r.request_count:
            added = r.retry_count * (PT02_RETRY_FACTOR - 1)
            k = 1 + added / r.request_count
            r2 = replace(
                r,
                retry_count=r.retry_count * PT02_RETRY_FACTOR,
                gen_ai_usage_input_tokens=round(r.gen_ai_usage_input_tokens * k),
                gen_ai_usage_output_tokens=round(r.gen_ai_usage_output_tokens * k),
                gen_ai_usage_cache_read_input_tokens=round(r.gen_ai_usage_cache_read_input_tokens * k),
            )
            base.append(r)
            new.append(r2)
            r = r2
        out.append(r)
    label = PatternLabel(
        "PT-02", "agent_retry_loop", (target,), "F2", None, PT02_OUTAGE, end, "retry_count",
        "retries x4", _impact(base, new, PT02_OUTAGE, end), ("leak_detector",),
    )
    return out, label


def pt03_silent_model_upgrade(rows: list[TelemetryRow]) -> tuple[list[TelemetryRow], PatternLabel]:
    """F4 ran on the mid tier before 2025-11-03; baseline telemetry has it on frontier throughout.

    The pattern moves earlier F4 rows to the mid model, so the upgrade is a visible change in the data.
    Impact is the post-switch cost minus what the mid tier would have cost (no quality gain, spec §8).
    """
    out, base, new = [], [], []
    for r in rows:
        if r.feature_id == "F4" and r.gen_ai_request_model != PT03_BEFORE_MODEL:
            if r.usage_ts.date() < PT03_SWITCH:
                out.append(replace(r, gen_ai_request_model=PT03_BEFORE_MODEL))
                continue
            base.append(replace(r, gen_ai_request_model=PT03_BEFORE_MODEL))
            new.append(r)
        out.append(r)
    label = PatternLabel(
        "PT-03", "silent_model_upgrade", (), "F4", "a-frontier", PT03_SWITCH, WINDOW_END, "model",
        "mid -> frontier, no quality gain", _impact(base, new, PT03_SWITCH, WINDOW_END),
        ("leak_detector", "cost_quality_lab"),
    )
    return out, label


def pt04_cache_collapse(rows: list[TelemetryRow]) -> tuple[list[TelemetryRow], PatternLabel]:
    """F1 cache-hit rate falls from 70% to 15% from 2026-04-07 (system-prompt change)."""
    keep = PT04_HIT_AFTER / PT04_HIT_BASELINE
    out, base, new = [], [], []
    for r in rows:
        if r.feature_id == "F1" and r.usage_ts.date() >= PT04_START:
            r2 = replace(r, gen_ai_usage_cache_read_input_tokens=round(r.gen_ai_usage_cache_read_input_tokens * keep))
            base.append(r)
            new.append(r2)
            r = r2
        out.append(r)
    label = PatternLabel(
        "PT-04", "cache_hit_collapse", (), "F1", None, PT04_START, WINDOW_END, "cache_hit_rate",
        "cache-hit rate 70% -> 15%", _impact(base, new, PT04_START, WINDOW_END), ("leak_detector",),
    )
    return out, label


def apply_pt01_to_pt04(
    rows: list[TelemetryRow], tenants: list[M2Tenant]
) -> tuple[list[TelemetryRow], list[PatternLabel]]:
    """Apply PT-01..PT-04 in order. Labels are computed against the rows each pattern sees, so impacts are
    marginal in this order (PT-04's impact includes PT-01's token growth on the same rows)."""
    labels = []
    rows, lab = pt01_prompt_regression(rows)
    labels.append(lab)
    rows, lab = pt02_retry_loop(rows, tenants)
    labels.append(lab)
    rows, lab = pt03_silent_model_upgrade(rows)
    labels.append(lab)
    rows, lab = pt04_cache_collapse(rows)
    labels.append(lab)
    return rows, labels
