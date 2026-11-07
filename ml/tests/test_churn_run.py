import pyarrow as pa
import pyarrow.parquet as pq

from mc_ml.churn.run import run_churn

from test_churn_train import _rows


def test_run_churn_time_split(tmp_path):
    rows = _rows(3000, 3)
    for i, r in enumerate(rows):
        r["renewal_date"] = r["renewal_date"].replace(day=1 + i % 28, month=1 + (i // 28) % 12)
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / "ev.parquet")
    out = run_churn(tmp_path / "ev.parquet", tmp_path / "gold", "r1")
    assert out["ev11"]["passed"] and out["ev11"]["test_n"] == 900 and out["ev11"]["scored"] == 3000
    assert (tmp_path / "gold" / "fct_churn_scores.parquet").exists()


def test_run_churn_too_few(tmp_path):
    pq.write_table(pa.Table.from_pylist(_rows(10, 1)), tmp_path / "ev.parquet")
    assert "skipped" in run_churn(tmp_path / "ev.parquet", tmp_path / "gold", "r1")
