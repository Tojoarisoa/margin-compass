"""Gradient-boosted AI COGS forecaster (M3-01, EV-02): numpy only, deterministic.

Squared-loss boosting of depth-2 regression trees on the log1p of daily cost. Features: lags 1, 7, 14,
the mean of the last 7 days, and weekday one-hot. Forecasts recurse one day at a time. P10/P90 come
from the empirical 10th/90th percentiles of in-sample one-step log residuals, widened with the horizon
by sqrt(h). No look-ahead: the model only sees the history it is fitted on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

SEASON = 7
LAGS = (1, 7, 14)
MIN_HISTORY = 14 + 14  # longest lag plus enough rows to fit
ROUNDS = 80
RATE = 0.1
DEPTH = 2
MIN_LEAF = 5


def _features(window: list[float], weekday: int) -> list[float]:
    """`window` is the history in log space, oldest first; `weekday` is that of the day to predict."""
    row = [window[-lag] for lag in LAGS]
    row.append(float(np.mean(window[-7:])))
    row.extend(1.0 if weekday == d else 0.0 for d in range(7))
    return row


def _best_split(x: np.ndarray, r: np.ndarray):
    best = None  # (gain, feature, threshold)
    total, n = r.sum(), len(r)
    for j in range(x.shape[1]):
        order = np.argsort(x[:, j], kind="stable")
        xs, rs = x[order, j], r[order]
        csum = np.cumsum(rs)
        for i in range(MIN_LEAF - 1, n - MIN_LEAF):
            if xs[i] == xs[i + 1]:
                continue
            left, right = csum[i], total - csum[i]
            gain = left**2 / (i + 1) + right**2 / (n - i - 1) - total**2 / n
            if best is None or gain > best[0] + 1e-12:
                best = (gain, j, (xs[i] + xs[i + 1]) / 2)
    return best


def _grow(x: np.ndarray, r: np.ndarray, depth: int):
    """A tree is a float (leaf) or (feature, threshold, left, right)."""
    split = _best_split(x, r) if depth > 0 and len(r) >= 2 * MIN_LEAF else None
    if split is None:
        return float(r.mean())
    _, j, thr = split
    mask = x[:, j] <= thr
    return (j, thr, _grow(x[mask], r[mask], depth - 1), _grow(x[~mask], r[~mask], depth - 1))


def _predict_tree(tree, row: list[float]) -> float:
    while not isinstance(tree, float):
        j, thr, left, right = tree
        tree = left if row[j] <= thr else right
    return tree


@dataclass(frozen=True)
class GbmModel:
    base: float
    trees: tuple
    window: tuple[float, ...]  # last 14 observations in log space, oldest first
    last_date: date
    resid_p10: float
    resid_p90: float

    def _step(self, window: list[float], weekday: int) -> float:
        row = _features(window, weekday)
        return self.base + RATE * sum(_predict_tree(t, row) for t in self.trees)

    def forecast(self, horizon: int) -> list[dict]:
        window, rows = list(self.window), []
        for h in range(1, horizon + 1):
            day = self.last_date + timedelta(days=h)
            pred = self._step(window, day.weekday())
            window.append(pred)
            scale = float(np.sqrt(h))
            p50 = max(0.0, float(np.expm1(pred)))
            rows.append({
                "target_date": day,
                "p10": max(0.0, min(p50, float(np.expm1(pred + self.resid_p10 * scale)))),
                "p50": p50,
                "p90": max(p50, float(np.expm1(pred + self.resid_p90 * scale))),
            })
        return rows


def fit(dates: list[date], values: list[float]) -> GbmModel:
    if len(values) < MIN_HISTORY + 14:
        raise ValueError(f"need at least {MIN_HISTORY + 14} days of history, got {len(values)}")
    if list(dates) != [dates[0] + timedelta(days=i) for i in range(len(dates))]:
        raise ValueError("history must be daily and gap-free")
    y = np.log1p(np.maximum(np.asarray(values, dtype=float), 0.0))
    ylist = y.tolist()
    start = max(LAGS)
    x = np.asarray([_features(ylist[:t], dates[t].weekday()) for t in range(start, len(y))])
    target = y[start:]
    base = float(target.mean())
    pred = np.full(len(target), base)
    trees = []
    for _ in range(ROUNDS):
        tree = _grow(x, target - pred, DEPTH)
        trees.append(tree)
        pred = pred + RATE * np.asarray([_predict_tree(tree, row) for row in x.tolist()])
    resid = target - pred
    lo, hi = np.quantile(resid, 0.10), np.quantile(resid, 0.90)
    return GbmModel(
        base=base, trees=tuple(trees), window=tuple(ylist[-14:]), last_date=dates[-1],
        resid_p10=float(min(lo, 0.0)), resid_p90=float(max(hi, 0.0)),
    )
