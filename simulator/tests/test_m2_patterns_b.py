"""M2-01 step 8: PT-08..PT-14 (spec §8, §9)."""

from __future__ import annotations

import pytest

from booncore_sim import m2_outcomes as oc
from booncore_sim import m2_patterns_b as pb
from booncore_sim import m2_telemetry as tl
from booncore_sim import m2_tenants as mt

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


@pytest.fixture(scope="module")
def rows(tenants):
    i = (2026 - mt.WINDOW_START.year) * 12 + 4 - mt.WINDOW_START.month  # Apr 2026, after the b-mid cut
    return tl.generate_month(SEED, tenants, i)[0]


def test_pt08_blocked_tenants_cannot_use_provider_b(tenants, rows):
    label = pb.pt08_blocked_cheaper_option(rows, tenants)
    by_id = {t.tenant_id: t for t in tenants}
    assert label.tenant_ids and all("b" not in by_id[x].allowed_providers for x in label.tenant_ids)
    assert label.expected_impact_usd_per_day > 0 and label.model == "b-mid"


def test_pt09_proposal_fails_the_recall_floor(tenants):
    i = (2026 - mt.WINDOW_START.year) * 12 + 9 - mt.WINDOW_START.month  # Sep 2026, inside the proposal window
    label = pb.pt09_safety_downgrade_proposal(tl.generate_month(SEED, tenants, i)[0])
    assert label.feature == "F0" and "97.5%" in label.magnitude and label.expected_impact_usd_per_day > 0


def test_pt10_twelve_unlimited_tenants_triple(tenants, rows):
    out, label = pb.pt10_power_tenants(rows, tenants)
    by_id = {t.tenant_id: t for t in tenants}
    assert len(label.tenant_ids) == 12 and all(by_id[x].unlimited_ai for x in label.tenant_ids)
    changed = [(a, b) for a, b in zip(rows, out, strict=True) if a != b]
    assert changed and all(a.tenant_id in label.tenant_ids and b.request_count == 3 * a.request_count for a, b in changed)
    assert label.expected_impact_usd_per_day > 0


def test_pt11_only_after_the_cut_and_for_allowed_tenants(tenants, rows):
    label = pb.pt11_unused_cheaper_option(rows, tenants)
    by_id = {t.tenant_id: t for t in tenants}
    assert all("b" in by_id[x].allowed_providers for x in label.tenant_ids)
    assert label.start_date.isoformat() == "2026-03-01" and label.expected_impact_usd_per_day > 0
    pt08 = pb.pt08_blocked_cheaper_option(rows, tenants)
    assert not set(pt08.tenant_ids) & set(label.tenant_ids)


def test_pt13_is_not_a_leak():
    label = pb.pt13_seasonality_and_growth()
    assert label.expected_impact_usd_per_day == 0.0 and label.detectable_by == ("forecaster",)


def test_pt14_events_carry_true_probabilities_and_are_deterministic(tenants):
    outcomes = oc.generate_all(SEED, tenants)[0]
    events, label = pb.pt14_churn_events(SEED, tenants, outcomes)
    assert events and label.expected_impact_usd_per_day > 0
    assert all(0 < e.p_churn < 1 and 0 <= e.p_downgrade < 1 for e in events)
    assert all(e.outcome in {"renewed", "downgraded", "churned"} for e in events)
    assert all(e.p_downgrade == 0 for e in events if next(t for t in tenants if t.tenant_id == e.tenant_id).plan == "starter")
    assert pb.pt14_churn_events(SEED, tenants, outcomes)[0] == events


def test_churn_probability_is_monotone_in_price_and_csat():
    rest = (4.0, 2.0, 0.5, 0.01)
    assert pb.renewal_probs(pb.CHURN_BETA, 8.0, *rest) > pb.renewal_probs(pb.CHURN_BETA, 0.0, *rest)
    assert pb.renewal_probs(pb.CHURN_BETA, 3.0, 2.0, 2.0, 0.5, 0.01) > pb.renewal_probs(pb.CHURN_BETA, 3.0, 4.5, 2.0, 0.5, 0.01)
