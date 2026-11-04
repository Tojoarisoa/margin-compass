"""M2-01 step 2: AI features F0-F4 and the effective-dated model price catalog (spec §3, §4; m2-plan.md M2-01).

Standalone and not yet wired into the CLI (M1 output unchanged). All prices and token medians are
synthetic and illustrative; parameters marked (assumption) are labeled inputs (spec §12 item 4).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

import numpy as np

CATALOG_START = date(2025, 1, 1)
B_MID_CUT_DATE = date(2026, 3, 1)  # spec §4: scheduled change in the window
B_MID_CUT_PCT = 0.40
TOKEN_SIGMA = 0.4  # (assumption) per-request log-normal spread, same as M1
IMAGING_F2_FACTOR = 1.8  # spec §3


@dataclass(frozen=True)
class Feature:
    feature_id: str
    name: str
    requests_per_ticket: float  # expected requests per ticket (F2: 40% x 6 steps; F4: per closed ticket)
    input_tokens_median: float
    output_tokens_median: float
    default_tier: str
    batch_eligible: bool = False  # F4, except Sev-1 cases (spec §3)
    cacheable_prefix_tokens: float = 0.0  # (assumption) cacheable system prompt per request


FEATURES: dict[str, Feature] = {
    f.feature_id: f
    for f in (
        Feature("F0", "Safety Screening", 1.0, 1500, 50, "mid"),
        Feature("F1", "Reply Copilot", 3.0, 2000, 300, "mid", cacheable_prefix_tokens=1200),
        Feature("F2", "Device Troubleshooting Agent", 0.4 * 6, 12000, 600, "frontier", cacheable_prefix_tokens=3000),
        Feature("F3", "Service Knowledge Search", 2.0, 300, 0, "embedding"),
        Feature("F4", "Case & Complaint Summaries", 1.0, 6000, 400, "frontier", batch_eligible=True),
    )
}


@dataclass(frozen=True)
class ModelPrice:
    model_id: str
    provider: str  # gen_ai.provider.name value (ADR-015)
    tier: str  # small | mid | frontier | embedding
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cache_read_usd_per_mtok: float | None  # None = no caching
    batch_discount_pct: float | None  # None = no batch pricing
    baa_covered: bool
    eu_region: bool
    effective_from: date
    effective_to: date | None = None  # exclusive; None = open


def _base() -> tuple[ModelPrice, ...]:
    s = CATALOG_START
    return (
        ModelPrice("a-small", "provider_a", "small", 0.25, 1.25, 0.025, 0.50, True, True, s),
        ModelPrice("a-mid", "provider_a", "mid", 3.00, 15.00, 0.30, 0.50, True, True, s),
        ModelPrice("a-frontier", "provider_a", "frontier", 15.00, 75.00, 1.50, 0.50, True, True, s),
        ModelPrice("b-mid", "provider_b", "mid", 2.00, 10.00, 0.50, 0.50, True, False, s),
        ModelPrice("c-small", "provider_c", "small", 0.10, 0.40, None, None, False, False, s),
        ModelPrice("emb-1", "provider_a", "embedding", 0.02, 0.0, None, None, True, True, s),
    )


def _build_catalog() -> tuple[ModelPrice, ...]:
    rows: list[ModelPrice] = []
    for p in _base():
        if p.model_id == "b-mid":
            f = 1 - B_MID_CUT_PCT
            rows.append(replace(p, effective_to=B_MID_CUT_DATE))
            rows.append(
                replace(
                    p,
                    input_usd_per_mtok=round(p.input_usd_per_mtok * f, 6),
                    output_usd_per_mtok=round(p.output_usd_per_mtok * f, 6),
                    cache_read_usd_per_mtok=round(p.cache_read_usd_per_mtok * f, 6),
                    effective_from=B_MID_CUT_DATE,
                )
            )
        else:
            rows.append(p)
    return tuple(rows)


PRICE_CATALOG_V2: tuple[ModelPrice, ...] = _build_catalog()

# Quality by tier (spec §4, assumption): (F1/F4 quality, F2 remote-resolution multiplier, F0 safety recall).
TIER_QUALITY: dict[str, tuple[float, float, float]] = {
    "frontier": (1.00, 1.00, 0.996),
    "mid": (0.99, 0.90, 0.993),
    "small": (0.96, 0.70, 0.975),
}
SAFETY_RECALL_FLOOR = 0.99  # KPI-08(b)


def price_on(model_id: str, day: date) -> ModelPrice:
    """The catalog row in force for `model_id` on `day` (effective_from inclusive, effective_to exclusive)."""
    for p in PRICE_CATALOG_V2:
        if p.model_id == model_id and p.effective_from <= day and (p.effective_to is None or day < p.effective_to):
            return p
    raise KeyError(f"no price for {model_id} on {day}")


def request_cost_usd(
    price: ModelPrice, *, input_tokens: int, cache_read_tokens: int, output_tokens: int, batch: bool = False
) -> float:
    """Cost of one usage row. input_tokens includes cached tokens (ADR-015), so they're priced once.

    Batch applies the model's discount to the whole row; models without batch pricing reject batch=True.
    """
    if cache_read_tokens < 0 or cache_read_tokens > input_tokens:
        raise ValueError("cache_read_tokens must be within 0..input_tokens")
    if cache_read_tokens and price.cache_read_usd_per_mtok is None:
        raise ValueError(f"{price.model_id} has no cached-input pricing")
    cached_rate = price.cache_read_usd_per_mtok or 0.0
    cost = (
        (input_tokens - cache_read_tokens) * price.input_usd_per_mtok
        + cache_read_tokens * cached_rate
        + output_tokens * price.output_usd_per_mtok
    ) / 1_000_000
    if batch:
        if price.batch_discount_pct is None:
            raise ValueError(f"{price.model_id} has no batch pricing")
        cost *= 1 - price.batch_discount_pct
    return cost


def draw_tokens(rng: np.random.Generator, feature: Feature, n: int, *, imaging: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """n requests' (input, output) tokens: log-normal around the spec §3 medians (F2 imaging x1.8)."""
    scale = IMAGING_F2_FACTOR if (imaging and feature.feature_id == "F2") else 1.0
    inp = np.maximum(1, np.rint(rng.lognormal(np.log(feature.input_tokens_median * scale), TOKEN_SIGMA, n))).astype(np.int64)
    if feature.output_tokens_median == 0:
        return inp, np.zeros(n, dtype=np.int64)
    out = np.maximum(1, np.rint(rng.lognormal(np.log(feature.output_tokens_median), TOKEN_SIGMA, n))).astype(np.int64)
    return inp, out
