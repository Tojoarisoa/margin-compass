"""M3-02 step 2: detector over gold, mart output, per-feature EV-03 scoring."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq

from mc_ml.leak_detector.run import run_detector

START = date(2025, 8, 1)
PATTERN = (10, 12, 11, 13, 12, 3, 2)


def _write(tmp_path, shift_from=60):
    rows = []
    for i in range(120):
        d = START + timedelta(days=i)
        for f in ("F1", "F2"):
            v = PATTERN[i % 7] * (1.5 if f == "F1" and i >= shift_from else 1.0)
            rows.append({"cost_date": d, "feature_id": f, "llm_cost_usd": Decimal(str(round(v, 6)))})
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / "fct_unit_cost.parquet")
    lab = [{"pattern_id": "PT-01", "feature_id": "F1", "start_date": START + timedelta(days=shift_from), "end_date": START + timedelta(days=119)}]
    pq.write_table(pa.Table.from_pylist(lab), tmp_path / "patterns.parquet")


def test_finds_labelled_shift_and_writes_mart(tmp_path):
    _write(tmp_path)
    out = run_detector(tmp_path, tmp_path / "patterns.parquet", "r1")
    mart = pq.read_table(tmp_path / "fct_margin_leaks.parquet").to_pylist()
    assert [r["feature_id"] for r in mart] == ["F1"] and mart[0]["status"] == "open"
    assert out["ev03"]["found"] == ["PT-01"] and out["ev03"]["passed"] and out["ev03"]["precision"] == 1.0


def test_alert_on_wrong_feature_is_a_false_positive(tmp_path):
    _write(tmp_path)
    lab = [{"pattern_id": "PT-01", "feature_id": "F2", "start_date": START + timedelta(days=60), "end_date": START + timedelta(days=119)}]
    pq.write_table(pa.Table.from_pylist(lab), tmp_path / "patterns.parquet")
    ev = run_detector(tmp_path, tmp_path / "patterns.parquet", "r1")["ev03"]
    assert ev["precision"] == 0.0 and ev["recall"] == 0.0 and ev["missed"] == ["PT-01"] and not ev["passed"]
