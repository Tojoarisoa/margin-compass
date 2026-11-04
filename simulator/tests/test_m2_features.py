"""M2-01 step 2: features and effective-dated catalog (spec §3, §4)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from booncore_sim import m2_features as f


def test_features_match_spec_table():
    assert set(f.FEATURES) == {"F0", "F1", "F2", "F3", "F4"}
    assert f.FEATURES["F2"].requests_per_ticket == pytest.approx(2.4)
    assert [f.FEATURES[k].default_tier for k in ("F0", "F1", "F2", "F3", "F4")] == ["mid", "mid", "frontier", "embedding", "frontier"]
    assert f.FEATURES["F4"].batch_eligible and not f.FEATURES["F1"].batch_eligible


def test_b_mid_price_cut_is_effective_dated():
    before, after = f.price_on("b-mid", date(2026, 2, 28)), f.price_on("b-mid", date(2026, 3, 1))
    assert before.input_usd_per_mtok == 2.00 and before.output_usd_per_mtok == 10.00
    assert after.input_usd_per_mtok == pytest.approx(1.20) and after.output_usd_per_mtok == pytest.approx(6.00)
    assert f.price_on("a-mid", date(2026, 6, 1)).input_usd_per_mtok == 3.00
    with pytest.raises(KeyError):
        f.price_on("a-mid", date(2024, 12, 31))


def test_embedding_model_priced_input_only():
    p = f.price_on("emb-1", date(2025, 6, 1))
    assert p.tier == "embedding" and f.request_cost_usd(p, input_tokens=1_000_000, output_tokens=0) == pytest.approx(0.02)


def test_cached_and_batch_pricing():
    p = f.price_on("a-mid", date(2025, 6, 1))
    base = f.request_cost_usd(p, input_tokens=1_000_000, output_tokens=100_000)
    assert base == pytest.approx(3.0 + 1.5)
    cached = f.request_cost_usd(p, input_tokens=1_000_000, output_tokens=0, cache_read_tokens=500_000)
    assert cached == pytest.approx(0.5 * 3.0 + 0.5 * 0.30)
    assert f.request_cost_usd(p, input_tokens=1_000_000, output_tokens=100_000, batch=True) == pytest.approx(base / 2)
    c = f.price_on("c-small", date(2025, 6, 1))  # no batch discount, no cache discount
    assert f.request_cost_usd(c, input_tokens=1000, output_tokens=0, batch=True) == f.request_cost_usd(c, input_tokens=1000, output_tokens=0)
    with pytest.raises(ValueError):
        f.request_cost_usd(p, input_tokens=10, output_tokens=0, cache_read_tokens=11)


def test_token_draws_follow_medians_and_are_deterministic():
    a = f.draw_tokens(np.random.default_rng([42, 1]), "F2", 20000)
    b = f.draw_tokens(np.random.default_rng([42, 1]), "F2", 20000)
    assert (a[0] == b[0]).all() and (a[1] == b[1]).all()
    assert np.median(a[0]) == pytest.approx(12000, rel=0.03) and np.median(a[1]) == pytest.approx(600, rel=0.03)
    img = f.draw_tokens(np.random.default_rng([42, 1]), "F2", 20000, imaging=True)
    assert np.median(img[0]) == pytest.approx(12000 * 1.8, rel=0.03)
    f1_img = f.draw_tokens(np.random.default_rng([42, 1]), "F1", 20000, imaging=True)
    assert np.median(f1_img[0]) == pytest.approx(2000, rel=0.03)  # x1.8 is F2 only
    emb_in, emb_out = f.draw_tokens(np.random.default_rng(1), "F3", 100)
    assert (emb_out == 0).all() and emb_in.min() >= 1


def test_quality_floor_and_tier_routing_respects_constraints():
    assert f.TIER_QUALITY["small"]["f0_recall"] < f.F0_RECALL_FLOOR <= f.TIER_QUALITY["mid"]["f0_recall"]
    assert f.tier_model("mid") == "a-mid"
    assert f.tier_model("small", "a,b") == "a-small"
    assert f.tier_model("mid", "b") == "b-mid"
    with pytest.raises(ValueError):
        f.tier_model("frontier", "b,c")
