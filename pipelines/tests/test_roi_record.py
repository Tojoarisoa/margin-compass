"""M5-04 KPI-13: owner-only ROI record (gold/_quality/roi.json) against the real bill."""

import json

import duckdb

from mc_pipelines.publish import write_roi


def _mart(root, rows):
    gold = root / "gold"
    gold.mkdir(parents=True)
    duckdb.sql(f"copy (select * from (values {rows}) t(action_id, status, realized_margin_usd)) "
               f"to '{gold / 'fct_realized_margin.parquet'}' (format parquet)")


def _focus(path):
    path.mkdir(parents=True)
    duckdb.sql(
        "copy (select * from (values (timestamp '2026-10-03', 'Amazon S3', 1.50, '{\"stage\":\"data\"}', 'Usage'), "
        "(timestamp '2026-11-02', 'Amazon Bedrock', 3.00, '{}', 'Usage'), "
        "(timestamp '2026-11-02', 'Amazon Bedrock', -3.00, '{}', 'Credit')) "
        "t(ChargePeriodStart, ServiceName, BilledCost, Tags, ChargeCategory)) "
        f"to '{path / 'part.parquet'}' (format parquet)")
    return str(path / "*.parquet")


def test_roi_uses_realized_rows_and_bill_before_credits(tmp_path, monkeypatch):
    _mart(tmp_path, "('a', 'realized', 40.0), ('b', 'realized', 5.0), ('c', 'pending_verification', 99.0)")
    monkeypatch.setenv("MC_FINOPS_FOCUS_GLOB", _focus(tmp_path / "bill"))
    assert write_roi(tmp_path, "r1") == ["gold/_quality/roi.json"]
    body = json.loads((tmp_path / "gold" / "_quality" / "roi.json").read_text())
    assert (body["realized_margin_usd"], body["platform_cost_usd"], body["net_usd"]) == ("45.00", "4.50", "40.50")
    assert body["roi_bps"] == 90000 and body["status"] == "ok"  # (45 - 4.5) / 4.5 = 9.0x
    assert (body["realized_margin_label"], body["platform_cost_label"]) == ("synthetic", "real")
    assert body["bill_months"] == ["2026-10-01", "2026-11-01"]
    assert not (tmp_path / "publish").exists()  # owner record only, never in the public snapshot


def test_roi_awaits_bill_and_skips_without_mart(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_FINOPS_FOCUS_GLOB", raising=False)
    assert write_roi(tmp_path / "none", "r1") == []
    _mart(tmp_path, "('a', 'realized', 1.0)")
    write_roi(tmp_path, "r1")
    body = json.loads((tmp_path / "gold" / "_quality" / "roi.json").read_text())
    assert body["status"] == "awaiting_bill" and body["roi_bps"] is None
