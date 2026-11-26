"""M5-04 step 4c-3: KPI-09 prediction through the calc-spec price_plan tool."""

import pytest

from mc_agents.kpi09 import DEFAULT_CHURN_BPS, predict_plan_change, tenant_plan
from mc_agents.tools.price_scenario import price_scenario

T1 = {"tenant_id": "bc-t0001", "arr_cents": 1_200_000, "addon_arr_cents": 240_000, "discount_bps": 1000}
T2 = {"tenant_id": "bc-t0002", "arr_cents": 600_000, "addon_arr_cents": 120_000, "discount_bps": 0, "cost_cents": 5000}


def test_tenant_plan_splits_arr_into_seat_and_addon():
    p = tenant_plan(T1)
    assert p["seat_price_cents"] == 80_000 and p["addon_cents"] == 20_000 and p["discount_bps"] == 1000
    assert p["cost_cents"] == 0


def test_no_churn_is_uplift_net_of_discount_every_month():
    r = predict_plan_change([T1], 1000, 3, churn_bps=0)
    # add-on 20,000/month, +10% = 2,000, less 10% discount = 1,800 per month
    assert r["monthly_revenue_delta_cents"] == [1800, 1800, 1800]
    assert r["revenue_delta_cents"] == 5400 and r["margin_delta_cents"] == 5400
    assert r["tool"] == "price_plan" and r["synthetic"] is True


def test_churn_shrinks_later_months_and_matches_tool_total():
    r = predict_plan_change([T1, T2], 1000, 6)
    assert r["churn_bps"] == DEFAULT_CHURN_BPS
    rev = r["monthly_revenue_delta_cents"]
    assert rev[0] > rev[-1] > 0
    total = 0
    for t in (T1, T2):
        p = tenant_plan(t)
        after = {"addon_cents": p["addon_cents"] * 11 // 10}
        total += price_scenario({**p, "after": after, "churn_bps": DEFAULT_CHURN_BPS, "months": 6})["churn"]["delta"][
            "adj_revenue_cents_change"]
    assert r["revenue_delta_cents"] == total


def test_zero_uplift_predicts_nothing():
    r = predict_plan_change([T1], 0, 4)
    assert r["revenue_delta_cents"] == 0 and r["margin_delta_cents"] == 0


@pytest.mark.parametrize("bad", [-1, True, 1.5])
def test_bad_uplift_rejected(bad):
    with pytest.raises(ValueError):
        predict_plan_change([T1], bad, 3)


def test_empty_plan_and_bad_tenant_rejected():
    with pytest.raises(ValueError):
        predict_plan_change([], 1000, 3)
    with pytest.raises(ValueError):
        tenant_plan({"tenant_id": "x", "arr_cents": 10, "addon_arr_cents": 20, "discount_bps": 0})
    with pytest.raises(ValueError):
        tenant_plan({"tenant_id": "x", "arr_cents": 10})


def test_error_bps_and_report():
    from mc_agents.kpi09 import error_bps, kpi09_report
    assert error_bps(110, 100) == 1000 and error_bps(90, -100) == 19000 and error_bps(5, 0) is None
    pred = {"revenue_delta_cents": 1000, "margin_delta_cents": 1000}
    ok = kpi09_report(pred, 950, 1050)
    assert ok["revenue_error_bps"] == 526 and ok["margin_error_bps"] == 476 and ok["passed"] is True
    bad = kpi09_report(pred, 950, 1300)
    assert bad["margin_error_bps"] == 2308 and bad["passed"] is False
    assert kpi09_report(pred, 0, 1000)["passed"] is False


def test_backtest_plan_change_from_simulator_tenants():
    from datetime import date
    from decimal import Decimal
    from types import SimpleNamespace

    from mc_agents.kpi09 import backtest_plan_change, months_covered, tenants_on_plan
    ts = [SimpleNamespace(tenant_id="bc-t0001", plan="growth", arr_usd=Decimal("12000.00"), ai_addon_arr_usd=Decimal("2400.00"),
                          discount_pct=Decimal("0.10")),
          SimpleNamespace(tenant_id="b", plan="starter", arr_usd=Decimal("6000.00"), ai_addon_arr_usd=Decimal("1200.00"),
                          discount_pct=Decimal("0"))]
    assert tenants_on_plan(ts, "growth") == [T1]
    assert months_covered(date(2026, 9, 1), date(2026, 10, 31)) == 2
    r = backtest_plan_change(ts, "growth", 1000, date(2026, 9, 1), date(2026, 10, 31), 36.0, 40.0)
    assert r["tenants"] == 1 and r["months"] == 2 and r["observed_revenue_cents"] == 3600
    assert r["predicted_revenue_cents"] == sum(r["monthly_predicted_revenue_cents"])
