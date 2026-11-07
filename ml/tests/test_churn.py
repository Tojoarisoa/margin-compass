import numpy as np
import pytest

from mc_ml.churn import LogisticChurn, auc, brier, ev11_gate, reliability


def _data(n, seed):
    rng = np.random.default_rng(seed)
    x = np.column_stack([
        rng.uniform(-5, 25, n), rng.uniform(2.5, 4.8, n), rng.uniform(0.2, 6, n),
        rng.choice([0.5, 1.0, 1.5], n), rng.uniform(0, 0.1, n),
    ])
    z = -2.0 + 0.12 * x[:, 0] - 1.2 * (x[:, 1] - 3) - 0.25 * x[:, 2] + 0.8 * x[:, 3] + 10 * x[:, 4]
    p = 1 / (1 + np.exp(-z))
    return x, (rng.random(n) < p).astype(float), p


def test_auc_known_values():
    assert auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8])) == 0.75
    assert auc(np.array([0, 1]), np.array([0.5, 0.5])) == 0.5
    assert np.isnan(auc(np.array([1, 1]), np.array([0.2, 0.9])))


def test_brier_and_reliability():
    assert brier(np.array([1, 0]), np.array([1.0, 0.0])) == 0.0
    rel = reliability(np.array([1, 0, 1, 1]), np.array([0.9, 0.1, 0.8, 0.95]), bins=2)
    assert [r["count"] for r in rel] == [1, 3]


def test_fit_beats_gate_on_held_out_and_recovers_signs():
    x, y, _ = _data(3000, 1)
    xt, yt, _ = _data(1500, 2)
    m = LogisticChurn().fit(x, y)
    g = ev11_gate(yt, m.predict_proba(xt))
    assert g["passed"], g
    assert m.coef[1] > 0 > m.coef[2]  # price up raises churn, CSAT up lowers it


def test_gate_fails_on_uninformed_forecast():
    _, y, _ = _data(2000, 3)
    assert not ev11_gate(y, np.full(len(y), y.mean()))["passed"]


def test_deterministic_and_validates():
    x, y, _ = _data(500, 4)
    assert np.array_equal(LogisticChurn().fit(x, y).coef, LogisticChurn().fit(x, y).coef)
    with pytest.raises(ValueError):
        LogisticChurn().fit(x, y + 2)
    with pytest.raises(ValueError):
        LogisticChurn().predict_proba(x)
