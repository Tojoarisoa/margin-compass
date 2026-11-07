"""PG-3 Margin Leaks snapshot (M3-05): built from the detector's mart and the daily cost it ran on."""
from __future__ import annotations

import json

import duckdb
from mc_pipelines.publish import build_pg3, publish_pg3


def _gold(tmp_path):
    gold = tmp_path / "gold"
    gold.mkdir()
    duckdb.sql(f"""COPY (SELECT * FROM (VALUES
        ('F-01','llm_cost_usd_per_day',DATE '2026-01-05',DATE '2026-01-06',NULL::DATE,12.5::DECIMAL(18,6),2.4,'open'),
        ('F-02','llm_cost_usd_per_day',DATE '2026-01-01',DATE '2026-01-02',DATE '2026-01-04',30.0::DECIMAL(18,6),3.1,'closed'),
        ('F-03','llm_cost_usd_per_day',DATE '2026-01-07',DATE '2026-01-08',NULL::DATE,7.25::DECIMAL(18,6),1.9,'open')
        ) t(feature_id, metric, start_date, detected_date, end_date, impact_usd_per_day, peak_ratio, status))
        TO '{gold}/fct_margin_leaks.parquet' (FORMAT PARQUET)""")
    duckdb.sql(f"""COPY (SELECT * FROM (VALUES
        (DATE '2026-01-01','F-01',10.0::DECIMAL(18,6)),(DATE '2026-01-01','F-01',2.5::DECIMAL(18,6)),
        (DATE '2026-01-02','F-02',4.0::DECIMAL(18,6))) t(cost_date, feature_id, llm_cost_usd))
        TO '{gold}/fct_unit_cost.parquet' (FORMAT PARQUET)""")
    return gold


def test_build_pg3_orders_leaks_by_impact_and_totals_open_impact(tmp_path):
    pg3 = build_pg3(_gold(tmp_path), "r1")
    assert pg3["schema_version"] == "pg3.v0" and pg3["data_label"] == "synthetic"
    assert [x["feature_id"] for x in pg3["leaks"]] == ["F-02", "F-01", "F-03"]
    assert pg3["leaks"][0]["end_date"] == "2026-01-04" and pg3["leaks"][1]["end_date"] is None
    assert pg3["open_leaks"] == 2 and pg3["open_impact_usd_per_day"] == 19.75
    assert {"date": "2026-01-01", "feature_id": "F-01", "llm_cost_usd": 12.5} in pg3["daily_llm_cost"]


def test_publish_pg3_writes_only_when_the_leak_mart_exists(tmp_path):
    assert publish_pg3(tmp_path, "r1") == []
    _gold(tmp_path)
    assert publish_pg3(tmp_path, "r1") == ["publish/latest/pg3.json"]
    assert json.loads((tmp_path / "publish" / "latest" / "pg3.json").read_text())["open_leaks"] == 2
