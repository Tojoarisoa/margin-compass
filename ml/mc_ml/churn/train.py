"""Fit the logistic churn model on PT-14 renewal events, check EV-11 on held-out events, write `fct_churn_scores`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .model import LogisticChurn, ev11_gate

FEATURES = ("price_change_pct", "csat_mean", "tenure_years", "sensitivity", "sev1_rate")
SCHEMA = pa.schema([
    ("tenant_id", pa.string()), ("renewal_date", pa.date32()), ("p_churn", pa.float64()), ("model_version", pa.string()),
    ("run_id", pa.string()),
])
MODEL_VERSION = "logistic-v1"


def read_events(path: Path) -> list[dict]:
    return pq.read_table(path).to_pylist()


def to_xy(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[float(r[f]) for f in FEATURES] for r in rows], dtype=float)
    y = np.array([1.0 if r["outcome"] == "churned" else 0.0 for r in rows])
    return x, y


def train_and_score(train_rows: list[dict], test_rows: list[dict]) -> tuple[LogisticChurn, dict]:
    """Fit on `train_rows`; EV-11 is judged on `test_rows` only (events from seeds the model never saw)."""
    x, y = to_xy(train_rows)
    model = LogisticChurn().fit(x, y)
    xt, yt = to_xy(test_rows)
    gate = ev11_gate(yt, model.predict_proba(xt))
    gate["train_n"] = len(train_rows)
    gate["coef"] = dict(zip(("intercept", *FEATURES), (float(c) for c in model.coef), strict=True))
    return model, gate


def write_scores(path: Path, model: LogisticChurn, rows: list[dict], run_id: str) -> int:
    """`fct_churn_scores`: the predicted churn probability for each renewal in `rows`."""
    p = model.predict_proba(to_xy(rows)[0])
    table = pa.Table.from_pylist(
        [{"tenant_id": r["tenant_id"], "renewal_date": r["renewal_date"], "p_churn": float(q),
          "model_version": MODEL_VERSION, "run_id": run_id} for r, q in zip(rows, p, strict=True)],
        schema=SCHEMA,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return table.num_rows


__all__ = ["FEATURES", "MODEL_VERSION", "read_events", "to_xy", "train_and_score", "write_scores"]
