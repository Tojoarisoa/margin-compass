"""Tenant and contract generation (spec §2, §5), thinned for M1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .config import SimConfig

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    segment: str
    plan: str
    arr_usd: Decimal
    ai_addon_arr_usd: Decimal
    discount_pct: Decimal
    unlimited_ai: bool
    contract_start: date
    renewal_date: date
    size_factor: float  # tenant ARR relative to its plan average; scales ticket volume
    small_tier_share: float


def generate_tenants(cfg: SimConfig, rng: np.random.Generator) -> list[Tenant]:
    tenants: list[Tenant] = []
    n = 0
    for (segment, plan), count in sorted(cfg.tenant_mix.items()):
        spec = cfg.plans[plan]
        for _ in range(count):
            n += 1
            size = float(rng.lognormal(mean=-cfg.arr_sigma**2 / 2, sigma=cfg.arr_sigma))  # mean 1.0
            arr = Decimal(str(spec.avg_arr_usd * size)).quantize(CENT, ROUND_HALF_UP)
            lo, hi = spec.discount_range
            discount = Decimal(str(rng.uniform(lo, hi))).quantize(CENT, ROUND_HALF_UP)
            renewal = cfg.start + timedelta(days=int(rng.integers(30, 366)))
            tenants.append(
                Tenant(
                    tenant_id=f"bc-t{n:04d}",
                    segment=segment,
                    plan=plan,
                    arr_usd=arr,
                    ai_addon_arr_usd=(arr * Decimal(str(cfg.ai_addon_share))).quantize(CENT, ROUND_HALF_UP),
                    discount_pct=discount,
                    unlimited_ai=False,
                    contract_start=renewal - timedelta(days=365),
                    renewal_date=renewal,
                    size_factor=size,
                    small_tier_share=spec.small_tier_share,
                )
            )

    # Legacy "unlimited AI" clauses sit on Growth/Enterprise tenants (spec §5).
    eligible = [i for i, t in enumerate(tenants) if t.plan in ("growth", "enterprise")]
    chosen = set(rng.choice(eligible, size=min(cfg.unlimited_ai_tenants, len(eligible)), replace=False).tolist())
    return [
        Tenant(**{**t.__dict__, "unlimited_ai": i in chosen}) for i, t in enumerate(tenants)
    ]
