"""M3-01 step 1: ETS baseline and the multi-step rolling-origin harness."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from mc_ml.cogs_forecast import ets, evaluate

START = date(2025, 8, 1)
PATTERN = (10, 12, 11, 13, 12, 3, 2)


def series(n_days: int, growth: float = 0.0, noise: float = 0.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    values = [max(0.0, PATTERN[i % 7] * (1 + growth * i) * float(rng.normal(1, noise)) if noise else PATTERN[i % 7] * (1 + growth * i)) for i in range(n_days)]
    return [START + timedelta(days=i) for i in range(n_days)], values


def test_ets_recovers_a_weekly_pattern():
    dates, values = series(70)
    fc = ets.fit(dates, values).forecast(14)
    assert [round(f["p50"], 3) for f in fc] == [float(PATTERN[(70 + i) % 7]) for i in range(14)]
    assert fc[0]["target_date"] == dates[-1] + timedelta(days=1)


def test_ets_quantiles_are_ordered_and_non_negative():
    dates, values = series(84, noise=0.3, seed=1)
    for f in ets.fit(dates, values).forecast(30):
        assert 0 <= f["p10"] <= f["p50"] <= f["p90"]


def test_ets_is_deterministic():
    dates, values = series(84, noise=0.2, seed=2)
    assert ets.fit(dates, values) == ets.fit(dates, values)


def test_ets_rejects_gaps_and_short_history():
    dates, values = series(30)
    with pytest.raises(ValueError, match="gap"):
        ets.fit(dates[:5] + dates[6:], values[:5] + values[6:])
    with pytest.raises(ValueError, match="at least"):
        ets.fit(dates[:10], values[:10])


def test_ets_beats_seasonal_naive_on_noisy_data():
    _, values = series(140, noise=0.3, seed=3)
    scores = evaluate.compare(values, horizon=14, origins=4)
    assert scores["ets"]["wape"] < scores["seasonal_naive"]["wape"]


def test_rolling_origin_is_exact_on_a_perfect_series():
    _, values = series(84)
    for name, score in evaluate.compare(values, horizon=14, origins=3).items():
        assert score["wape"] == pytest.approx(0, abs=1e-6), name
        assert score["pinball"] == pytest.approx(0, abs=1e-6), name
        assert score["p10_p90_coverage"] == 1


def test_pinball_matches_hand_values():
    assert evaluate.pinball(10, 8, 0.9) == pytest.approx(1.8)
    assert evaluate.pinball(8, 10, 0.9) == pytest.approx(0.2)


def test_rolling_origin_has_no_look_ahead():
    seen = []

    def spy(dates, values, horizon):
        seen.append(len(values))
        return [{"p10": 0, "p50": 0, "p90": 0}] * horizon

    evaluate.rolling_origin(spy, [1.0] * 100, horizon=10, origins=3, step=7)
    assert seen == [76, 83, 90]  # origins end 10 + 7*(3-1-k) days before the series end


def test_rolling_origin_rejects_short_series():
    with pytest.raises(ValueError, match="not enough"):
        evaluate.rolling_origin(evaluate.ets_forecaster, [1.0] * 40, horizon=30, origins=4)
