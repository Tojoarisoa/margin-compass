"""M6-02 step 1: model drift checks for the AI COGS forecaster (PLAN.md §6.2 Stage 4 "retrain on drift", §13.2).

Two deterministic checks per feature, both warnings that recommend a retrain, never errors:

- **Error drift:** the one-week-ahead seasonal-naive error (WAPE) over the last 28 days, against the same error over
  the 112 days before. It needs no stored forecasts, so it works on any history. Growth and slow seasonal moves shift
  level, not this error, so they stay quiet (the PT-13 idea from the data drift checks).
- **Forecast accuracy drift:** forecasts from an earlier run (`fct_forecasts`, P50) against the actuals that have
  arrived since, compared with the WAPE the model's backtest recorded. Skipped until at least 7 target days have
  actuals.

All inputs and outputs are synthetic and labeled so.
"""

from __future__ import annotations

from datetime import date

RECENT_DAYS = 28
REFERENCE_DAYS = 112
SEASON = 7
ERROR_RATIO = 2.0  # recent error at least twice the reference error
ERROR_FLOOR = 0.05  # and at least 5 WAPE points worse, so a near-perfect reference doesn't alert on noise
MIN_REALIZED_DAYS = 7


def _wape(actual: list[float], predicted: list[float]) -> float | None:
    total = sum(abs(a) for a in actual)
    if total <= 0:
        return None
    return sum(abs(a - p) for a, p in zip(actual, predicted, strict=True)) / total


def naive_error(values: list[float], start: int, end: int) -> float | None:
    """WAPE of predicting each day from the same weekday a week earlier, for days [start, end)."""
    idx = [i for i in range(max(start, SEASON), end)]
    if not idx:
        return None
    return _wape([values[i] for i in idx], [values[i - SEASON] for i in idx])


def error_drift(values: list[float], ratio: float = ERROR_RATIO, floor: float = ERROR_FLOOR) -> dict | None:
    """Recent vs reference one-week-ahead error, or None when the history is shorter than both windows."""
    n = len(values)
    if n < RECENT_DAYS + REFERENCE_DAYS + SEASON:
        return None
    recent = naive_error(values, n - RECENT_DAYS, n)
    reference = naive_error(values, n - RECENT_DAYS - REFERENCE_DAYS, n - RECENT_DAYS)
    if recent is None or reference is None:
        return None
    drift = recent >= ratio * reference and recent - reference >= floor
    return {"recent_wape": round(recent, 6), "reference_wape": round(reference, 6), "drift": drift}


def forecast_accuracy_drift(forecasts: list[dict], actuals: dict[date, float], reference_wape: float | None,
                            ratio: float = ERROR_RATIO, floor: float = ERROR_FLOOR) -> dict | None:
    """Earlier P50 forecasts (`target_date`, `p50_usd`) vs actuals that have arrived. None until enough days exist
    or without a reference WAPE."""
    pairs = sorted((f["target_date"], float(f["p50_usd"])) for f in forecasts if f["target_date"] in actuals)
    if len(pairs) < MIN_REALIZED_DAYS or reference_wape is None:
        return None
    live = _wape([actuals[d] for d, _ in pairs], [p for _, p in pairs])
    if live is None:
        return None
    drift = live >= ratio * reference_wape and live - reference_wape >= floor
    return {"live_wape": round(live, 6), "reference_wape": round(reference_wape, 6), "days": len(pairs), "drift": drift}


def forecaster_drift(series: dict[str, list[float]], days: list[date], prior_forecasts: list[dict] | None = None,
                     backtest_wape: dict[str, float] | None = None) -> dict:
    """Drift report for every feature. `retrain` is true when any check on any feature drifted."""
    by_feature = {}
    for feature, values in sorted(series.items()):
        actuals = dict(zip(days, values, strict=True))
        mine = [f for f in prior_forecasts or [] if f["feature_id"] == feature]
        by_feature[feature] = {
            "error_drift": error_drift(values),
            "forecast_accuracy_drift": forecast_accuracy_drift(mine, actuals, (backtest_wape or {}).get(feature)),
        }
    drifted = sorted(f for f, r in by_feature.items() if any(c and c["drift"] for c in r.values()))
    return {"synthetic": True, "window_end": days[-1].isoformat() if days else None, "by_feature": by_feature,
            "drifted": drifted, "retrain": bool(drifted)}
