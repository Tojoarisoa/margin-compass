"""Daily LLM telemetry for F1 (spec §3) with injected pattern PT-01 (spec §8).

Rows are pre-aggregated to day × tenant × feature × model (PLAN.md §7.5). Column names follow the
OpenTelemetry GenAI attributes pinned in ADR-015, in snake_case. No prompt or response content
exists anywhere (AGENTS.md rule 16).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .catalog import PRICE_CATALOG_V1, token_cost_usd
from .config import SimConfig
from .tenants import Tenant


@dataclass(frozen=True)
class UsageRow:
    usage_date: date
    tenant_id: str
    feature_id: str
    gen_ai_provider_name: str
    gen_ai_request_model: str
    gen_ai_operation_name: str
    request_count: int
    gen_ai_usage_input_tokens: int  # includes cached tokens (ADR-015)
    gen_ai_usage_output_tokens: int
    gen_ai_usage_cache_read_input_tokens: int
    retry_count: int
    # Ground truth for labels only; not written to the telemetry file.
    counterfactual_input_tokens: int


def _mean_of_lognormal(median: float, sigma: float) -> float:
    return median * float(np.exp(sigma**2 / 2))


def generate_f1_telemetry(cfg: SimConfig, tenants: list[Tenant], rng: np.random.Generator) -> list[UsageRow]:
    mean_in = _mean_of_lognormal(cfg.f1_input_tokens_median, cfg.token_sigma)
    mean_out = _mean_of_lognormal(cfg.f1_output_tokens_median, cfg.token_sigma)
    small, mid = cfg.models
    rows: list[UsageRow] = []
    for day_index in range(cfg.days):
        day = cfg.start + timedelta(days=day_index)
        weekday_factor = 1.0 if day.weekday() < 5 else cfg.weekend_factor
        regression = 1.0 + cfg.pt01_magnitude if ("PT-01" in cfg.patterns and day >= cfg.pt01_start) else 1.0
        for t in tenants:
            plan = cfg.plans[t.plan]
            tickets = int(rng.poisson(plan.tickets_per_weekday * t.size_factor * weekday_factor))
            requests = int(rng.poisson(cfg.f1_requests_per_ticket * tickets)) if tickets else 0
            small_requests = int(rng.binomial(requests, t.small_tier_share)) if requests else 0
            for model, n in ((small, small_requests), (mid, requests - small_requests)):
                if n == 0:
                    continue
                # Daily averages of n log-normal draws: noise shrinks with volume.
                in_noise = float(rng.normal(1.0, cfg.token_sigma / np.sqrt(n)))
                out_noise = float(rng.normal(1.0, cfg.token_sigma / np.sqrt(n)))
                base_input = max(n, round(n * mean_in * in_noise))
                cache_read = min(base_input, int(rng.binomial(n, cfg.cache_hit_rate)) * int(cfg.f1_cached_prefix_tokens))
                # PT-01: the release grows the prompt after the cached prefix, so the extra tokens are uncached.
                actual_input = round(base_input * regression)
                price = PRICE_CATALOG_V1[model]
                rows.append(
                    UsageRow(
                        usage_date=day,
                        tenant_id=t.tenant_id,
                        feature_id="F1",
                        gen_ai_provider_name=price.provider,
                        gen_ai_request_model=model,
                        gen_ai_operation_name="chat",
                        request_count=n,
                        gen_ai_usage_input_tokens=actual_input,
                        gen_ai_usage_output_tokens=max(n, round(n * mean_out * out_noise)),
                        gen_ai_usage_cache_read_input_tokens=cache_read,
                        retry_count=int(rng.binomial(n, cfg.retry_rate)),
                        counterfactual_input_tokens=base_input,
                    )
                )
    return rows


def pt01_label(cfg: SimConfig, rows: list[UsageRow]) -> dict:
    """Ground truth for PT-01: average $/day of extra cost versus the counterfactual (no regression)."""
    affected_days = (cfg.end - cfg.pt01_start).days + 1
    extra_usd = 0.0
    for r in rows:
        if r.usage_date < cfg.pt01_start:
            continue
        price = PRICE_CATALOG_V1[r.gen_ai_request_model]
        common = {"cache_read_tokens": r.gen_ai_usage_cache_read_input_tokens, "output_tokens": r.gen_ai_usage_output_tokens}
        extra_usd += token_cost_usd(price, input_tokens=r.gen_ai_usage_input_tokens, **common) - token_cost_usd(
            price, input_tokens=r.counterfactual_input_tokens, **common
        )
    return {
        "pattern_id": "PT-01",
        "pattern_type": "prompt_regression",
        "feature_id": "F1",
        "tenant_scope": "all",
        "model_scope": "all",
        "start_date": cfg.pt01_start,
        "end_date": None,  # ongoing at simulation end
        "affected_metric": "input_tokens_per_request",
        "magnitude": cfg.pt01_magnitude,
        "expected_impact_usd_per_day": round(extra_usd / affected_days, 2),
        "detectable_by": "leak_detector",
    }
