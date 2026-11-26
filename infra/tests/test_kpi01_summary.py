"""KPI-01 summary of a published pg1.json (ops verify-backfill, M6-04 case study input)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "kpi01_summary.py"
spec = importlib.util.spec_from_file_location("kpi01_summary", SCRIPT)
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


def _day(i, rev, cost):
    return {"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "ai_revenue_usd": rev, "ai_cost_to_serve_usd": cost}


def test_first_and_last_30_days_and_change_in_points():
    trend = [_day(i, 100.0, 40.0) for i in range(30)] + [_day(30 + i, 100.0, 30.0) for i in range(30)]
    out = k.summary({"run_id": "r1", "data_label": "synthetic", "trend": list(reversed(trend)),
                     "headline": {"unprofitable_tenants": 2, "tenants": 9}})
    assert out["first_30_days"]["ai_gross_margin_pct"] == "60.00"
    assert out["last_30_days"]["ai_gross_margin_pct"] == "70.00"
    assert out["window"]["ai_gross_margin_pct"] == "65.00" and out["window"]["days"] == 60
    assert out["change_pts"] == "10.00"
    assert out["data_label"] == "synthetic" and out["unprofitable_tenants"] == 2


def test_ratio_of_sums_not_mean_of_daily_ratios():
    out = k.summary({"trend": [_day(0, 10.0, 0.0), _day(1, 90.0, 90.0)]})
    assert out["window"]["ai_gross_margin_pct"] == "10.00"  # mean of daily % would be 50


def test_zero_revenue_and_empty_trend():
    out = k.summary({"trend": [_day(0, 0.0, 5.0)]})
    assert out["window"]["ai_gross_margin_pct"] is None and out["change_pts"] is None
    assert "error" in k.summary({"trend": []})


def test_compare_counterfactual_and_approved_runs():
    base = {"trend": [_day(i, 100.0, 40.0) for i in range(40)]}
    appr = {"data_label": "synthetic", "trend": [_day(i, 100.0, 40.0 if i < 10 else 35.0) for i in range(40)]}
    out = k.compare(base, appr)
    assert out["recovered_pts_last_30_days"] == "5.00"
    assert out["recovered_pts_window"] == "3.75"  # 30 of 40 days at +5 pts
    assert out["data_label"] == "synthetic" and out["counterfactual"]["last_30_days"]["ai_gross_margin_pct"] == "60.00"
    assert "error" in k.compare({"trend": []}, appr)
