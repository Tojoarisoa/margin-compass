"""M6-02 step 1: forecaster drift checks."""

from datetime import date, timedelta

from mc_ml.cogs_forecast.drift import error_drift, forecast_accuracy_drift, forecaster_drift, naive_error

WEEK = [10.0, 12.0, 11.0, 13.0, 12.0, 6.0, 5.0]


def _days(n: int) -> list[date]:
    return [date(2025, 4, 1) + timedelta(days=i) for i in range(n)]


def _weekly(n: int, growth: float = 0.0) -> list[float]:
    return [WEEK[i % 7] * (1 + growth) ** i for i in range(n)]


def test_naive_error_zero_on_a_pure_weekly_cycle():
    assert naive_error(_weekly(28), 0, 28) == 0.0


def test_short_history_has_no_error_drift():
    assert error_drift(_weekly(100)) is None


def test_growth_and_weekly_cycle_do_not_drift():
    r = error_drift(_weekly(200, growth=0.003))
    assert r is not None and r["drift"] is False


def test_a_noisy_last_month_drifts():
    values = _weekly(200)
    for i in range(172, 200):
        values[i] *= 1.6 if i % 2 else 0.5
    r = error_drift(values)
    assert r["drift"] is True and r["recent_wape"] > r["reference_wape"]


def test_forecast_accuracy_needs_seven_realized_days_and_a_reference():
    actuals = {d: 10.0 for d in _days(10)}
    six = [{"target_date": d, "p50_usd": 10} for d in _days(6)]
    assert forecast_accuracy_drift(six, actuals, 0.1) is None
    seven = [{"target_date": d, "p50_usd": 10} for d in _days(7)]
    assert forecast_accuracy_drift(seven, actuals, None) is None
    assert forecast_accuracy_drift(seven, actuals, 0.1) == {"live_wape": 0.0, "reference_wape": 0.1, "days": 7, "drift": False}


def test_forecast_accuracy_drifts_when_live_error_doubles():
    actuals = {d: 10.0 for d in _days(14)}
    off = [{"target_date": d, "p50_usd": 14} for d in _days(14)]
    r = forecast_accuracy_drift(off, actuals, 0.1)
    assert r["live_wape"] == 0.4 and r["drift"] is True


def test_report_flags_retrain_only_for_drifted_features():
    days = _days(200)
    noisy = _weekly(200)
    for i in range(172, 200):
        noisy[i] *= 1.6 if i % 2 else 0.5
    r = forecaster_drift({"F1": _weekly(200), "F2": noisy}, days)
    assert r["drifted"] == ["F2"] and r["retrain"] is True and r["synthetic"] is True
    assert r["by_feature"]["F1"]["forecast_accuracy_drift"] is None
    assert r["window_end"] == days[-1].isoformat()


def test_report_is_deterministic():
    days = _days(200)
    s = {"F1": _weekly(200, 0.002)}
    assert forecaster_drift(s, days) == forecaster_drift(s, days)
