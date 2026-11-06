"""Volume drift check for daily series (M2-03 statistical checks, PLAN.md §6.2 Stage 3).

A day is compared with the mean of the same weekday in the previous 4 weeks, so the weekly cycle is part of the
expectation, and the slow seasonal moves (respiratory season, fiscal-year-end crunch, growth: PT-13) stay inside
the band. PT-13 is the guard: it must never alert on the seasonal baseline. Findings are warnings, not errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

WEEKS_BACK = 4
LOW, HIGH = 0.5, 2.0


@dataclass(frozen=True)
class DriftWarning:
    day: date
    value: float
    expected: float
    ratio: float


def volume_drift(series: dict[date, float], low: float = LOW, high: float = HIGH) -> list[DriftWarning]:
    """Days whose value is outside [low, high] times the mean of the same weekday in the 4 weeks before.

    Days without all 4 prior same-weekday values, or whose expectation is 0, are skipped (no baseline yet).
    """
    out = []
    for day in sorted(series):
        prior = [series.get(day - timedelta(weeks=w)) for w in range(1, WEEKS_BACK + 1)]
        if any(p is None for p in prior):
            continue
        expected = sum(prior) / WEEKS_BACK
        if expected <= 0:
            continue
        ratio = series[day] / expected
        if ratio < low or ratio > high:
            out.append(DriftWarning(day, series[day], expected, ratio))
    return out


PRIOR_DAYS = 28
MIN_PRIOR_DAYS = 14
BAND = 0.5


def ratio_drift(numerator: dict[date, float], denominator: dict[date, float], band: float = BAND) -> list[DriftWarning]:
    """Distribution drift of a ratio of sums (tokens per request, cost per request, ...).

    Each day's ratio is compared with the ratio of the sums over the previous 28 days (at least 14 of them present),
    never with an average of daily ratios. Warns when it moves more than `band` (50%) either way. The slow
    seasonal and growth moves of PT-13 stay inside the band.
    """
    out = []
    for day in sorted(denominator):
        if denominator[day] <= 0 or day not in numerator:
            continue
        prior = [day - timedelta(days=d) for d in range(1, PRIOR_DAYS + 1)]
        prior = [d for d in prior if denominator.get(d, 0) > 0 and d in numerator]
        if len(prior) < MIN_PRIOR_DAYS:
            continue
        expected = sum(numerator[d] for d in prior) / sum(denominator[d] for d in prior)
        if expected <= 0:
            continue
        value = numerator[day] / denominator[day]
        ratio = value / expected
        if abs(ratio - 1) > band:
            out.append(DriftWarning(day, value, expected, ratio))
    return out


def m2_drift_checks(gold: Path) -> list[dict]:
    """Run the drift checks on the M2 gold marts. Each result is a warning (never an error) tagged statistical."""
    import duckdb

    daily = duckdb.sql(
        f"select cost_date, sum(requests), sum(input_tokens + output_tokens), sum(llm_cost_usd) "
        f"from '{gold}/fct_unit_cost.parquet' group by all order by 1").fetchall()
    requests = {r[0]: float(r[1]) for r in daily}
    tokens = {r[0]: float(r[2]) for r in daily}
    cost = {r[0]: float(r[3]) for r in daily}
    checks = {
        "volume_requests": volume_drift(requests),
        "ratio_tokens_per_request": ratio_drift(tokens, requests),
        "ratio_cost_per_request": ratio_drift(cost, requests),
    }
    return [
        {"check": name, "category": "statistical", "severity": "warn", "day": w.day.isoformat(),
         "value": round(w.value, 6), "expected": round(w.expected, 6), "ratio": round(w.ratio, 4)}
        for name, found in checks.items() for w in found
    ]


def write_m2_scorecard(gold: Path, run_id: str) -> dict:
    """gold/_quality/m2_scorecard.json: the M2 statistical warnings, for PG-8 (M2-03.4). Synthetic data."""
    import json

    warnings = m2_drift_checks(gold)
    card = {"run_id": run_id, "checks": ["volume_requests", "ratio_tokens_per_request", "ratio_cost_per_request"],
            "warnings": warnings, "synthetic": True}
    out = gold / "_quality"
    out.mkdir(parents=True, exist_ok=True)
    (out / "m2_scorecard.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n")
    return card
