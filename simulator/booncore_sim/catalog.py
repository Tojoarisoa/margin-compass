"""Synthetic price catalog v1 (spec §4). Fictional providers; prices are illustrative, not real."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ModelPrice:
    model_id: str
    provider: str  # gen_ai.provider.name value (ADR-015)
    tier: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    cache_read_usd_per_mtok: float
    batch_discount_pct: float
    baa_covered: bool
    eu_region: bool
    effective_from: date


_CATALOG_START = date(2025, 1, 1)

PRICE_CATALOG_V1: dict[str, ModelPrice] = {
    p.model_id: p
    for p in (
        ModelPrice("a-small", "provider_a", "small", 0.25, 1.25, 0.025, 0.50, True, True, _CATALOG_START),
        ModelPrice("a-mid", "provider_a", "mid", 3.00, 15.00, 0.30, 0.50, True, True, _CATALOG_START),
        ModelPrice("a-frontier", "provider_a", "frontier", 15.00, 75.00, 1.50, 0.50, True, True, _CATALOG_START),
        ModelPrice("b-mid", "provider_b", "mid", 2.00, 10.00, 0.50, 0.50, True, False, _CATALOG_START),
        ModelPrice("c-small", "provider_c", "small", 0.10, 0.40, 0.10, 0.00, False, False, _CATALOG_START),
    )
}


def token_cost_usd(price: ModelPrice, *, input_tokens: int, cache_read_tokens: int, output_tokens: int) -> float:
    """Cost of one usage row. input_tokens includes cached tokens (ADR-015), so they're priced once."""
    uncached = input_tokens - cache_read_tokens
    if uncached < 0:
        raise ValueError("cache_read_tokens cannot exceed input_tokens")
    return (
        uncached * price.input_usd_per_mtok
        + cache_read_tokens * price.cache_read_usd_per_mtok
        + output_tokens * price.output_usd_per_mtok
    ) / 1_000_000
