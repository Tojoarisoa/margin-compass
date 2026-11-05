"""M2-01 step 1: tenants, contracts, SCD2 history (spec §2, §5, §7)."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

import pytest

from booncore_sim import m2_tenants as m


@pytest.fixture(scope="module")
def gen():
    return m.generate_m2_tenants(42)


def test_shape_and_segment_plan_mix(gen):
    tenants, _ = gen
    assert len(tenants) == 400 and len({t.tenant_id for t in tenants}) == 400
    assert Counter(t.plan for t in tenants) == {"starter": 200, "growth": 150, "enterprise": 50}
    assert Counter(t.segment for t in tenants) == {
        "imaging": 60, "in_vitro_diagnostics": 100, "patient_monitoring": 80, "surgical": 60, "other_devices": 100,
    }


def test_arr_totals_are_exact_to_the_cent(gen):
    tenants, _ = gen
    for plan, total in m.PLAN_ARR_TOTAL.items():
        assert sum(t.arr_usd for t in tenants if t.plan == plan) == total
    assert sum(t.arr_usd for t in tenants) == Decimal("24000000.00")
    imaging = sum(t.arr_usd for t in tenants if t.segment == "imaging") / Decimal("24000000")
    assert Decimal("0.33") < imaging < Decimal("0.45")  # spec §2.2: about 40% of ARR


def test_contract_clauses_have_the_spec_counts(gen):
    tenants, _ = gen
    assert sum(t.unlimited_ai for t in tenants) == 60
    assert all(t.plan != "starter" for t in tenants if t.unlimited_ai)
    assert Counter(t.approved_models for t in tenants) == {"any": 260, "baa_only": 120, "provider_a_only": 20}
    assert sum(t.data_residency == "eu_only" for t in tenants) == 80
    assert all(t.allowed_providers == "a" for t in tenants if t.data_residency == "eu_only")
    assert all("c" not in t.allowed_providers for t in tenants if t.approved_models != "any")


def test_unlimited_ai_skews_older(gen):
    tenants, _ = gen
    eligible = [t for t in tenants if t.plan != "starter"]
    old = [t for t in eligible if t.onboarded_on < m.WINDOW_START]
    share_old = sum(t.unlimited_ai for t in old) / len(old)
    share_new = sum(t.unlimited_ai for t in eligible if t.onboarded_on >= m.WINDOW_START) / max(1, len(eligible) - len(old))
    assert share_old > share_new


def test_discounts_and_slas(gen):
    tenants, _ = gen
    ranges = {"starter": (0, 0.05), "growth": (0.05, 0.15), "enterprise": (0.10, 0.25)}
    for t in tenants:
        lo, hi = ranges[t.plan]
        assert Decimal(str(lo)) <= t.discount_pct <= Decimal(str(hi))
        assert t.sev1_share == (0.10 if t.segment == "imaging" else 0.05)
        assert abs(t.sev1_share + t.sev2_share + t.sev3_share - 1) < 1e-9
        assert (t.sla_sev1_minutes, t.sla_sev2_minutes, t.sla_sev3_business_days) == (15, 120, 1)


def test_renewals_spread_across_the_year_and_terms_are_annual(gen):
    tenants, _ = gen
    assert all((t.renewal_date - t.contract_start).days == 365 for t in tenants)
    assert all(m.WINDOW_START <= t.renewal_date < m.WINDOW_START + timedelta(days=365) for t in tenants)
    assert len({t.renewal_date.month for t in tenants}) == 12


def test_growth_is_two_percent_a_month_with_waves():
    counts = m.onboarding_counts()
    assert sum(counts) == 400 and counts[0] == round(400 / 1.02**m.MONTHS)
    waves = {i for i in range(1, m.MONTHS) if m._month_start(i).month in m.WAVE_MONTHS}
    normal = [c for i, c in enumerate(counts) if i > 0 and i not in waves]
    assert all(counts[i] >= 2 * min(normal) - 1 for i in waves)


def test_active_count_matches_cohorts(gen):
    tenants, _ = gen
    assert m.active_tenant_count(tenants, m.WINDOW_START) == m.onboarding_counts()[0]
    assert m.active_tenant_count(tenants, m.WINDOW_END) == 400


def test_scd2_history_is_contiguous_with_one_current_row(gen):
    tenants, history = gen
    by_tenant: dict[str, list] = {}
    for v in history:
        by_tenant.setdefault(v.tenant_id, []).append(v)
    assert set(by_tenant) == {t.tenant_id for t in tenants}
    current = {t.tenant_id: t for t in tenants}
    changed = 0
    for tid, rows in by_tenant.items():
        rows.sort(key=lambda v: v.valid_from)
        assert [v.is_current for v in rows] == [False] * (len(rows) - 1) + [True]
        assert rows[-1].valid_to is None and rows[-1].plan == current[tid].plan
        for a, b in zip(rows, rows[1:], strict=False):
            assert a.valid_to == b.valid_from and a.valid_from < a.valid_to  # no gaps or overlaps
            assert m.PLAN_RANK[a.plan] < m.PLAN_RANK[b.plan]  # upgrades only
        changed += len(rows) > 1
    assert changed == m.UPGRADE_COUNT


def test_deterministic_and_seed_sensitive(gen):
    assert m.generate_m2_tenants(42) == gen
    assert m.generate_m2_tenants(43)[0] != gen[0]
    with pytest.raises(ValueError):
        m.generate_m2_tenants(-1)


def test_window_follows_the_fiscal_year():
    """Owner decision 2026-11-06: start at FY2025's first day; end at the last full month before the project."""
    assert (m.WINDOW_START, m.WINDOW_END, m.MONTHS) == (date(2025, 4, 1), date(2026, 10, 31), 19)
    assert m._month_start(m.MONTHS) == m.WINDOW_END + timedelta(days=1)
    assert (m.WINDOW_END - m.WINDOW_START).days + 1 == 579
    assert m.fiscal_year(date(2025, 4, 1)) == 2025 and m.fiscal_year(date(2026, 3, 31)) == 2025
    assert m.fiscal_year(date(2026, 4, 1)) == 2026 and m.fiscal_year(m.WINDOW_END) == 2026
