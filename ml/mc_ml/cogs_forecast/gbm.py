"""Gradient-boosted AI COGS forecaster (M3-01, EV-02): numpy only, deterministic.

Works on z = log(cost / scale + FLOOR), where `scale` is the mean of the history, so every series (a
$0.15/day feature or a $7k/day one) is on the same footing and near-zero days cannot blow up. Squared-loss
boosting of 50 stumps (depth 1; deeper or longer fits overfit the level steps in the real F4 series) predicts the change from the base (the same weekday last week) from the lag deviations (lags 1, 7, 14, 21, 28 minus the base), the week-over-week and
three-week trends of the 7-day mean, and the weekday. The training series is winsorized at the 1st and 99th
percentile so a one-off spike cannot drive the recursion. Forecasts recurse one day at a time and are clipped
to the range of the history. P10/P90 come from the empirical 10th/90th
percentiles of in-sample one-step residuals, widened with the horizon by h**WIDEN. No look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

SEASON = 7
LAGS = (1, 7, 14, 21, 28)
WINDOW = 28  # longest lag
MIN_HISTORY = WINDOW + 14  # the window plus enough rows to fit
ROUNDS = 50
RATE = 0.1
DEPTH = 1
MIN_LEAF = 5
FLOOR = 0.05  # z = log(cost / scale + FLOOR)
TRIM = 0.01  # winsorize z at this quantile on both sides before fitting
WIDEN = 0.1  # interval half-width grows as h**WIDEN


def _level(window: list[float]) -> float:
    """Base prediction: the same weekday last week (follows level shifts at once; the trees correct the rest)."""
    return float(window[-7])


def _features(window: list[float], weekday: int) -> list[float]:
    """`window` is the history in z space, oldest first; `weekday` is that of the day to predict."""
    base = _level(window)
    row = [window[-lag] - base for lag in LAGS]
    m7 = float(np.mean(window[-7:]))
    row.append(m7 - float(np.mean(window[-14:-7])))  # this week vs last
    row.append(m7 - float(np.mean(window[-28:-21])))  # this week vs three weeks ago
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
    trees: tuple
    window: tuple[float, ...]  # last 28 observations in z space, oldest first
    scale: float
    zmin: float
    zmax: float
    last_date: date
    resid_p10: float
    resid_p90: float

    def _step(self, window: list[float], weekday: int) -> float:
        row = _features(window, weekday)
        z = _level(window) + RATE * sum(_predict_tree(t, row) for t in self.trees)
        return min(max(z, self.zmin), self.zmax)

    def to_dict(self) -> dict:
        def tree(t):
            return t if isinstance(t, float) else [t[0], t[1], tree(t[2]), tree(t[3])]
        return {"model": "gbm", "rate": RATE, "lags": list(LAGS), "floor": FLOOR, "widen": WIDEN, "scale": self.scale,
                "zmin": self.zmin, "zmax": self.zmax, "last_date": self.last_date.isoformat(),
                "window": list(self.window), "resid_p10": self.resid_p10, "resid_p90": self.resid_p90,
                "trees": [tree(t) for t in self.trees]}

    def _cost(self, z: float) -> float:
        return max(0.0, float(np.exp(z) - FLOOR) * self.scale)

    def forecast(self, horizon: int) -> list[dict]:
        window, rows = list(self.window), []
        for h in range(1, horizon + 1):
            day = self.last_date + timedelta(days=h)
            pred = self._step(window, day.weekday())
            window.append(pred)
            wide = float(h**WIDEN)
            p50 = self._cost(pred)
            rows.append({
                "target_date": day,
                "p10": max(0.0, min(p50, self._cost(pred + self.resid_p10 * wide))),
                "p50": p50,
                "p90": max(p50, self._cost(pred + self.resid_p90 * wide)),
            })
        return rows


def fit(dates: list[date], values: list[float]) -> GbmModel:
    if len(values) < MIN_HISTORY + 14:
        raise ValueError(f"need at least {MIN_HISTORY + 14} days of history, got {len(values)}")
    if list(dates) != [dates[0] + timedelta(days=i) for i in range(len(dates))]:
        raise ValueError("history must be daily and gap-free")
    raw = np.maximum(np.asarray(values, dtype=float), 0.0)
    scale = float(raw.mean()) or 1.0
    y = np.log(raw / scale + FLOOR)
    y = np.clip(y, np.quantile(y, TRIM), np.quantile(y, 1 - TRIM))  # one-off spikes must not drive the recursion
    ylist = y.tolist()
    x = np.asarray([_features(ylist[:t], dates[t].weekday()) for t in range(WINDOW, len(y))])
    level = np.asarray([_level(ylist[:t]) for t in range(WINDOW, len(y))])
    target = y[WINDOW:] - level
    pred = np.zeros(len(target))
    trees = []
    for _ in range(ROUNDS):
        tree = _grow(x, target - pred, DEPTH)
        trees.append(tree)
        pred = pred + RATE * np.asarray([_predict_tree(tree, row) for row in x.tolist()])
    resid = target - pred
    lo, hi = np.quantile(resid, 0.10), np.quantile(resid, 0.90)
    return GbmModel(
        trees=tuple(trees), window=tuple(ylist[-WINDOW:]), scale=scale, zmin=float(y.min()), zmax=float(y.max()),
        last_date=dates[-1], resid_p10=float(min(lo, 0.0)), resid_p90=float(max(hi, 0.0)),
    )
