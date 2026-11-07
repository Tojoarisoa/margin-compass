"""Unit-cost shift detector: seasonal-residual scoring with a run rule (numpy only, deterministic).

For each day the baseline is the median of the same weekday over the previous `weeks` weeks. A day is
*high* when its log-ratio to the baseline exceeds max(k * robust sigma, min_rel). `min_run` consecutive
high days raise an alert dated at the first high day; the baseline is frozen at that day so a persistent
shift does not absorb itself. The alert closes after `close_days` normal days. Impact is the mean excess
over the baseline, in the units of the series (USD per day when fed daily cost).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

SEASON = 7


@dataclass(frozen=True)
class Params:
    weeks: int = 4
    k: float = 4.0
    min_rel: float = 0.15  # log-ratio floor, about +16%
    min_run: int = 2
    close_days: int = 3


@dataclass(frozen=True)
class Alert:
    start: date
    detected: date  # day the run rule fired
    end: date | None  # None while open
    impact_per_day: float
    peak_ratio: float


def _baseline(values: np.ndarray, t: int, weeks: int) -> float:
    prior = [values[t - SEASON * w] for w in range(1, weeks + 1) if t - SEASON * w >= 0]
    return float(np.median(prior)) if prior else float("nan")


def _sigma(values: np.ndarray, t: int, weeks: int) -> float:
    """Robust spread (MAD) of log-ratios to the seasonal baseline over the 4 weeks before t."""
    logs = []
    for u in range(max(weeks * SEASON, t - 28), t):
        b = _baseline(values, u, weeks)
        if b > 0 and values[u] > 0:
            logs.append(math.log(values[u] / b))
    if len(logs) < 7:
        return 0.1
    a = np.asarray(logs)
    return max(1.4826 * float(np.median(np.abs(a - np.median(a)))), 0.02)


def detect(dates: list[date], values: list[float], params: Params | None = None) -> list[Alert]:
    x = np.asarray(values, dtype=float)
    p = params or Params()
    alerts: list[Alert] = []
    run: list[int] = []
    open_start: int | None = None
    detected = 0
    frozen: dict[int, float] = {}  # weekday slot -> baseline frozen at alert start
    frozen_sigma = 0.1
    calm = 0
    for t in range(p.weeks * SEASON, len(x)):
        if open_start is not None:
            base, sigma = frozen[t % SEASON], frozen_sigma
        else:
            base, sigma = _baseline(x, t, p.weeks), _sigma(x, t, p.weeks)
        if not base > 0:
            continue
        high = math.log(max(x[t], 1e-12) / base) > max(p.k * sigma, p.min_rel)
        if open_start is None:
            run = run + [t] if high else []
            if len(run) >= p.min_run:
                open_start, detected, run, calm = run[0], t, [], 0
                frozen_sigma = sigma
                frozen = {u % SEASON: _baseline(x, u, p.weeks) for u in range(open_start - SEASON + 1, open_start + 1)}
                alerts.append(_make(dates, x, frozen, open_start, detected, None, t))
        else:
            calm = 0 if high else calm + 1
            if calm >= p.close_days:
                alerts[-1] = _make(dates, x, frozen, open_start, detected, t - p.close_days, t)
                open_start = None
            else:
                alerts[-1] = _make(dates, x, frozen, open_start, detected, None, t)
    return alerts


def _make(dates, x, frozen, start: int, detected: int, end: int | None, upto: int) -> Alert:
    last = end if end is not None else upto
    days = range(start, last + 1)
    excess = [x[u] - frozen[u % SEASON] for u in days]
    ratios = [x[u] / frozen[u % SEASON] for u in days if frozen[u % SEASON] > 0]
    return Alert(dates[start], dates[detected], dates[end] if end is not None else None,
                 round(float(np.mean(excess)), 6), round(float(max(ratios)), 4) if ratios else 0.0)
