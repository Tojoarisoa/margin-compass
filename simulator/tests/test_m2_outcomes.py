"""M2-01 step 4: outcomes (aggregates, 10% ticket sample, labeled safety events; spec §3, §4, §12 item 3a)."""

from __future__ import annotations

from collections import Counter

import pytest

from booncore_sim import m2_outcomes as oc
from booncore_sim import m2_tenants as mt

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


@pytest.fixture(scope="module")
def month(tenants):
    return oc.generate_month(SEED, tenants, 17)


def test_chunk_alone_is_identical_to_a_rerun(tenants, month):
    oc.generate_month(SEED, tenants, 3)
    assert oc.generate_month(SEED, tenants, 17) == month
    assert oc.generate_month(SEED + 1, tenants, 17) != month


def test_aggregates_are_internally_consistent(month):
    daily, _ = month
    assert daily
    for r in daily:
        assert r.sev1_tickets + r.sev2_tickets + r.sev3_tickets == r.tickets
        assert r.resolved_remotely <= r.f2_tickets <= r.tickets
        assert r.safety_events_flagged <= r.safety_events_labeled <= r.tickets
        assert r.safety_events_flagged <= r.safety_flags_total
        assert r.tickets <= r.csat_sum <= 5 * r.tickets


def test_ticket_rows_agree_with_aggregates(month):
    daily, tickets = month
    day_of = {(r.tenant_id, r.day): r for r in daily}
    events = Counter((k.tenant_id, k.ticket_date) for k in tickets if k.safety_event_label)
    for key, n in events.items():
        # every labeled event is stored per ticket, so the counts match exactly
        assert day_of[key].safety_events_labeled == n
    assert sum(r.safety_events_labeled for r in daily) == sum(events.values())
    assert len({k.ticket_id for k in tickets}) == len(tickets)
    for k in tickets:
        assert 1 <= k.severity <= 3 and 1 <= k.csat <= 5 and 0.0 <= k.eval_score <= 1.0
        assert not (k.resolved_remotely and not k.used_f2)


def test_sample_is_ten_percent_plus_events(month):
    daily, tickets = month
    total = sum(r.tickets for r in daily)
    events = sum(k.safety_event_label for k in tickets)
    expected = events + oc.TICKET_SAMPLE_RATE * (total - events)
    assert len(tickets) == pytest.approx(expected, rel=0.05)


def test_safety_recall_follows_the_f0_tier_and_is_above_the_floor():
    from booncore_sim.m2_catalog import SAFETY_RECALL_FLOOR, TIER_QUALITY

    assert oc.f0_recall() == TIER_QUALITY["mid"][2] >= SAFETY_RECALL_FLOOR
    # the small tier is the PT-09 downgrade and must breach the floor (spec §4)
    assert TIER_QUALITY["small"][2] < SAFETY_RECALL_FLOOR


def test_full_run_recall_and_remote_share(tenants):
    daily, tickets = oc.generate_all(SEED, tenants)
    assert oc.safety_event_recall(daily) == pytest.approx(oc.f0_recall(), abs=0.003)
    share = sum(r.resolved_remotely for r in daily) / sum(r.f2_tickets for r in daily)
    assert 0.30 <= share <= 0.50  # spec §3
    assert len(daily) + len(tickets) < 1_000_000  # spec §10 outcome budget
    base = [oc.baseline_remote_share(SEED, i) for i in range(len(tenants))]
    assert min(base) >= 0.30 and max(base) <= 0.50


def test_events_follow_segment_base_rates(tenants):
    daily, _ = oc.generate_all(SEED, tenants)
    seg = {t.tenant_id: t.segment for t in tenants}
    tot, ev = Counter(), Counter()
    for r in daily:
        tot[seg[r.tenant_id]] += r.tickets
        ev[seg[r.tenant_id]] += r.safety_events_labeled
    for s, rate in oc.SAFETY_BASE_RATE.items():
        assert ev[s] / tot[s] == pytest.approx(rate, rel=0.15)
