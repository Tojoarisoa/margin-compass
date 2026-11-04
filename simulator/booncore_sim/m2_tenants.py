"""M2-01 step 1: 400 tenants, contracts, and SCD2 plan history (spec §2, §5, §7; m2-plan.md M2-01).

Standalone and deterministic: every tenant's draws come from its own stream, `default_rng([seed, index])`,
and the few exact-count clauses (for example 15% "unlimited AI") rank per-tenant draws, so the same
seed gives the same tenants whatever else the simulator does. Not yet wired into the CLI (M1 profile
unchanged). All output is synthetic. Parameters marked (assumption) are labeled inputs (spec §12 item 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .config import PLANS

CENT = Decimal("0.01")
WINDOW_START = date(2025, 5, 1)
WINDOW_END = date(2026, 10, 31)  # 18 months
MONTHS = 18
FINAL_TENANTS = 400
MONTHLY_GROWTH = 0.02  # spec §7
WAVE_MONTHS = (1, 9)  # onboarding waves in Jan and Sep (spec §7)
WAVE_WEIGHT = 2.0  # (assumption) a wave month onboards twice a normal month
AI_ADDON_SHARE = 0.35  # spec §2.1
PLAN_ARR_TOTAL = {"starter": Decimal("3000000.00"), "growth": Decimal("9000000.00"), "enterprise": Decimal("12000000.00")}
PLAN_RANK = {"starter": 0, "growth": 1, "enterprise": 2}
ARR_SIGMA = 0.5  # (assumption) log-normal spread around the plan average

# segment -> (enterprise, growth, starter). Row sums are spec §2.2 (60/100/80/60/100); column sums §2.1 (50/150/200).
SEGMENT_PLAN_MIX: dict[str, tuple[int, int, int]] = {
    "imaging": (30, 25, 5),
    "in_vitro_diagnostics": (15, 60, 25),
    "patient_monitoring": (3, 50, 27),
    "surgical": (2, 15, 43),
    "other_devices": (0, 0, 100),
}
SEV1_SHARE = {"imaging": 0.10}  # others 0.05 (spec §5)
UNLIMITED_AI_COUNT = 60  # 15% of tenants, Growth/Enterprise only
BAA_ONLY_COUNT = 120  # 30%: BAA-covered providers only (no Provider C)
PROVIDER_A_ONLY_COUNT = 20  # 5%
EU_ONLY_COUNT = 80  # 20%: EU-only implies Provider A only
UPGRADE_COUNT = 24  # (assumption) 6% of tenants changed plan during the window
ALLOWED_PROVIDERS = {"any": "a,b,c", "baa_only": "a,b", "provider_a_only": "a"}


@dataclass(frozen=True)
class M2Tenant:
    tenant_id: str
    segment: str
    plan: str  # current plan
    arr_usd: Decimal  # current list ARR, before discount
    ai_addon_arr_usd: Decimal
    discount_pct: Decimal
    unlimited_ai: bool
    approved_models: str  # any | baa_only | provider_a_only
    data_residency: str  # any | eu_only
    allowed_providers: str  # derived from the two clauses above; comma-separated
    sev1_share: float
    sev2_share: float
    sev3_share: float
    sla_sev1_minutes: int
    sla_sev2_minutes: int
    sla_sev3_business_days: int
    fiscal_year_end: str  # MM-DD
    onboarded_on: date
    contract_start: date
    renewal_date: date


@dataclass(frozen=True)
class TenantVersion:
    """One SCD2 row for dim_tenant: valid_from inclusive, valid_to exclusive (None = current)."""

    tenant_id: str
    valid_from: date
    valid_to: date | None
    plan: str
    arr_usd: Decimal
    ai_addon_arr_usd: Decimal
    discount_pct: Decimal
    is_current: bool


def _money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def _month_start(i: int) -> date:
    y, m = divmod(WINDOW_START.month - 1 + i, 12)
    return date(WINDOW_START.year + y, m + 1, 1)


def onboarding_counts() -> list[int]:
    """New tenants per window month (index 0 = the first month's start cohort is pre-existing).

    The tenant count starts at round(400 / 1.02^18) = 280 and grows about 2% a month; Jan and Sep
    count double. Largest-remainder rounding makes the total exactly 400.
    """
    base = round(FINAL_TENANTS / (1 + MONTHLY_GROWTH) ** MONTHS)
    to_add = FINAL_TENANTS - base
    weights = [WAVE_WEIGHT if _month_start(i).month in WAVE_MONTHS else 1.0 for i in range(1, MONTHS)]
    raw = [to_add * w / sum(weights) for w in weights]
    counts = [int(r) for r in raw]
    for j in sorted(range(len(raw)), key=lambda k: (-(raw[k] - counts[k]), k))[: to_add - sum(counts)]:
        counts[j] += 1
    return [base, *counts]  # index 0: tenants active on day one


def _segment_plan_slots() -> list[tuple[str, str]]:
    plans = ("enterprise", "growth", "starter")
    slots = [(seg, plan) for seg, mix in SEGMENT_PLAN_MIX.items() for plan, n in zip(plans, mix, strict=True) for _ in range(n)]
    assert len(slots) == FINAL_TENANTS
    return slots


def generate_m2_tenants(seed: int) -> tuple[list[M2Tenant], list[TenantVersion]]:
    if seed < 0:
        raise ValueError("seed must be non-negative")
    slots = _segment_plan_slots()
    n = len(slots)
    rngs = [np.random.default_rng([seed, i]) for i in range(n)]  # one stream per tenant
    draws = [
        {
            "size": float(r.lognormal(-ARR_SIGMA**2 / 2, ARR_SIGMA)),
            "discount": float(r.uniform()),
            "onboard_rank": float(r.uniform()),
            "legacy": float(r.uniform()),
            "clause": float(r.uniform()),
            "eu": float(r.uniform()),
            "renewal_day": int(r.integers(0, 365)),
            "pre_days": int(r.integers(30, 900)),
            "fy": float(r.uniform()),
            "upgrade": float(r.uniform()),
            "upgrade_day": float(r.uniform()),
        }
        for r in rngs
    ]

    # Onboarding dates: rank tenants by a draw, then give the earliest 280 a pre-window date and the
    # rest the month cohorts above, with a uniform day inside the month.
    counts = onboarding_counts()
    order = sorted(range(n), key=lambda i: (draws[i]["onboard_rank"], i))
    onboarded: dict[int, date] = {}
    pos = 0
    for month_index, c in enumerate(counts):
        for i in order[pos : pos + c]:
            if month_index == 0:
                onboarded[i] = WINDOW_START - timedelta(days=draws[i]["pre_days"])
            else:
                first = _month_start(month_index)
                last = _month_start(month_index + 1) - timedelta(days=1)
                onboarded[i] = first + timedelta(days=int(draws[i]["onboard_rank"] * 1e6) % ((last - first).days + 1))
        pos += c

    # ARR: log-normal around the plan average, rescaled so each plan sums to its spec total.
    arr: dict[int, Decimal] = {}
    for plan, total in PLAN_ARR_TOTAL.items():
        idx = [i for i in range(n) if slots[i][1] == plan]
        raw = sum(draws[i]["size"] for i in idx)
        for i in idx:
            arr[i] = _money(Decimal(str(draws[i]["size"] / raw)) * total)
        biggest = max(idx, key=lambda i: arr[i])
        arr[biggest] += total - sum(arr[i] for i in idx)  # to-the-cent residual

    def pick(candidates: list[int], k: int, key) -> set[int]:
        return set(sorted(candidates, key=key)[:k])

    # Exact-count clauses. "Unlimited AI" skews to older Growth/Enterprise tenants.
    eligible = [i for i in range(n) if slots[i][1] in ("growth", "enterprise")]
    unlimited = pick(eligible, UNLIMITED_AI_COUNT, lambda i: (-((WINDOW_START - onboarded[i]).days / 900 + draws[i]["legacy"]), i))
    by_clause = sorted(range(n), key=lambda i: (draws[i]["clause"], i))
    provider_a_only = set(by_clause[:PROVIDER_A_ONLY_COUNT])
    baa_only = set(by_clause[PROVIDER_A_ONLY_COUNT : PROVIDER_A_ONLY_COUNT + BAA_ONLY_COUNT])
    eu_only = set(sorted(range(n), key=lambda i: (draws[i]["eu"], i))[:EU_ONLY_COUNT])

    tenants: list[M2Tenant] = []
    for i, (segment, plan) in enumerate(slots):
        d = draws[i]
        lo, hi = PLANS[plan].discount_range
        approved = "provider_a_only" if i in provider_a_only else "baa_only" if i in baa_only else "any"
        residency = "eu_only" if i in eu_only else "any"
        providers = "a" if residency == "eu_only" else ALLOWED_PROVIDERS[approved]
        sev1 = SEV1_SHARE.get(segment, 0.05)
        renewal = WINDOW_START + timedelta(days=d["renewal_day"])
        fy = "06-30" if d["fy"] < 0.8 else ("03-31", "09-30", "12-31")[min(2, int((d["fy"] - 0.8) / 0.2 * 3))]
        arr_i = arr[i]
        tenants.append(
            M2Tenant(
                tenant_id=f"bc-t{i + 1:04d}",
                segment=segment,
                plan=plan,
                arr_usd=arr_i,
                ai_addon_arr_usd=_money(arr_i * Decimal(str(AI_ADDON_SHARE))),
                discount_pct=_money(lo + (hi - lo) * d["discount"]),
                unlimited_ai=i in unlimited,
                approved_models=approved,
                data_residency=residency,
                allowed_providers=providers,
                sev1_share=sev1,
                sev2_share=0.25,
                sev3_share=round(1 - sev1 - 0.25, 2),
                sla_sev1_minutes=15,
                sla_sev2_minutes=120,
                sla_sev3_business_days=1,
                fiscal_year_end=fy,
                onboarded_on=onboarded[i],
                contract_start=renewal - timedelta(days=365),
                renewal_date=renewal,
            )
        )

    return tenants, _history(tenants, draws)


def _history(tenants: list[M2Tenant], draws: list[dict]) -> list[TenantVersion]:
    """SCD2 rows: one per tenant, two for the UPGRADE_COUNT tenants that moved up a plan in the window."""
    upgradable = [i for i, t in enumerate(tenants) if t.plan != "starter" and t.onboarded_on <= WINDOW_END - timedelta(days=120)]
    upgraded = set(sorted(upgradable, key=lambda i: (draws[i]["upgrade"], i))[:UPGRADE_COUNT])
    rows: list[TenantVersion] = []
    for i, t in enumerate(tenants):
        if i not in upgraded:
            rows.append(TenantVersion(t.tenant_id, t.onboarded_on, None, t.plan, t.arr_usd, t.ai_addon_arr_usd, t.discount_pct, True))
            continue
        earliest = max(t.onboarded_on, WINDOW_START) + timedelta(days=30)
        span = (WINDOW_END - timedelta(days=30) - earliest).days
        change = earliest + timedelta(days=int(draws[i]["upgrade_day"] * (span + 1)))
        prev_plan = "starter" if t.plan == "growth" else "growth"
        prev_arr = _money(t.arr_usd * Decimal(str(PLANS[prev_plan].avg_arr_usd / PLANS[t.plan].avg_arr_usd)))
        rows.append(TenantVersion(t.tenant_id, t.onboarded_on, change, prev_plan, prev_arr, _money(prev_arr * Decimal(str(AI_ADDON_SHARE))), t.discount_pct, False))
        rows.append(TenantVersion(t.tenant_id, change, None, t.plan, t.arr_usd, t.ai_addon_arr_usd, t.discount_pct, True))
    return rows


def active_tenant_count(tenants: list[M2Tenant], on: date) -> int:
    return sum(1 for t in tenants if t.onboarded_on <= on)
