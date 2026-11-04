"""M2-01 step 2: AI features F0-F4 and the effective-dated model catalog (spec §3, §4; m2-plan.md M2-01).

Standalone and deterministic; not yet wired into the CLI (M1 output unchanged). All prices and token
distributions are synthetic. Parameters marked (assumption) are labeled inputs (spec §12 item 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .catalog import PRICE_CATALOG_V1, ModelPrice

B_MID_CUT_DATE = date(2026, 3, 1)  # spec §4
B_MID_CUT_PCT = 0.40
TOKEN_SIGMA = 0.4  # (assumption) per-request log-normal spread, as in M1
IMAGING_F2_FACTOR = 1.8  # spec §3


@dataclass(frozen=True)
class Feature:
    feature_id: str
    name: str
    requests_per_ticket: float  # expected requests per ticket (F2: 40% x 6 steps)
    input_median: int
    output_median: int
    default_tier: str
    batch_eligible: bool = False
    cacheable_prefix_tokens: int = 0  # (assumption) system-prompt prefix that can hit the cache


FEATURES: dict[str, Feature] = {
    f.feature_id: f
    for f in (
        Feature("F0", "Safety Screening", 1.0, 1500, 50, "mid", cacheable_prefix_tokens=800),
        Feature("F1", "Reply Copilot", 3.0, 2000, 300, "mid", cacheable_prefix_tokens=1200),
        Feature("F2", "Device Troubleshooting Agent", 0.4 * 6, 12000, 600, "frontier", cacheable_prefix_tokens=2000),
        Feature("F3", "Service Knowledge Search", 2.0, 300, 0, "embedding"),
        Feature("F4", "Case & Complaint Summaries", 1.0, 6000, 400, "frontier", batch_eligible=True),
    )
}

# Quality by tier (spec §4, assumption): F1/F4 quality, F2 remote-resolution multiplier, F0 safety recall.
TIER_QUALITY: dict[str, dict[str, float]] = {
    "frontier": {"f1_f4_quality": 1.00, "f2_resolution_mult": 1.00, "f0_recall": 0.996},
    "mid": {"f1_f4_quality": 0.99, "f2_resolution_mult": 0.90, "f0_recall": 0.993},
    "small": {"f1_f4_quality": 0.96, "f2_resolution_mult": 0.70, "f0_recall": 0.975},
}
F0_RECALL_FLOOR = 0.99  # spec §4: small tier is below it

_CATALOG_START = date(2025, 1, 1)
_EMB = ModelPrice("emb-1", "provider_a", "embedding", 0.02, 0.0, 0.0, 0.0, True, True, _CATALOG_START)


def _b_mid_cut() -> ModelPrice:
    b = PRICE_CATALOG_V1["b-mid"]
    f = 1 - B_MID_CUT_PCT
    return ModelPrice(
        b.model_id, b.provider, b.tier, round(b.input_usd_per_mtok * f, 6), round(b.output_usd_per_mtok * f, 6),
        round(b.cache_read_usd_per_mtok * f, 6), b.batch_discount_pct, b.baa_covered, b.eu_region, B_MID_CUT_DATE,
    )


# Every version of every model, effective-dated. The latest version with effective_from <= day applies.
CATALOG_VERSIONS: tuple[ModelPrice, ...] = (*PRICE_CATALOG_V1.values(), _EMB, _b_mid_cut())


def price_on(model_id: str, day: date) -> ModelPrice:
    """The catalog entry in force for `model_id` on `day`."""
    versions = [p for p in CATALOG_VERSIONS if p.model_id == model_id and p.effective_from <= day]
    if not versions:
        raise KeyError(f"no price for {model_id} on {day}")
    return max(versions, key=lambda p: p.effective_from)


def request_cost_usd(
    price: ModelPrice, *, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0, batch: bool = False
) -> float:
    """Cost of one request. input_tokens includes cached tokens (ADR-015). Batch applies the model's
    batch discount to the whole request; models without a batch discount are never discounted."""
    uncached = input_tokens - cache_read_tokens
    if uncached < 0 or cache_read_tokens < 0:
        raise ValueError("cache_read_tokens must be within 0..input_tokens")
    usd = (
        uncached * price.input_usd_per_mtok
        + cache_read_tokens * price.cache_read_usd_per_mtok
        + output_tokens * price.output_usd_per_mtok
    ) / 1_000_000
    return usd * (1 - price.batch_discount_pct) if batch else usd


def draw_tokens(rng: np.random.Generator, feature_id: str, n: int, *, imaging: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """n (input, output) token draws: log-normal around the spec §3 medians. F2 imaging tenants get x1.8.
    F3 is an embedding call, so its output is always 0."""
    f = FEATURES[feature_id]
    scale = IMAGING_F2_FACTOR if (feature_id == "F2" and imaging) else 1.0
    inp = np.maximum(1, np.rint(rng.lognormal(np.log(f.input_median * scale), TOKEN_SIGMA, n))).astype(np.int64)
    if f.output_median == 0:
        return inp, np.zeros(n, dtype=np.int64)
    out = np.maximum(1, np.rint(rng.lognormal(np.log(f.output_median * scale), TOKEN_SIGMA, n))).astype(np.int64)
    return inp, out


def tier_model(tier: str, allowed_providers: str = "a,b,c") -> str:
    """Cheapest-listed default model for a tier among allowed providers (spec §5 constraints)."""
    preference = {"small": ("a-small", "c-small"), "mid": ("a-mid", "b-mid"), "frontier": ("a-frontier",), "embedding": ("emb-1",)}
    allowed = set(allowed_providers.split(","))
    for m in preference[tier]:
        if m == "emb-1" or m[0] in allowed:
            return m
    raise ValueError(f"no {tier} model for providers {allowed_providers}")
