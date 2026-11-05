"""M2-01 step 5: simulated FOCUS shared-infrastructure export (S2, PT-12; D3 share ~15% of AI COGS)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

import pytest

from booncore_sim import m2_infra as infra
from booncore_sim import m2_telemetry as tl
from booncore_sim import m2_tenants as mt
from booncore_sim.m2_catalog import price_on, request_cost_usd

SEED = 42
DEC_2025, MAR_2026, OCT_2026 = 7, 10, 17  # month indexes (0 = May 2025)


@pytest.fixture(scope="module")
def tenants():
    return mt.generate_m2_tenants(SEED)[0]


@pytest.fixture(scope="module")
def telemetry(tenants):
    return {m: tl.generate_month(SEED, tenants, m)[0] for m in (DEC_2025, MAR_2026, OCT_2026)}


def _llm_cost(rows):
    total = 0.0
    for r in rows:
        p = price_on(r.gen_ai_request_model, r.usage_ts.date())
        total += request_cost_usd(
            p, input_tokens=r.gen_ai_usage_input_tokens, cache_read_tokens=r.gen_ai_usage_cache_read_input_tokens,
            output_tokens=r.gen_ai_usage_output_tokens, batch=r.is_batch,
        )
    return total


def test_chunk_alone_is_identical_to_a_rerun(telemetry):
    first = infra.generate_month(SEED, telemetry[OCT_2026], OCT_2026)
    infra.generate_month(SEED, telemetry[DEC_2025], DEC_2025)
    assert infra.generate_month(SEED, telemetry[OCT_2026], OCT_2026) == first
    assert infra.generate_month(SEED + 1, telemetry[OCT_2026], OCT_2026) != first


def test_rejects_telemetry_from_another_month(telemetry):
    with pytest.raises(ValueError):
        infra.generate_month(SEED, telemetry[DEC_2025], OCT_2026)
    with pytest.raises(ValueError):
        infra.generate_month(-1, telemetry[OCT_2026], OCT_2026)


def test_focus_shape_and_tags(telemetry):
    rows = infra.generate_month(SEED, telemetry[OCT_2026], OCT_2026)
    assert rows
    for r in rows:
        assert r.billing_currency == "USD" and r.charge_category == "Usage"
        assert (r.charge_period_end - r.charge_period_start).days == 1
        assert r.billing_period_start == date(2026, 10, 1) and r.billing_period_end == date(2026, 11, 1)
        assert r.list_cost == r.contracted_cost == r.billed_cost == r.effective_cost > 0
        tags = json.loads(r.tags)
        assert tags["x-env"] in ("prod", "staging")
        assert ("x-feature" in tags) == (r.sku_id != "observability")
    assert {r.sku_id for r in rows if "x-feature" not in json.loads(r.tags)} == {"observability"}


def test_idle_staging_gpu_only_in_its_window(telemetry):
    dec = infra.generate_month(SEED, telemetry[DEC_2025], DEC_2025)
    mar = infra.generate_month(SEED, telemetry[MAR_2026], MAR_2026)
    oct_ = infra.generate_month(SEED, telemetry[OCT_2026], OCT_2026)
    gpu = [r for r in dec if r.sku_id == "staging-gpu-idle"]
    assert len(gpu) == 31 and {r.billed_cost for r in gpu} == {infra.IDLE_GPU_USD_PER_DAY}
    assert all(json.loads(r.tags) == {"x-env": "staging", "x-feature": "F2"} for r in gpu)
    assert not [r for r in mar + oct_ if r.sku_id == "staging-gpu-idle"]


def test_oversized_vector_tier_is_a_fixed_daily_charge_throughout(telemetry):
    for m in (DEC_2025, OCT_2026):
        vs = [r for r in infra.generate_month(SEED, telemetry[m], m) if r.sku_id == "vector-storage"]
        assert len(vs) == len(tl.month_days(m))
        assert {r.billed_cost for r in vs} == {infra.OVERSIZED_VECTOR_USD_PER_DAY}


def test_pt12_labels_match_the_charges():
    labels = infra.pt12_labels(date(2025, 5, 1), date(2026, 10, 31))
    gpu = next(x for x in labels if x.component == "idle_staging_gpu")
    vec = next(x for x in labels if x.component == "oversized_vector_tier")
    assert gpu.expected_impact_usd_per_day == infra.IDLE_GPU_USD_PER_DAY
    assert (gpu.start, gpu.end) == (date(2025, 12, 1), date(2026, 2, 28))
    assert vec.expected_impact_usd_per_day == 75.0
    assert all(x.pattern_id == "PT-12" for x in labels)


def test_shared_infra_is_about_15_percent_of_ai_cogs(telemetry):
    """D3 (labeled assumption): infra / (LLM + infra) near 15% at baseline (a month without the idle GPU)."""
    rows = infra.generate_month(SEED, telemetry[OCT_2026], OCT_2026)
    infra_cost = sum(r.billed_cost for r in rows)
    share = infra_cost / (infra_cost + _llm_cost(telemetry[OCT_2026]))
    assert 0.12 <= share <= 0.18, share


def test_variable_lines_track_request_volume(telemetry):
    rows = infra.generate_month(SEED, telemetry[OCT_2026], OCT_2026)
    reqs = defaultdict(int)
    for t in telemetry[OCT_2026]:
        reqs[t.feature_id] += t.request_count
    q = sum(r.consumed_quantity for r in rows if r.sku_id == "compute-f2-agents")
    assert q == reqs["F2"]
    cost = sum(r.billed_cost for r in rows if r.sku_id == "compute-f2-agents")
    assert cost == pytest.approx(q * 0.020, rel=0.02)
