"""M3-01 step 3: gradient-boosted forecaster."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_ets_evaluate import START, series

from mc_ml.cogs_forecast import evaluate, gbm


def test_gbm_recovers_a_weekly_pattern():
    dates, values = series(98)
    start_wd = START.weekday()
    fc = gbm.fit(dates, values).forecast(14)
    pattern = (10, 12, 11, 13, 12, 3, 2)
    for h, row in enumerate(fc):
        assert row["p50"] == pytest.approx(pattern[(98 + h) % 7], rel=0.15), (h, start_wd)
    assert fc[0]["target_date"] == dates[-1] + timedelta(days=1)


def test_gbm_quantiles_ordered_and_deterministic():
    dates, values = series(112, noise=0.3, seed=4)
    a, b = gbm.fit(dates, values), gbm.fit(dates, values)
    assert a == b
    for f in a.forecast(30):
        assert 0 <= f["p10"] <= f["p50"] <= f["p90"]


def test_gbm_rejects_gaps_and_short_history():
    dates, values = series(60)
    with pytest.raises(ValueError, match="gap"):
        gbm.fit(dates[:5] + dates[6:], values[:5] + values[6:])
    with pytest.raises(ValueError, match="at least"):
        gbm.fit(dates[:20], values[:20])


def test_gbm_is_scored_beside_the_baselines():
    _, values = series(140, noise=0.3, seed=3)
    scores = evaluate.compare(values, evaluate.CANDIDATES, horizon=14, origins=3)
    assert set(scores) == {"seasonal_naive", "ets", "gbm"}
    assert scores["gbm"]["wape"] < 0.6


def _score(wape, pinball):
    return {"wape": wape, "pinball": pinball, "p10_p90_coverage": 0.8}


def test_ev02_gate_needs_every_feature_to_beat_both_baselines():
    good = {"seasonal_naive": _score(0.3, 3), "ets": _score(0.25, 2.5), "gbm": _score(0.2, 2)}
    bad = {"seasonal_naive": _score(0.3, 3), "ets": _score(0.15, 2.5), "gbm": _score(0.2, 2)}
    assert evaluate.ev02_gate({"a": good, "b": None})["passed"]
    result = evaluate.ev02_gate({"a": good, "b": bad})
    assert not result["passed"] and "b: gbm wape" in result["failures"][0]
    assert not evaluate.ev02_gate({"a": None})["passed"]
