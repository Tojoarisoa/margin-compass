"""Rolling-origin, multi-step backtests for AI COGS forecasters (M3-01, EV-02).

Every origin refits on data up to the origin only (no look-ahead), forecasts `horizon` days, and is
scored on those days: WAPE of the P50, mean pinball loss over P10/P50/P90, and P10-P90 coverage.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import numpy as np

from . import ets, gbm, seasonal_naive

QUANTILES = (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))

# A forecaster maps (dates, values, horizon) of history to rows with p10 / p50 / p90.
Forecaster = Callable[[list[date], list[float], int], list[dict]]


def seasonal_naive_forecaster(dates: list[date], values: list[float], horizon: int) -> list[dict]:
    return seasonal_naive.fit(dates, values).forecast(horizon)


def ets_forecaster(dates: list[date], values: list[float], horizon: int) -> list[dict]:
    return ets.fit(dates, values).forecast(horizon)


def gbm_forecaster(dates: list[date], values: list[float], horizon: int) -> list[dict]:
    return gbm.fit(dates, values).forecast(horizon)


BASELINES: dict[str, Forecaster] = {"seasonal_naive": seasonal_naive_forecaster, "ets": ets_forecaster}
CANDIDATES: dict[str, Forecaster] = {**BASELINES, "gbm": gbm_forecaster}


def pinball(actual: float, pred: float, q: float) -> float:
    diff = actual - pred
    return max(q * diff, (q - 1) * diff)


def rolling_origin(
    forecaster: Forecaster, values: list[float], horizon: int = 30, origins: int = 4, step: int = 7,
    min_history: int = 28, start: date = date(2000, 1, 1),
) -> dict:
    """Score `forecaster` at `origins` origins spaced `step` days apart, the last ending at the series end."""
    y = list(values)
    dates = [start + timedelta(days=i) for i in range(len(y))]
    first = len(y) - horizon - step * (origins - 1)
    if first < min_history:
        raise ValueError("not enough history for the requested origins and horizon")
    abs_err = abs_act = pin = 0.0
    covered = n = 0
    for k in range(origins):
        cut = first + k * step
        rows = forecaster(dates[:cut], y[:cut], horizon)
        for h, row in enumerate(rows):
            actual = y[cut + h]
            abs_err += abs(actual - row["p50"])
            abs_act += abs(actual)
            pin += float(np.mean([pinball(actual, row[name], q) for name, q in QUANTILES]))
            covered += int(row["p10"] <= actual <= row["p90"])
            n += 1
    return {
        "method": f"rolling-origin, {horizon}-day horizon, {origins} origins every {step} days",
        "points": n,
        "wape": round(abs_err / abs_act, 6) if abs_act else None,
        "pinball": round(pin / n, 6),
        "p10_p90_coverage": round(covered / n, 6),
    }


def compare(values: list[float], forecasters: dict[str, Forecaster] | None = None, **kwargs) -> dict[str, dict]:
    """Backtest every forecaster on the same series and origins."""
    return {name: rolling_origin(fn, values, **kwargs) for name, fn in (forecasters or BASELINES).items()}


def ev02_gate(multi_step: dict[str, dict[str, dict] | None], candidate: str = "gbm") -> dict:
    """EV-02: the candidate passes only if, on every scored feature, it beats both baselines on WAPE
    and pinball loss. Features with too little history (None) are not scored; with none scored, no pass."""
    scored, failures = 0, []
    for feature, scores in sorted(multi_step.items()):
        if not scores or candidate not in scores:
            continue
        scored += 1
        for name, score in scores.items():
            if name == candidate:
                continue
            for metric in ("wape", "pinball"):
                mine, theirs = scores[candidate][metric], score[metric]
                if mine is None or theirs is None or mine >= theirs:
                    failures.append(f"{feature}: {candidate} {metric} {mine} does not beat {name} {theirs}")
    return {"candidate": candidate, "features_scored": scored, "passed": scored > 0 and not failures, "failures": failures}
