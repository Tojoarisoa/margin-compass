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
    assert [r["feature_id"] for r in mart] == ["F1"] and mart[0]["status"] == "closed"  # a shift that persists is re-baselined
    assert out["ev03"]["found"] == ["PT-01"] and out["ev03"]["passed"] and out["ev03"]["precision"] == 1.0


def test_alert_on_wrong_feature_is_a_false_positive(tmp_path):
    _write(tmp_path)
    lab = [{"pattern_id": "PT-01", "feature_id": "F2", "start_date": START + timedelta(days=60), "end_date": START + timedelta(days=119)}]
    pq.write_table(pa.Table.from_pylist(lab), tmp_path / "patterns.parquet")
    ev = run_detector(tmp_path, tmp_path / "patterns.parquet", "r1")["ev03"]
    assert ev["precision"] == 0.0 and ev["recall"] == 0.0 and ev["missed"] == ["PT-01"] and not ev["passed"]


def test_reads_m2_label_columns(tmp_path):
    """The m2 simulator writes `feature` (not `feature_id`) plus `type` and `tenant_ids`."""
    _write(tmp_path)
    lab = [{"pattern_id": "PT-01", "type": "model_swap", "tenant_ids": [], "feature": "F1", "model": None,
            "start_date": START + timedelta(days=60), "end_date": START + timedelta(days=119)}]
    pq.write_table(pa.Table.from_pylist(lab), tmp_path / "patterns.parquet")
    out = run_detector(tmp_path, tmp_path / "patterns.parquet", "r1")
    assert out["ev03"]["found"] == ["PT-01"] and out["ev03"]["passed"]


def _usage(tmp_path, retry_surge=True, n=120):
    """Silver usage for one feature with 3 tenants; tenant t2 retries x6 on days 80-83."""
    gold, silver = tmp_path / "gold", tmp_path / "silver"
    gold.mkdir(), silver.mkdir()
    rows, cost = [], []
    for i in range(n):
        d = START + timedelta(days=i)
        for t in ("t1", "t2", "t3"):
            retries = 5 + (i + len(t)) % 2
            if retry_surge and t == "t2" and 80 <= i <= 83:
                retries *= 6
            rows.append({"usage_date": d, "tenant_id": t, "feature_id": "F2", "request_count": 100, "input_tokens": 1000,
                         "uncached_input_tokens": 300, "retry_count": retries, "llm_cost_usd": Decimal("1.5")})
        cost.append({"cost_date": d, "feature_id": "F2", "llm_cost_usd": Decimal("4.5")})
    pq.write_table(pa.Table.from_pylist(rows), silver / "slv_m2_llm_usage_priced.parquet")
    pq.write_table(pa.Table.from_pylist(cost), gold / "fct_unit_cost.parquet")
    lab = [{"pattern_id": "PT-02", "feature": "F2", "start_date": START + timedelta(days=80), "end_date": START + timedelta(days=83)}]
    pq.write_table(pa.Table.from_pylist(lab), tmp_path / "patterns.parquet")
    return gold


def test_tenant_retry_surge_is_found_from_usage_detail(tmp_path):
    gold = _usage(tmp_path)
    out = run_detector(gold, tmp_path / "patterns.parquet", "r1")
    mart = pq.read_table(gold / "fct_margin_leaks.parquet").to_pylist()
    assert [(r["feature_id"], r["tenant_id"], r["metric"]) for r in mart] == [("F2", "t2", "tenant_retry_count")]
    assert out["ev03"]["found"] == ["PT-02"] and out["ev03"]["precision"] == 1.0


def test_quiet_usage_raises_no_alert(tmp_path):
    gold = _usage(tmp_path, retry_surge=False)
    assert run_detector(gold, None, "r1")["alerts"] == 0
