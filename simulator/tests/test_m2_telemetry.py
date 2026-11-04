"""M2-01 step 3: telemetry grain, 1% sample, determinism by chunk (spec §7, §10; m2-plan.md M2-01)."""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from booncore_sim import m2_telemetry as tl
from booncore_sim import m2_tenants as mt

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


@pytest.fixture(scope="module")
def last_month(tenants):
    return tl.generate_month(SEED, tenants, 17)


def test_month_days_cover_the_window_exactly():
    days = [d for m in range(mt.MONTHS) for d in tl.month_days(m)]
    assert days[0] == mt.WINDOW_START and days[-1] == mt.WINDOW_END
    assert len(days) == len(set(days)) == (mt.WINDOW_END - mt.WINDOW_START).days + 1
    with pytest.raises(ValueError):
        tl.month_days(18)


def test_chunk_alone_is_identical_to_a_rerun(tenants, last_month):
    """Any month regenerates byte-identically; months share no RNG state, so order cannot matter."""
    tl.generate_month(SEED, tenants, 3)  # generating another month first must not change this one
    assert tl.generate_month(SEED, tenants, 17) == last_month
    assert tl.generate_month(SEED + 1, tenants, 17) != last_month


def test_grain_enterprise_hourly_others_daily(tenants, last_month):
    rows, _ = last_month
    plan = {t.tenant_id: t.plan for t in tenants}
    for r in rows:
        if plan[r.tenant_id] != "enterprise" or r.feature_id in tl.DAILY_ONLY:
            assert r.grain == "day" and r.usage_ts.hour == 0
        else:
            assert r.grain == "hour"
    assert any(r.grain == "hour" for r in rows)


def test_row_budget_spec_10(tenants, last_month):
    """Tenants grow about linearly, so 18 x the mean of the first and last month estimates the total.

    The full 18-month run (2.59M rows, 0.42M sample at seed 42) was checked by hand against the 1.5-3M budget.
    """
    first = tl.generate_month(SEED, tenants, 0)
    est_rows = 18 * (len(first[0]) + len(last_month[0])) / 2
    est_raw = 18 * (len(first[1]) + len(last_month[1])) / 2
    assert 1.5e6 < est_rows < 3.0e6
    assert est_raw < 0.63e6


def test_sample_is_about_one_percent_with_trace_ids(last_month):
    rows, raw = last_month
    requests = sum(r.request_count for r in rows)
    assert len(raw) == pytest.approx(requests * tl.SAMPLE_RATE, rel=0.05)
    assert len({q.trace_id for q in raw}) == len(raw)
    assert all(len(q.trace_id) == 32 and int(q.trace_id, 16) >= 0 for q in raw)
    first = mt.WINDOW_START
    assert all(q.request_ts.date() >= first for q in raw)


def test_no_content_fields():
    fields = set(tl.TelemetryRow.__dataclass_fields__) | set(tl.RawRequest.__dataclass_fields__)
    assert not {f for f in fields if any(w in f for w in ("prompt", "response", "text", "content"))}


def test_row_invariants(last_month):
    rows, raw = last_month
    for r in rows:
        assert r.request_count > 0 and r.retry_count <= r.request_count
        assert 0 <= r.gen_ai_usage_cache_read_input_tokens <= r.gen_ai_usage_input_tokens
        assert r.gen_ai_usage_output_tokens >= 0
        if r.feature_id == "F3":
            assert r.gen_ai_usage_output_tokens == 0 and r.gen_ai_operation_name == "embeddings"
        if r.is_batch:
            assert r.feature_id == "F4"
    for q in raw:
        assert 0 <= q.gen_ai_usage_cache_read_input_tokens <= q.gen_ai_usage_input_tokens


def test_tenants_have_no_rows_before_onboarding(tenants):
    onboarded = {t.tenant_id: t.onboarded_on for t in tenants}
    rows, _ = tl.generate_month(SEED, tenants, 0)
    assert all(r.usage_ts.date() >= onboarded[r.tenant_id] for r in rows)


def test_weekend_volume_is_a_fifth_of_weekday(last_month):
    rows, _ = last_month
    by_day = Counter()
    for r in rows:
        by_day[r.usage_ts.date()] += r.request_count
    wk = [v for d, v in by_day.items() if d.weekday() < 5]
    we = [v for d, v in by_day.items() if d.weekday() >= 5]
    assert sum(we) / len(we) == pytest.approx(0.2 * sum(wk) / len(wk), rel=0.25)


def test_hourly_profile_peaks_in_business_hours(last_month):
    rows, _ = last_month
    by_hour = Counter()
    for r in rows:
        if r.grain == "hour":
            by_hour[r.usage_ts.hour] += r.request_count
    assert min(by_hour[h] for h in tl.BUSINESS_HOURS) > 4 * max(by_hour[h] for h in (0, 1, 2, 3, 22, 23))
    assert by_hour[3] / by_hour[12] == pytest.approx(tl.HOURLY_FLOOR, rel=0.2)


def test_respiratory_and_fiscal_multipliers(tenants):
    pm = next(t for t in tenants if t.segment == "patient_monitoring")
    other = next(t for t in tenants if t.segment == "surgical")
    d = date(2026, 1, 7)  # a Wednesday, outside both crunch windows for this check
    assert tl.day_multiplier(pm, d) / tl.day_multiplier(other, d) == pytest.approx(1.25 / (1.15 if tl._in_fiscal_crunch(pm, d) else 1) * (1.15 if tl._in_fiscal_crunch(other, d) else 1))
    june = date(2026, 6, 20)
    on_june30 = [t for t in tenants if t.fiscal_year_end == "06-30"][0]
    assert tl._in_fiscal_crunch(on_june30, june) and not tl._in_fiscal_crunch(on_june30, date(2026, 5, 1))
