"""Seasonal-naive AI COGS forecaster (M1-04 stub; also the KPI-07 baseline).

Point forecast: each future day takes the last observed value for the same weekday (season = 7).
Interval: P10/P90 scale the point forecast by the empirical 10th/90th percentiles of week-over-week
ratios y[t] / y[t-7] seen in training. Simple, transparent, and deterministic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np

SEASON = 7


@dataclass(frozen=True)
class SeasonalNaiveModel:
    season: int
    last_season: tuple[float, ...]  # the final `season` observations, oldest first
    last_date: date
    ratio_p10: float
    ratio_p90: float

    def forecast(self, horizon: int) -> list[dict]:
        rows = []
        for h in range(1, horizon + 1):
            p50 = self.last_season[(h - 1) % self.season]
            rows.append({
                "target_date": self.last_date + timedelta(days=h),
                "p10": max(0.0, min(p50, p50 * self.ratio_p10)),  # P10 <= P50 <= P90 always
                "p50": p50,
                "p90": max(p50, p50 * self.ratio_p90),
            })
        return rows

    def to_dict(self) -> dict:
        d = asdict(self)
        d["last_date"] = self.last_date.isoformat()
        d["last_season"] = list(self.last_season)
        return d


def fit(dates: list[date], values: list[float], season: int = SEASON) -> SeasonalNaiveModel:
    if len(values) < 2 * season:
        raise ValueError(f"need at least {2 * season} days of history, got {len(values)}")
    expected = [dates[0] + timedelta(days=i) for i in range(len(dates))]
    if list(dates) != expected:
        raise ValueError("history must be daily and gap-free")
    y = np.asarray(values, dtype=float)
    prev, cur = y[:-season], y[season:]
    valid = prev > 0
    ratios = cur[valid] / prev[valid] if valid.any() else np.array([1.0])
    return SeasonalNaiveModel(
        season=season,
        last_season=tuple(float(v) for v in y[-season:]),
        last_date=dates[-1],
        ratio_p10=float(np.quantile(ratios, 0.10)),
        ratio_p90=float(np.quantile(ratios, 0.90)),
    )


def backtest(values: list[float], holdout_days: int = 28, season: int = SEASON) -> dict:
    """One-step-ahead seasonal-naive errors over the last `holdout_days` (rolling origin).

    WAPE = sum|actual - forecast| / sum|actual|. Coverage = share of actuals inside P10–P90, with the
    interval ratios fitted only on data before each origin (no look-ahead).
    """
    y = np.asarray(values, dtype=float)
    if len(y) < holdout_days + 2 * season:
        raise ValueError("not enough history for the backtest")
    abs_err, abs_act, covered = 0.0, 0.0, 0
    for t in range(len(y) - holdout_days, len(y)):
        history = y[:t]
        point = history[t - season]
        prev, cur = history[:-season], history[season:]
        valid = prev > 0
        ratios = cur[valid] / prev[valid] if valid.any() else np.array([1.0])
        lo, hi = point * np.quantile(ratios, 0.10), point * np.quantile(ratios, 0.90)
        abs_err += abs(y[t] - point)
        abs_act += abs(y[t])
        covered += int(lo <= y[t] <= hi)
    return {
        "method": "rolling-origin, one-step-ahead",
        "holdout_days": holdout_days,
        "wape": round(abs_err / abs_act, 6) if abs_act else None,
        "p10_p90_coverage": round(covered / holdout_days, 6),
    }
