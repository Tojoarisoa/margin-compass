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
