"""M3-01: the forecaster trains on M2 gold (fct_unit_cost) as well as M1 gold."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pyarrow as pa
import pyarrow.parquet as pq

from mc_ml.registry import FileRegistry
from mc_ml.train import train_cogs_forecaster


def test_trains_on_m2_unit_cost_layout(tmp_path):
    gold = tmp_path / "gold"
    gold.mkdir()
    start = date(2025, 4, 1)
    rows = [(start + timedelta(days=i), f, 10 + 3 * math.sin(i * 2 * math.pi / 7) + k) for i in range(120) for k, f in enumerate(("F1", "F2"))]
    pq.write_table(pa.table({"cost_date": [r[0] for r in rows], "feature_id": [r[1] for r in rows], "llm_cost_usd": [r[2] for r in rows]}),
                   gold / "fct_unit_cost.parquet")
    out = train_cogs_forecaster(gold, tmp_path / "models", FileRegistry(tmp_path / "models" / "registry.json"), str(tmp_path / "models"), "r1")
    assert out["registered"] and out["forecast_rows"] == 2 * 30
    bt = json.loads((tmp_path / "models" / "ai_cogs_forecaster" / out["version"] / "backtest.json").read_text())
    assert "passed" in bt["ev02"]


def test_train_writes_the_model_drift_report(tmp_path):
    """M6-02: every train run writes gold/_quality/model_drift.json; a clean weekly series does not ask for a retrain."""
    gold = tmp_path / "gold"
    gold.mkdir()
    start = date(2025, 4, 1)
    rows = [(start + timedelta(days=i), "F1", 10 + 3 * math.sin(i * 2 * math.pi / 7)) for i in range(160)]
    pq.write_table(pa.table({"cost_date": [r[0] for r in rows], "feature_id": [r[1] for r in rows], "llm_cost_usd": [r[2] for r in rows]}),
                   gold / "fct_unit_cost.parquet")
    reg = FileRegistry(tmp_path / "models" / "registry.json")
    out = train_cogs_forecaster(gold, tmp_path / "models", reg, str(tmp_path / "models"), "r1")
    report = json.loads((gold / "_quality" / "model_drift.json").read_text())
    assert report["synthetic"] is True and report["run_id"] == "r1" and report["retrain"] is False
    assert report["by_feature"]["F1"]["error_drift"]["drift"] is False
    assert out["drift_retrain"] is False and out["drifted_features"] == []
    # a second run reads the first run's forecasts; none of their target days has actuals yet
    train_cogs_forecaster(gold, tmp_path / "models", reg, str(tmp_path / "models"), "r2")
    report = json.loads((gold / "_quality" / "model_drift.json").read_text())
    assert report["by_feature"]["F1"]["forecast_accuracy_drift"] is None
