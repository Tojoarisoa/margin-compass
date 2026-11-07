"""Logistic churn baseline and the EV-11 scorer (AUC >= 0.75, well calibrated). Synthetic data only.

Features per renewal: price change %, mean CSAT, tenure years, segment price sensitivity, unresolved Sev-1 rate
(the same inputs as the simulator's PT-14, spec §9). The model is L2-regularised logistic regression fitted by
Newton steps on standardised features, so it is deterministic and needs no dependency beyond numpy.
"""

from __future__ import annotations

import numpy as np

AUC_MIN = 0.75
BRIER_MAX = 0.25  # an uninformed 0.5 forecast scores exactly 0.25
CALIBRATION_GAP_MAX = 0.10  # weighted mean |predicted - observed| across reliability bins


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


class LogisticChurn:
    def __init__(self, l2: float = 1.0, iterations: int = 25) -> None:
        self.l2 = l2
        self.iterations = iterations
        self.mean: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.coef: np.ndarray | None = None  # [intercept, *weights] on standardised features

    def fit(self, x: np.ndarray, y: np.ndarray) -> LogisticChurn:
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if x.ndim != 2 or len(x) != len(y) or len(x) == 0:
            raise ValueError("x must be 2-D with one row per label")
        if not set(np.unique(y)) <= {0.0, 1.0}:
            raise ValueError("labels must be 0 or 1")
        self.mean = x.mean(axis=0)
        sd = x.std(axis=0)
        self.scale = np.where(sd > 0, sd, 1.0)
        z = np.column_stack([np.ones(len(x)), (x - self.mean) / self.scale])
        w = np.zeros(z.shape[1])
        pen = np.full(z.shape[1], self.l2)
        pen[0] = 0.0  # the intercept is not penalised
        for _ in range(self.iterations):
            p = _sigmoid(z @ w)
            grad = z.T @ (p - y) + pen * w
            hess = (z * (p * (1 - p))[:, None]).T @ z + np.diag(pen) + 1e-9 * np.eye(len(w))
            step = np.linalg.solve(hess, grad)
            w = w - step
            if float(np.max(np.abs(step))) < 1e-8:
                break
        self.coef = w
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        if self.coef is None or self.mean is None or self.scale is None:
            raise ValueError("model is not fitted")
        x = np.asarray(x, dtype=float)
        z = np.column_stack([np.ones(len(x)), (x - self.mean) / self.scale])
        return _sigmoid(z @ self.coef)


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve (rank statistic, ties count one half). NaN when one class is missing."""
    y = np.asarray(y)
    p = np.asarray(p, dtype=float)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    greater = (pos[:, None] > neg[None, :]).sum()
    ties = (pos[:, None] == neg[None, :]).sum()
    return float((greater + 0.5 * ties) / (len(pos) * len(neg)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 5) -> list[dict[str, float]]:
    """Equal-width probability bins: count, mean predicted, observed rate (empty bins are skipped)."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append({"bin": b, "count": int(m.sum()), "mean_predicted": float(p[m].mean()), "observed": float(y[m].mean())})
    return out


def ev11_gate(y: np.ndarray, p: np.ndarray, bins: int = 5) -> dict[str, object]:
    """EV-11: AUC >= 0.75, Brier below the uninformed 0.25, and a weighted reliability gap of at most 0.10."""
    rel = reliability(y, p, bins)
    n = sum(r["count"] for r in rel)
    gap = sum(r["count"] * abs(r["mean_predicted"] - r["observed"]) for r in rel) / n if n else float("nan")
    a, b = auc(y, p), brier(y, p)
    passed = bool(a >= AUC_MIN and b < BRIER_MAX and gap <= CALIBRATION_GAP_MAX)
    return {"auc": a, "brier": b, "calibration_gap": float(gap), "reliability": rel, "n": int(n), "passed": passed}
