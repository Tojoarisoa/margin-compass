"""M2-03 statistical check: volume drift warns on a real jump and stays quiet on PT-13 seasonality."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from booncore_sim.m2_telemetry import generate_month
from booncore_sim.m2_tenants import generate_m2_tenants
from mc_pipelines.drift import ratio_drift, volume_drift


def _weekly(days: int, start: date = date(2026, 1, 5)) -> dict[date, float]:
    return {start + timedelta(d): 1000.0 * (0.4 if (start + timedelta(d)).weekday() >= 5 else 1.0) for d in range(days)}


def test_weekly_cycle_alone_does_not_warn():
    assert volume_drift(_weekly(70)) == []


def test_a_tripled_day_and_a_dropout_warn():
    s = _weekly(70)
    spike, drop = date(2026, 2, 10), date(2026, 2, 17)
    s[spike] *= 3
    s[drop] *= 0.1
    found = {w.day: w.ratio for w in volume_drift(s)}
    assert found[spike] > 2 and found[drop] < 0.5


def test_no_baseline_no_warning():
    assert volume_drift({date(2026, 1, 5): 5.0, date(2026, 1, 12): 500.0}) == []


def test_pt13_guard_baseline_seasonality_never_alerts():
    # Jan-Apr 2026 baseline telemetry (months 9..12) spans the fiscal-year-end crunch and growth (PT-13).
    tenants = generate_m2_tenants(42)[0]
    daily: dict[date, float] = defaultdict(float)
    for month in (9, 10, 11, 12):
        rows, _ = generate_month(42, tenants, month)
        for r in rows:
            daily[r.usage_ts.date()] += r.request_count
    assert len(daily) > 100
    assert volume_drift(daily) == []


def test_ratio_drift_warns_on_a_shifted_ratio_only():
    start = date(2026, 1, 5)
    den = {start + timedelta(d): 1000.0 * (0.4 if (start + timedelta(d)).weekday() >= 5 else 1.0) for d in range(60)}
    num = {d: v * 800 for d, v in den.items()}  # 800 tokens per request every day, weekends included
    assert ratio_drift(num, den) == []
    shifted = date(2026, 2, 20)
    num[shifted] *= 2.5  # tokens per request jumps with the same volume
    assert [w.day for w in ratio_drift(num, den)] == [shifted]


def test_ratio_drift_needs_a_baseline():
    d = date(2026, 1, 5)
    assert ratio_drift({d: 9.0}, {d: 1.0}) == []


def test_pt13_guard_tokens_per_request_baseline_never_alerts():
    tenants = generate_m2_tenants(42)[0]
    tokens: dict[date, float] = defaultdict(float)
    requests: dict[date, float] = defaultdict(float)
    for month in (9, 10, 11, 12):
        rows, _ = generate_month(42, tenants, month)
        for r in rows:
            day = r.usage_ts.date()
            tokens[day] += r.gen_ai_usage_input_tokens + r.gen_ai_usage_output_tokens
            requests[day] += r.request_count
    assert ratio_drift(tokens, requests) == []
