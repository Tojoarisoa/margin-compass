"""M2-01 step 5: shared-infrastructure FOCUS export and PT-12 (spec §8; m2-plan.md M2-01 item 5)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

import pytest

from booncore_sim import m2_infra as inf
from booncore_sim import m2_tenants as mt
from booncore_sim.m2_telemetry import month_days

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


@pytest.fixture(scope="module")
def full(tenants):
    return inf.generate_all(SEED, tenants)


def test_chunk_alone_equals_full_run(tenants, full):
    assert inf.generate_month(SEED, tenants, 9) == [r for r in full if r.charge_period_start.year * 12 + r.charge_period_start.month == 2026 * 12 + 2]
    assert inf.generate_month(SEED + 1, tenants, 9) != inf.generate_month(SEED, tenants, 9)


def test_focus_shape_and_tags(full):
    assert full
    for r in full:
        assert r.billed_cost == r.effective_cost == r.list_cost == r.contracted_cost > 0
        assert r.billing_currency == "USD" and r.synthetic
        assert (r.charge_period_end - r.charge_period_start).days == 1
        assert r.x_env in ("prod", "staging") and r.x_feature in ("F2", "F3", "shared")
        assert r.sub_account_id == f"mc-{r.x_env}"


def test_row_budget_and_window(full):
    days = (mt.WINDOW_END - mt.WINDOW_START).days + 1
    assert len(full) < 10 * days
    assert min(r.charge_period_start for r in full) == mt.WINDOW_START
    assert max(r.charge_period_start for r in full) == mt.WINDOW_END


def test_idle_gpu_only_in_its_window(full):
    gpu = [r for r in full if r.x_env == "staging"]
    assert {r.charge_period_start for r in gpu} == {d for m in range(mt.MONTHS) for d in month_days(m) if inf.GPU_START <= d <= inf.GPU_END}
    assert len(gpu) == 90
    assert all(r.billed_cost == Decimal("50.4000") for r in gpu)


def test_vector_tier_is_fixed_and_oversized(full, tenants):
    tier = [r for r in full if r.charge_description == "Vector store provisioned tier"]
    assert len({r.billed_cost for r in tier}) == 1
    for d in (date(2025, 5, 1), date(2026, 10, 31)):
        n = sum(1 for t in tenants if t.onboarded_on <= d)
        assert inf.vector_right_sized_usd(n) < inf.VECTOR_PROVISIONED_USD


def test_usage_lines_follow_weekly_seasonality(full):
    f2 = {r.charge_period_start: float(r.billed_cost) for r in full if r.resource_id == "mc-prod-f2-agent"}
    wk = [v for d, v in f2.items() if d.weekday() < 5 and date(2026, 5, 1) <= d <= date(2026, 5, 31)]
    we = [v for d, v in f2.items() if d.weekday() >= 5 and date(2026, 5, 1) <= d <= date(2026, 5, 31)]
    assert sum(we) / len(we) < 0.5 * sum(wk) / len(wk)


def test_prod_total_is_a_plausible_share_of_ai_cost(full):
    by_day = defaultdict(float)
    for r in full:
        by_day[r.charge_period_start] += float(r.billed_cost)
    avg = sum(by_day.values()) / len(by_day)
    assert 50 < avg < 600  # well below the ~$11.5k/day AI spend (spec §3)


def test_pt12_labels_match_the_generated_rows(full, tenants):
    gpu_l, vec_l = inf.pt12_labels(tenants)
    gpu = [float(r.billed_cost) for r in full if r.x_env == "staging"]
    assert gpu_l.expected_impact_usd_per_day == pytest.approx(sum(gpu) / len(gpu))
    assert (gpu_l.start_date, gpu_l.end_date) == (date(2025, 12, 1), date(2026, 2, 28))
    assert vec_l.end_date is None and 0 < vec_l.expected_impact_usd_per_day < inf.VECTOR_PROVISIONED_USD
    assert gpu_l.pattern_id == vec_l.pattern_id == "PT-12"
