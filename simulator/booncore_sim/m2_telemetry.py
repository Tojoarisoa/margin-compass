"""M2-01 step 3: telemetry grain (spec §7, §10, §12 item 2; m2-plan.md M2-01).

Enterprise tenants get hourly rows, every other plan daily rows, plus a 1% raw request sample with trace
IDs. This is the baseline only (weekly, respiratory-season and fiscal-year-end effects, PT-13); injected
patterns come in a later step. Standalone and not wired into the CLI, so M1 output is unchanged.

Determinism: a month's output depends only on (seed, month, tenant) through one RNG stream per
tenant-month, so any month can be regenerated alone and match the full run byte for byte.
No prompt or response content exists (AGENTS.md rule 16). All output is synthetic. Parameters marked
(assumption) are labeled inputs (spec §12 item 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np

from .config import PLANS
from .m2_catalog import FEATURES, TOKEN_SIGMA, Feature, draw_tokens, price_on
from .m2_tenants import MONTHS, WINDOW_END, M2Tenant, _month_start

STREAM = 3  # RNG namespace: tenants use [seed, i]; telemetry uses [seed, STREAM, month, i]
WEEKEND_FACTOR = 0.20  # spec §7
RESPIRATORY_BOOST = 0.25  # spec §7: Nov-Feb, patient monitoring and in-vitro diagnostics
RESPIRATORY_SEGMENTS = ("patient_monitoring", "in_vitro_diagnostics")
FISCAL_BOOST = 0.15  # spec §7: final 3 weeks of the tenant's fiscal year
FISCAL_DAYS = 21
HOURLY_FLOOR = 0.15  # spec §7: overnight floor
BUSINESS_HOURS = range(8, 18)  # (assumption) peak 08:00-17:59 UTC
SAMPLE_RATE = 0.01  # spec §10: 1% raw request sample
RETRY_RATE = 0.02  # (assumption) same as M1
CACHE_HIT = {"F1": 0.70, "F2": 0.50}  # (assumption) F1 70% is the PT-04 baseline
IMAGING = "imaging"

# feature -> model; F1 is split by the plan's small-tier share (spec §2.1).
ROUTING = {"F0": "a-mid", "F2": "a-frontier", "F3": "emb-1", "F4": "a-frontier"}
# (assumption) F4 summaries run as an end-of-day batch job and the F3 vector service reports daily, so
# every tenant gets daily rows for them. This keeps Enterprise hourly telemetry inside the spec §10 row budget.
DAILY_ONLY = ("F3", "F4")
OPERATION = {"F3": "embeddings"}  # everything else is chat


@dataclass(frozen=True)
class TelemetryRow:
    usage_ts: datetime  # start of the hour (hourly grain) or midnight (daily grain), UTC
    grain: str  # hour | day
    tenant_id: str
    feature_id: str
    gen_ai_provider_name: str
    gen_ai_request_model: str
    gen_ai_operation_name: str
    is_batch: bool
    request_count: int
    gen_ai_usage_input_tokens: int  # includes cached tokens (ADR-015)
    gen_ai_usage_output_tokens: int
    gen_ai_usage_cache_read_input_tokens: int
    retry_count: int


@dataclass(frozen=True)
class RawRequest:
    """One sampled request. Metadata and token counts only."""

    trace_id: str  # 32 hex chars
    request_ts: datetime
    tenant_id: str
    feature_id: str
    gen_ai_request_model: str
    is_batch: bool
    gen_ai_usage_input_tokens: int
    gen_ai_usage_output_tokens: int
    gen_ai_usage_cache_read_input_tokens: int


def month_days(month_index: int) -> list[date]:
    if not 0 <= month_index < MONTHS:
        raise ValueError(f"month_index must be 0..{MONTHS - 1}")
    start = _month_start(month_index)
    end = min(_month_start(month_index + 1) - timedelta(days=1), WINDOW_END)
    return [start + timedelta(days=k) for k in range((end - start).days + 1)]


def hourly_weights() -> np.ndarray:
    w = np.full(24, HOURLY_FLOOR)
    w[list(BUSINESS_HOURS)] = 1.0
    return w / w.sum()


def _in_fiscal_crunch(t: M2Tenant, day: date) -> bool:
    month, dom = (int(x) for x in t.fiscal_year_end.split("-"))
    for year in (day.year, day.year + 1):
        try:
            fy_end = date(year, month, dom)
        except ValueError:  # Feb 29 in a non-leap year
            fy_end = date(year, month, dom - 1)
        if fy_end - timedelta(days=FISCAL_DAYS) < day <= fy_end:
            return True
    return False


def day_multiplier(t: M2Tenant, day: date) -> float:
    m = WEEKEND_FACTOR if day.weekday() >= 5 else 1.0
    if day.month in (11, 12, 1, 2) and t.segment in RESPIRATORY_SEGMENTS:
        m *= 1 + RESPIRATORY_BOOST
    if _in_fiscal_crunch(t, day):
        m *= 1 + FISCAL_BOOST
    return m


def _size_factor(t: M2Tenant) -> float:
    return float(t.arr_usd) / PLANS[t.plan].avg_arr_usd


def _models_for(feature: Feature, t: M2Tenant) -> list[tuple[str, float]]:
    """(model, share of the feature's requests). Provider A models are allowed for every tenant (spec §5)."""
    if feature.feature_id == "F1":
        small = PLANS[t.plan].small_tier_share
        return [("a-small", small), ("a-mid", 1 - small)]
    return [(ROUTING[feature.feature_id], 1.0)]


def _mean_of_lognormal(median: float) -> float:
    return median * float(np.exp(TOKEN_SIGMA**2 / 2))


def _row(ts, grain, t, f, model, batch, n, rng, imaging) -> TelemetryRow:
    scale = 1.8 if (imaging and f.feature_id == "F2") else 1.0
    # Averages of n log-normal draws: noise shrinks with volume (same approach as M1).
    in_noise = float(rng.normal(1.0, TOKEN_SIGMA / np.sqrt(n)))
    out_noise = float(rng.normal(1.0, TOKEN_SIGMA / np.sqrt(n)))
    total_in = max(n, round(n * _mean_of_lognormal(f.input_tokens_median * scale) * in_noise))
    total_out = 0 if f.output_tokens_median == 0 else max(n, round(n * _mean_of_lognormal(f.output_tokens_median) * out_noise))
    cache = 0
    if f.cacheable_prefix_tokens and f.feature_id in CACHE_HIT:
        cache = min(total_in, int(rng.binomial(n, CACHE_HIT[f.feature_id])) * int(f.cacheable_prefix_tokens))
    price = price_on(model, ts.date())
    return TelemetryRow(
        ts, grain, t.tenant_id, f.feature_id, price.provider, model,
        OPERATION.get(f.feature_id, "chat"), batch, n, total_in, total_out, cache, int(rng.binomial(n, RETRY_RATE)),
    )


def _sample(rng, ts, hour_weights, t, f, model, batch, n, imaging) -> list[RawRequest]:
    k = int(rng.binomial(n, SAMPLE_RATE))
    if k == 0:
        return []
    inp, out = draw_tokens(rng, f, k, imaging=imaging)
    hours = [ts.hour] * k if hour_weights is None else rng.choice(24, size=k, p=hour_weights)
    minutes = rng.integers(0, 3600, size=k)
    ids = rng.integers(0, 2**63, size=(k, 2), dtype=np.uint64)
    reqs = []
    for j in range(k):
        cache = 0
        if f.cacheable_prefix_tokens and f.feature_id in CACHE_HIT and rng.uniform() < CACHE_HIT[f.feature_id]:
            cache = min(int(inp[j]), int(f.cacheable_prefix_tokens))
        reqs.append(
            RawRequest(
                f"{int(ids[j, 0]):016x}{int(ids[j, 1]):016x}",
                datetime(ts.year, ts.month, ts.day, int(hours[j])) + timedelta(seconds=int(minutes[j])),
                t.tenant_id, f.feature_id, model, batch, int(inp[j]), int(out[j]), cache,
            )
        )
    return reqs


def generate_month(seed: int, tenants: list[M2Tenant], month_index: int) -> tuple[list[TelemetryRow], list[RawRequest]]:
    """Telemetry rows and the 1% raw sample for one window month (spec §10)."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    days = month_days(month_index)
    hw = hourly_weights()
    rows: list[TelemetryRow] = []
    raw: list[RawRequest] = []
    for i, t in enumerate(tenants):
        rng = np.random.default_rng([seed, STREAM, month_index, i])
        hourly = t.plan == "enterprise"
        imaging = t.segment == IMAGING
        base = PLANS[t.plan].tickets_per_weekday * _size_factor(t)
        for day in days:
            if day < t.onboarded_on:
                continue
            tickets = int(rng.poisson(base * day_multiplier(t, day)))
            if tickets == 0:
                continue
            midnight = datetime(day.year, day.month, day.day)
            for f in FEATURES.values():
                total = int(rng.poisson(f.requests_per_ticket * tickets))
                if total == 0:
                    continue
                for model, share in _models_for(f, t):
                    n_model = int(rng.binomial(total, share)) if share < 1.0 else total
                    # F4 is batch-eligible except Sev-1 cases (spec §3).
                    splits = [(False, n_model)]
                    if f.batch_eligible and n_model:
                        n_sev1 = int(rng.binomial(n_model, t.sev1_share))
                        splits = [(True, n_model - n_sev1), (False, n_sev1)]
                    for batch, n in splits:
                        if n == 0:
                            continue
                        if hourly and f.feature_id not in DAILY_ONLY:
                            per_hour = rng.multinomial(n, hw)
                            for h in range(24):
                                if per_hour[h]:
                                    ts = midnight + timedelta(hours=h)
                                    rows.append(_row(ts, "hour", t, f, model, batch, int(per_hour[h]), rng, imaging))
                                    raw += _sample(rng, ts, None, t, f, model, batch, int(per_hour[h]), imaging)
                        else:
                            rows.append(_row(midnight, "day", t, f, model, batch, n, rng, imaging))
                            raw += _sample(rng, midnight, hw, t, f, model, batch, n, imaging)
    return rows, raw


def generate_all(seed: int, tenants: list[M2Tenant]) -> tuple[list[TelemetryRow], list[RawRequest]]:
    rows: list[TelemetryRow] = []
    raw: list[RawRequest] = []
    for m in range(MONTHS):
        r, s = generate_month(seed, tenants, m)
        rows += r
        raw += s
    return rows, raw


