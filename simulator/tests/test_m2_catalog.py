"""M2-01 step 2: features and the effective-dated catalog (spec §3, §4)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from booncore_sim import m2_catalog as c


def test_features_match_spec():
    assert list(c.FEATURES) == ["F0", "F1", "F2", "F3", "F4"]
    f = c.FEATURES
    assert (f["F0"].input_tokens_median, f["F0"].output_tokens_median, f["F0"].requests_per_ticket) == (1500, 50, 1)
    assert f["F2"].requests_per_ticket == pytest.approx(2.4) and f["F2"].default_tier == "frontier"
    assert f["F3"].default_tier == "embedding" and f["F3"].output_tokens_median == 0
    assert f["F4"].batch_eligible and not f["F1"].batch_eligible


def test_catalog_has_all_models_and_one_row_in_force_per_day():
    ids = {p.model_id for p in c.PRICE_CATALOG_V2}
    assert ids == {"a-small", "a-mid", "a-frontier", "b-mid", "c-small", "emb-1"}
    for model in ids:
        for d in (date(2025, 5, 1), date(2026, 2, 28), date(2026, 3, 1), date(2026, 10, 31)):
            rows = [p for p in c.PRICE_CATALOG_V2 if p.model_id == model and p.effective_from <= d
                    and (p.effective_to is None or d < p.effective_to)]
            assert len(rows) == 1


def test_b_mid_cut_is_40_percent_on_2026_03_01():
    before, after = c.price_on("b-mid", date(2026, 2, 28)), c.price_on("b-mid", date(2026, 3, 1))
    assert (before.input_usd_per_mtok, before.output_usd_per_mtok) == (2.00, 10.00)
    assert after.input_usd_per_mtok == pytest.approx(1.20) and after.output_usd_per_mtok == pytest.approx(6.00)
    assert after.cache_read_usd_per_mtok == pytest.approx(0.30)
    assert c.price_on("a-mid", date(2026, 3, 1)).input_usd_per_mtok == 3.00  # others unchanged


def test_cached_and_batch_pricing():
    p = c.price_on("a-mid", date(2025, 6, 1))
    full = c.request_cost_usd(p, input_tokens=1_000_000, cache_read_tokens=0, output_tokens=0)
    cached = c.request_cost_usd(p, input_tokens=1_000_000, cache_read_tokens=1_000_000, output_tokens=0)
    assert full == pytest.approx(3.00) and cached == pytest.approx(0.30)  # cached = 10% of input
    assert c.request_cost_usd(p, input_tokens=1_000_000, cache_read_tokens=0, output_tokens=0, batch=True) == pytest.approx(1.50)
    b = c.price_on("b-mid", date(2025, 6, 1))
    assert b.cache_read_usd_per_mtok / b.input_usd_per_mtok == pytest.approx(0.25)


def test_no_cache_or_batch_where_the_catalog_has_none():
    s = c.price_on("c-small", date(2025, 6, 1))
    assert c.request_cost_usd(s, input_tokens=1000, cache_read_tokens=0, output_tokens=100) > 0
    with pytest.raises(ValueError):
        c.request_cost_usd(s, input_tokens=1000, cache_read_tokens=500, output_tokens=0)
    with pytest.raises(ValueError):
        c.request_cost_usd(s, input_tokens=1000, cache_read_tokens=0, output_tokens=0, batch=True)
    with pytest.raises(ValueError):
        c.request_cost_usd(c.price_on("a-small", date(2025, 6, 1)), input_tokens=10, cache_read_tokens=11, output_tokens=0)


def test_embedding_priced_on_input_only():
    e = c.price_on("emb-1", date(2025, 6, 1))
    assert c.request_cost_usd(e, input_tokens=1_000_000, cache_read_tokens=0, output_tokens=0) == pytest.approx(0.02)


def test_safety_recall_floor_flags_small_tier_only():
    assert [t for t, q in c.TIER_QUALITY.items() if q[2] < c.SAFETY_RECALL_FLOOR] == ["small"]


def test_unknown_model_or_date_raises():
    with pytest.raises(KeyError):
        c.price_on("zzz", date(2025, 6, 1))
    with pytest.raises(KeyError):
        c.price_on("a-mid", date(2024, 12, 31))


def test_token_draws_are_deterministic_and_near_medians():
    f = c.FEATURES["F2"]
    a = c.draw_tokens(np.random.default_rng([42, 1]), f, 20000)
    b = c.draw_tokens(np.random.default_rng([42, 1]), f, 20000)
    assert all((x == y).all() for x, y in zip(a, b, strict=True))
    assert np.median(a[0]) == pytest.approx(12000, rel=0.03) and np.median(a[1]) == pytest.approx(600, rel=0.03)
    img = c.draw_tokens(np.random.default_rng([42, 1]), f, 20000, imaging=True)
    assert np.median(img[0]) == pytest.approx(12000 * 1.8, rel=0.03)
    emb = c.draw_tokens(np.random.default_rng(1), c.FEATURES["F3"], 100)
    assert (emb[1] == 0).all() and np.median(emb[0]) == pytest.approx(300, rel=0.15)
