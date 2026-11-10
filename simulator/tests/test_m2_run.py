"""M2-01 step 9: the composed, patterned run and its chunk determinism."""

from __future__ import annotations

import pytest

from booncore_sim import m2_run as run
from booncore_sim import m2_telemetry as tl
from booncore_sim import m2_tenants as mt

SEED = 42


@pytest.fixture(scope="module")
def full():
    return run.generate_patterned(SEED)


def test_all_pattern_labels_present_and_ordered(full):
    ids = [x.pattern_id for x in full.labels]
    assert ids == [f"PT-{i:02d}" for i in range(1, 15)]
    assert all(x.expected_impact_usd_per_day > 0 for x in full.labels if x.pattern_id != "PT-13")


def test_row_budget_and_event_count(full):
    assert 1_500_000 <= len(full.telemetry) <= 3_000_000
    assert full.renewal_events


def test_month_alone_equals_month_in_full_run(full):
    i = 10  # Feb 2026: PT-05 and PT-02 both land here
    alone, _ = run.patterned_month(SEED, full.tenants, i)
    days = tl.month_days(i)
    lo, hi = days[0], days[-1]
    in_month = [r for r in full.telemetry if lo <= r.usage_ts.date() <= hi]
    assert alone == in_month
    assert mt.WINDOW_START <= lo and hi <= mt.WINDOW_END


def test_approvals_are_opt_in_and_change_only_later_rows(full):
    from datetime import date

    from booncore_sim.m5_effects import Approval

    assert run.generate_patterned(SEED, []).telemetry == full.telemetry
    feature = full.telemetry[0].feature_id
    a = Approval("act-x", "ACT-2", f"{feature}/price", date(2025, 9, 1))
    out = run.generate_patterned(SEED, [a])
    assert len(out.telemetry) == len(full.telemetry)
    assert out.telemetry[0] == full.telemetry[0]
    assert sum(r.request_count for r in out.telemetry) < sum(r.request_count for r in full.telemetry)


def test_month_chunk_with_approvals_equals_full_run(full):
    from datetime import date

    from booncore_sim.m5_effects import Approval

    feature = full.telemetry[0].feature_id
    a = Approval("act-x", "ACT-2", f"{feature}/price", date(2025, 9, 1))
    month = 6
    chunk, _ = run.patterned_month(SEED, full.tenants, month, [a])
    base, _ = run.patterned_month(SEED, full.tenants, month)
    assert chunk != base
    assert sum(r.request_count for r in chunk) < sum(r.request_count for r in base)
    assert run.patterned_month(SEED, full.tenants, month, []) == (base, run.patterned_month(SEED, full.tenants, month)[1])
