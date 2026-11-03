"""Simulation profiles. Parameters marked (assumption) come from docs/booncore-spec.md and are
labeled assumptions, not facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class PlanSpec:
    avg_arr_usd: float
    tickets_per_weekday: float
    discount_range: tuple[float, float]  # (assumption)
    small_tier_share: float  # share of F1 requests routed to the small tier (assumption)


@dataclass(frozen=True)
class SimConfig:
    profile: str
    start: date
    days: int
    seed: int
    # (segment, plan) -> number of tenants
    tenant_mix: dict[tuple[str, str], int]
    plans: dict[str, PlanSpec]
    features: tuple[str, ...] = ("F1",)
    models: tuple[str, ...] = ("a-small", "a-mid")
    patterns: tuple[str, ...] = ("PT-01",)
    ai_addon_share: float = 0.35  # spec §2.1
    arr_sigma: float = 0.25  # log-normal spread of tenant ARR around the plan average (assumption)
    weekend_factor: float = 0.20  # spec §7
    f1_requests_per_ticket: float = 3.0  # spec §3
    f1_input_tokens_median: float = 2000.0  # spec §3 (assumption)
    f1_output_tokens_median: float = 300.0  # spec §3 (assumption)
    token_sigma: float = 0.4  # per-request log-normal spread (assumption)
    f1_cached_prefix_tokens: float = 1200.0  # cacheable system prompt per request (assumption)
    cache_hit_rate: float = 0.70  # spec §8 PT-04 baseline
    retry_rate: float = 0.01  # (assumption)
    unlimited_ai_tenants: int = 3  # spec §5: about 15% of tenants
    pt01_start: date = date(2025, 9, 15)  # spec §8
    pt01_magnitude: float = 0.40  # +40% input tokens per request on F1
    extra: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError("days must be positive")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if not set(p for _, p in self.tenant_mix) <= set(self.plans):
            raise ValueError("tenant_mix references an unknown plan")
        if self.patterns and not (self.start <= self.pt01_start <= self.end):
            raise ValueError("PT-01 start must fall inside the simulation window")

    @property
    def end(self) -> date:
        """Last simulated day (inclusive)."""
        return self.start + timedelta(days=self.days - 1)

    @property
    def tenant_count(self) -> int:
        return sum(self.tenant_mix.values())


# Spec §2.1 plan averages and weekday ticket volumes.
PLANS = {
    "starter": PlanSpec(avg_arr_usd=15_000, tickets_per_weekday=5, discount_range=(0.00, 0.05), small_tier_share=0.30),
    "growth": PlanSpec(avg_arr_usd=60_000, tickets_per_weekday=25, discount_range=(0.05, 0.15), small_tier_share=0.15),
    "enterprise": PlanSpec(avg_arr_usd=240_000, tickets_per_weekday=150, discount_range=(0.10, 0.25), small_tier_share=0.05),
}

# Spec §11 (M1-01): 20 tenants, 10 imaging and 10 other, mixed plans.
M1 = SimConfig(
    profile="m1",
    start=date(2025, 8, 1),
    days=90,  # through 2025-10-29
    seed=42,
    tenant_mix={
        ("imaging", "enterprise"): 4,
        ("imaging", "growth"): 4,
        ("imaging", "starter"): 2,
        ("in_vitro_diagnostics", "enterprise"): 1,
        ("in_vitro_diagnostics", "growth"): 2,
        ("patient_monitoring", "growth"): 2,
        ("patient_monitoring", "starter"): 1,
        ("surgical", "starter"): 2,
        ("other_devices", "starter"): 2,
    },
    plans=PLANS,
)

PROFILES = {"m1": M1}
