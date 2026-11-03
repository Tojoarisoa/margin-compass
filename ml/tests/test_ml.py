"""M1-04: seasonal-naive forecaster, registry backends, promotion policy."""

from __future__ import annotations

from datetime import date, timedelta

import boto3
import pytest
from moto import mock_aws

from mc_ml.cogs_forecast.seasonal_naive import backtest, fit
from mc_ml.registry import DynamoRegistry, FileRegistry, ModelVersion, should_promote

START = date(2025, 8, 1)


def weekly(n_weeks: int, pattern=(10, 12, 11, 13, 12, 3, 2)) -> tuple[list[date], list[float]]:
    values = [float(v) for _ in range(n_weeks) for v in pattern]
    return [START + timedelta(days=i) for i in range(len(values))], values


# --- Forecaster ----------------------------------------------------------------------------------
def test_forecast_repeats_the_last_week():
    dates, values = weekly(4)
    model = fit(dates, values)
    fc = model.forecast(14)
    assert [f["p50"] for f in fc] == values[-7:] * 2
    assert fc[0]["target_date"] == dates[-1] + timedelta(days=1)


def test_perfectly_weekly_series_has_zero_error_and_tight_interval():
    dates, values = weekly(8)
    bt = backtest(values, holdout_days=28)
    assert bt["wape"] == 0 and bt["p10_p90_coverage"] == 1
    assert all(f["p10"] == f["p50"] == f["p90"] for f in fit(dates, values).forecast(7))


def test_quantiles_are_ordered_and_non_negative_on_noisy_data():
    import numpy as np

    rng = np.random.default_rng(0)
    dates, values = weekly(10)
    noisy = [max(0.0, v * float(rng.normal(1, 0.2))) for v in values]
    for f in fit(dates, noisy).forecast(30):
        assert 0 <= f["p10"] <= f["p50"] <= f["p90"]


def test_backtest_wape_matches_a_hand_computation():
    dates, values = weekly(6)
    values[-1] += 5  # one surprise on the last day
    bt = backtest(values, holdout_days=7)
    expected = 5 / sum(values[-7:])
    assert bt["wape"] == pytest.approx(expected, abs=1e-6)


def test_fit_rejects_gaps_and_short_history():
    dates, values = weekly(3)
    with pytest.raises(ValueError, match="gap"):
        fit(dates[:5] + dates[6:], values[:5] + values[6:])
    with pytest.raises(ValueError, match="at least"):
        fit(dates[:10], values[:10])


# --- Promotion policy --------------------------------------------------------------------------
def mv(version: str, wape: float | None) -> ModelVersion:
    return ModelVersion("m", version, f"s3://b/{version}", f"s3://b/{version}.md", {"wape": wape}, {}, "run")


def test_first_version_is_promoted_and_worse_challengers_are_not():
    assert should_promote(mv("v1", 0.2), None)
    assert should_promote(mv("v2", 0.19), mv("v1", 0.2))
    assert should_promote(mv("v2", 0.2), mv("v1", 0.2))  # ties keep the newer model
    assert not should_promote(mv("v2", 0.21), mv("v1", 0.2))
    assert not should_promote(mv("v2", None), mv("v1", 0.2))


# --- Registry backends (same contract) ---------------------------------------------------------
@pytest.fixture(params=["file", "dynamodb"])
def registry(request, tmp_path):
    if request.param == "file":
        yield FileRegistry(tmp_path / "registry.json")
        return
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="core", BillingMode="PROVISIONED", ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
        )
        yield DynamoRegistry("core", client=client)


def test_register_is_idempotent_and_round_trips(registry):
    v1 = mv("v1", 0.2)
    assert registry.register(v1) is True
    assert registry.register(v1) is False
    assert registry.get_version("m", "v1") == v1
    assert registry.get_version("m", "nope") is None


def test_aliases_point_at_registered_versions_only(registry):
    registry.register(mv("v1", 0.2))
    assert registry.get_alias("m", "champion") is None
    registry.set_alias("m", "champion", "v1")
    assert registry.get_alias("m", "champion") == "v1"
    with pytest.raises(KeyError):
        registry.set_alias("m", "champion", "unregistered")
