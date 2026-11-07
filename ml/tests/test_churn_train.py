from datetime import date

import numpy as np
import pyarrow.parquet as pq

from mc_ml.churn.train import FEATURES, train_and_score, write_scores


def _rows(n, seed):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        r = {"tenant_id": f"t{i}", "renewal_date": date(2026, 1, 1), "price_change_pct": float(rng.uniform(0, 8)),
             "csat_mean": float(rng.uniform(2.5, 4.8)), "tenure_years": float(rng.uniform(0.2, 6)),
             "sensitivity": float(rng.choice([0.0, 0.5, 1.0])), "sev1_rate": float(rng.uniform(0, 0.1))}
        z = -3.2 + 0.4 * r["price_change_pct"] - 1.5 * (r["csat_mean"] - 3) + 1.2 * r["sensitivity"] + 15 * r["sev1_rate"]
        r["outcome"] = "churned" if rng.random() < 1 / (1 + np.exp(-z)) else "renewed"
        out.append(r)
    return out


def test_train_gate_and_scores(tmp_path):
    train, test = _rows(4000, 1), _rows(1500, 2)
    model, gate = train_and_score(train, test)
    assert gate["passed"], gate
    assert gate["train_n"] == 4000 and set(gate["coef"]) == {"intercept", *FEATURES}
    assert write_scores(tmp_path / "g" / "fct_churn_scores.parquet", model, test, "r1") == 1500
    t = pq.read_table(tmp_path / "g" / "fct_churn_scores.parquet")
    assert t.num_rows == 1500 and 0 <= min(t["p_churn"].to_pylist()) <= max(t["p_churn"].to_pylist()) <= 1
