"""M2-01 step 6: PT-01..PT-04 (spec §8)."""

from __future__ import annotations

from datetime import date

import pytest

from booncore_sim import m2_patterns as pt
from booncore_sim import m2_telemetry as tl
from booncore_sim import m2_tenants as mt

SEED = 42


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


def month(tenants, year, mon):
    """Rows for a calendar month, addressed by date so tests don't depend on the window start."""
    i = (year - mt.WINDOW_START.year) * 12 + mon - mt.WINDOW_START.month
    return tl.generate_month(SEED, tenants, i)[0]


def total(rows, pred):
    return sum(r.gen_ai_usage_input_tokens for r in rows if pred(r))


def test_pt01_inflates_f1_input_only_after_start(tenants):
    rows = month(tenants, 2025, 10)
    out, label = pt.pt01_prompt_regression(rows)
    assert label.pattern_id == "PT-01" and label.expected_impact_usd_per_day > 0
    f1 = lambda r: r.feature_id == "F1"  # noqa: E731
    uncached = lambda rs: sum(r.gen_ai_usage_input_tokens - r.gen_ai_usage_cache_read_input_tokens for r in rs if f1(r))  # noqa: E731
    assert uncached(out) == pytest.approx(1.4 * uncached(rows), rel=1e-3)
    assert total(out, lambda r: r.feature_id != "F1") == total(rows, lambda r: r.feature_id != "F1")
    early = month(tenants, 2025, 8)  # before the start
    assert pt.pt01_prompt_regression(early)[0] == early


def test_pt02_one_imaging_tenant_nine_days(tenants):
    rows = month(tenants, 2026, 1)
    out, label = pt.pt02_retry_loop(rows, tenants)
    assert len(label.tenant_ids) == 1
    tenant = next(t for t in tenants if t.tenant_id == label.tenant_ids[0])
    assert tenant.segment == "imaging"
    assert (label.end_date - label.start_date).days == 8 and label.start_date == date(2026, 1, 20)
    changed = [(a, b) for a, b in zip(rows, out, strict=True) if a != b]
    assert changed and all(a.tenant_id == tenant.tenant_id and a.feature_id == "F2" for a, _ in changed)
    assert all(b.retry_count == 4 * a.retry_count for a, b in changed)
    assert label.expected_impact_usd_per_day > 0


def test_pt03_f4_mid_before_frontier_after(tenants):
    for mon, expected in ((9, {"a-mid"}), (11, {"a-mid", "a-frontier"})):  # Sep 2025 before, Nov 2025 across the switch
        out, label = pt.pt03_silent_model_upgrade(month(tenants, 2025, mon))
        assert {r.gen_ai_request_model for r in out if r.feature_id == "F4"} == expected
    assert label.expected_impact_usd_per_day > 0 and label.model == "a-frontier"


def test_pt04_cache_hit_drops_to_15_percent(tenants):
    rows = month(tenants, 2026, 4)
    out, label = pt.pt04_cache_collapse(rows)
    f1 = [(a, b) for a, b in zip(rows, out, strict=True) if a.feature_id == "F1" and a.usage_ts.date() >= date(2026, 4, 7)]
    hit = lambda rs, key: sum(key(r) for r in rs) / sum(r.request_count * 1200 for r in rs)  # noqa: E731
    before = hit([a for a, _ in f1], lambda r: r.gen_ai_usage_cache_read_input_tokens)
    after = hit([b for _, b in f1], lambda r: r.gen_ai_usage_cache_read_input_tokens)
    assert before == pytest.approx(0.70, abs=0.02) and after == pytest.approx(0.15, abs=0.02)
    assert label.expected_impact_usd_per_day > 0


def test_apply_all_labels(tenants):
    rows = month(tenants, 2026, 2) + month(tenants, 2026, 4)
    out, labels = pt.apply_pt01_to_pt04(rows, tenants)
    assert [x.pattern_id for x in labels] == ["PT-01", "PT-02", "PT-03", "PT-04"]
    assert len(out) == len(rows)


def test_pt05_f3_volume_x30_three_days(tenants):
    rows = month(tenants, 2026, 2)
    out, label = pt.pt05_reindex_storm(rows)
    f3 = lambda rs: sum(r.request_count for r in rs if r.feature_id == "F3" and date(2026, 2, 10) <= r.usage_ts.date() <= date(2026, 2, 12))  # noqa: E731
    assert (label.end_date - label.start_date).days == 2 and label.model == "emb-1"
    assert f3(rows) > 0 and f3(out) == 30 * f3(rows)
    assert label.expected_impact_usd_per_day > 0


def test_pt06_pt07_imaging_targets(tenants):
    for mon, fn, n in ((6, pt.pt06_fleet_update_surge, 1), (8, pt.pt07_integration_flood, 3)):  # Jun, Aug 2026
        rows = month(tenants, 2026, mon)
        out, label = fn(rows, tenants)
        assert len(label.tenant_ids) == n
        assert all(next(t for t in tenants if t.tenant_id == x).segment == "imaging" for x in label.tenant_ids)
        changed = [(a, b) for a, b in zip(rows, out, strict=True) if a != b]
        assert changed and all(a.feature_id == "F2" and a.tenant_id in label.tenant_ids for a, _ in changed)
        assert label.expected_impact_usd_per_day > 0
    assert (label.end_date - label.start_date).days == 6


def test_apply_pt05_to_pt07_labels(tenants):
    rows = month(tenants, 2026, 2) + month(tenants, 2026, 6)
    out, labels = pt.apply_pt05_to_pt07(rows, tenants)
    assert [x.pattern_id for x in labels] == ["PT-05", "PT-06", "PT-07"]
    assert len(out) == len(rows)
