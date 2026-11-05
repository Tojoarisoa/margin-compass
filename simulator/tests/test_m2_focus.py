"""M2-01 step 5: simulated FOCUS 1.2 shared-infra export (spec §8 PT-12, D3 calibration)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from booncore_sim import m2_focus as fx
from booncore_sim import m2_tenants as mt

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


@pytest.fixture(scope="module")
def rows(tenants):
    return fx.generate_all(SEED, tenants)


def test_deterministic(tenants):
    d = date(2026, 3, 10)
    n = fx.active_tenants(tenants, d)
    assert fx.generate_day(SEED, n, d) == fx.generate_day(SEED, n, d)
    assert fx.generate_day(SEED, n, d) != fx.generate_day(SEED + 1, n, d)


def test_focus_shape(rows):
    for r in rows[:50]:
        assert r.charge_category == "Usage" and r.billing_currency == "USD"
        assert r.billed_cost == r.effective_cost == r.list_cost >= 0
        assert r.charge_period_end - r.charge_period_start == timedelta(days=1)
        assert r.billing_period_start.day == 1 and r.billing_period_end > r.charge_period_start
        assert r.tag_feature and r.tag_env in ("prod", "staging")
    assert {r.charge_period_start for r in rows} == {mt.WINDOW_START + timedelta(days=i) for i in range((mt.WINDOW_END - mt.WINDOW_START).days + 1)}


def test_idle_gpu_only_in_window(rows):
    gpu = [r for r in rows if r.service_name == "Idle GPU Instance"]
    days = {r.charge_period_start for r in gpu}
    assert min(days) == fx.GPU_IDLE_START and max(days) == fx.GPU_IDLE_END and len(gpu) == 90
    assert all(r.tag_env == "staging" and r.billed_cost == fx.GPU_IDLE_USD_PER_DAY for r in gpu)


def test_oversized_vector_tier_all_window(rows):
    xl = [r for r in rows if r.sku_id == "vector-tier-xl"]
    assert len(xl) == (mt.WINDOW_END - mt.WINDOW_START).days + 1 and all(r.billed_cost == fx.VECTOR_OVERSIZE_USD_PER_DAY for r in xl)


def test_waste_ground_truth(rows):
    day = date(2026, 1, 15)
    by_day = sum(r.billed_cost for r in rows if r.charge_period_start == day and (r.sku_id in ("vector-tier-xl", "gpu-hour")))
    assert by_day == pytest.approx(fx.pt12_waste_usd_per_day(day))
    assert fx.pt12_waste_usd_per_day(date(2026, 4, 1)) == fx.VECTOR_OVERSIZE_USD_PER_DAY


def test_share_of_ai_cogs_near_15_percent(rows):
    # D3: shared infra ~ 15% of AI COGS. Seed-42 LLM cost over the 19-month window is $3.58M (measured 2026-11-06).
    shared = sum(r.billed_cost for r in rows)
    share = shared / (shared + 3_579_745)
    assert 0.12 <= share <= 0.18, share


def test_features_tagged(rows):
    assert {r.tag_feature for r in rows} == {"F2", "F3", "F4", "shared"}
