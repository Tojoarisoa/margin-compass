"""ETS baseline for AI COGS (M3-01, EV-02): additive Holt-Winters with a damped trend, season = 7.

Plain numpy, deterministic. Smoothing parameters come from a small fixed grid, chosen by the lowest
in-sample one-step squared error. P10/P90 use Gaussian intervals from the in-sample one-step residual
spread, widened with the horizon as for a local-level model: sigma * sqrt(1 + (h - 1) * alpha^2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product

import numpy as np

SEASON = 7
PHI = 0.9  # trend damping
Z80 = 1.2815515655446004  # standard normal 90th percentile
ALPHAS = (0.1, 0.3, 0.5, 0.7)
BETAS = (0.0, 0.05, 0.1)
GAMMAS = (0.05, 0.2, 0.4)


@dataclass(frozen=True)
class EtsModel:
    season: int
    alpha: float
    beta: float
    gamma: float
    level: float
    trend: float
    seasonals: tuple[float, ...]  # next `season` seasonal terms, first = the day after last_date
    sigma: float
    last_date: date

    def forecast(self, horizon: int) -> list[dict]:
        rows, damp = [], 0.0
        for h in range(1, horizon + 1):
            damp += PHI**h
            p50 = max(0.0, self.level + damp * self.trend + self.seasonals[(h - 1) % self.season])
            width = Z80 * self.sigma * float(np.sqrt(1 + (h - 1) * self.alpha**2))
            rows.append({
                "target_date": self.last_date + timedelta(days=h),
                "p10": max(0.0, p50 - width),
                "p50": p50,
                "p90": p50 + width,
            })
        return rows


def _run(y: np.ndarray, season: int, alpha: float, beta: float, gamma: float):
    """One pass of the recursions. Returns (sse, one-step residuals, level, trend, seasonals)."""
    level = float(y[:season].mean())
    trend = 0.0
    seas = [float(v) - level for v in y[:season]]  # seas[i] belongs to day i mod season
    resid = []
    for t in range(season, len(y)):
        s = seas[t % season]
        pred = level + PHI * trend + s
        err = float(y[t]) - pred
        resid.append(err)
        new_level = level + PHI * trend + alpha * err
        trend = PHI * trend + beta * (new_level - level - PHI * trend) if beta else 0.0
        seas[t % season] = s + gamma * (1 - alpha) * err
        level = new_level
    return float(np.sum(np.square(resid))), np.asarray(resid), level, trend, seas


def fit(dates: list[date], values: list[float], season: int = SEASON) -> EtsModel:
    if len(values) < 2 * season:
        raise ValueError(f"need at least {2 * season} days of history, got {len(values)}")
    if list(dates) != [dates[0] + timedelta(days=i) for i in range(len(dates))]:
        raise ValueError("history must be daily and gap-free")
    y = np.asarray(values, dtype=float)
    best = min(
        ((_run(y, season, a, b, g), (a, b, g)) for a, b, g in product(ALPHAS, BETAS, GAMMAS)),
        key=lambda item: (item[0][0], item[1]),  # ties break on parameters: deterministic
    )
    (_, resid, level, trend, seas), (alpha, beta, gamma) = best
    n = len(y)
    return EtsModel(
        season=season, alpha=alpha, beta=beta, gamma=gamma, level=level, trend=trend,
        seasonals=tuple(seas[(n + i) % season] for i in range(season)),
        sigma=float(resid.std()), last_date=dates[-1],
    )
