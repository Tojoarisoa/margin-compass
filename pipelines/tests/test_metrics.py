"""M2-03.1: the metric registry compiles to SQL and Python that agree, and rolls up from sums."""

from __future__ import annotations

from decimal import Decimal

import duckdb
import pytest

from mc_pipelines import metrics

ROWS = {
    "fct_m2_tenant_margin": [
        {"tenant_id": "a", "revenue_usd": "100.00", "cost_to_serve_usd": "60.5"},
        {"tenant_id": "b", "revenue_usd": "10.00", "cost_to_serve_usd": "30.25"},
    ],
    "agg_m2_cost_per_outcome": [
        {"cost_to_serve_usd": "30.0", "resolved_remotely": 10},
        {"cost_to_serve_usd": "5.0", "resolved_remotely": 0},  # cost on a day with no resolutions still counts
        {"cost_to_serve_usd": "5.0", "resolved_remotely": 10},
    ],
    "fct_unit_cost": [
        {"llm_cost_usd": "3.5", "requests": 1000},
        {"llm_cost_usd": "0.5", "requests": 3000},
    ],
    "fct_quality": [
        {"safety_events_flagged": 9, "safety_events_labeled": 10},
        {"safety_events_flagged": 0, "safety_events_labeled": 0},  # a day without events must not drag the roll-up
        {"safety_events_flagged": 1, "safety_events_labeled": 1},
    ],
    "fct_infra_cost_allocated": [
        {"rule_id": "AR-01", "allocated_cost_usd": "75.0000"},
        {"rule_id": "UNALLOCATED", "allocated_cost_usd": "25.0000"},
    ],
}


def _table(con, name: str, rows: list[dict]):
    cols = ", ".join(f"{k} {'varchar' if k in ('tenant_id', 'rule_id') else 'decimal(18,6)'}" for k in rows[0])
    con.execute(f"create table {name} ({cols})")
    for r in rows:
        con.execute(f"insert into {name} values ({', '.join('?' * len(r))})", list(r.values()))


@pytest.mark.parametrize("name", list(metrics.load()))
def test_sql_and_python_agree(name):
    m = metrics.load()[name]
    rows = ROWS[m["source"]]
    con = duckdb.connect()
    _table(con, m["source"], rows)
    sql_value = con.sql(f"select {metrics.to_sql(m)} from {m['source']}").fetchall()[0][0]
    py_value = metrics.compute(m, rows)
    assert py_value is not None and sql_value is not None
    assert abs(Decimal(str(sql_value)) - py_value) < Decimal("1e-9")


def test_known_values_and_rollup_from_sums():
    reg = metrics.load()
    assert metrics.compute(reg["gross_margin_usd"], ROWS["fct_m2_tenant_margin"]) == Decimal("19.25")
    assert metrics.compute(reg["attribution_coverage"], ROWS["fct_infra_cost_allocated"]) == Decimal("0.75")
    assert metrics.compute(reg["cost_per_outcome_usd"], ROWS["agg_m2_cost_per_outcome"]) == Decimal("2")
    # Recall is 10/11 from summed counts, not the mean of daily ratios (0.9, none, 1.0 -> 0.95).
    recall = metrics.compute(reg["safety_event_recall"], ROWS["fct_quality"])
    assert abs(recall - Decimal(10) / Decimal(11)) < Decimal("1e-12")


def test_empty_denominator_is_null_in_both_forms():
    m = metrics.load()["safety_event_recall"]
    rows = [{"safety_events_flagged": 0, "safety_events_labeled": 0}]
    con = duckdb.connect()
    _table(con, "fct_quality", rows)
    assert con.sql(f"select {metrics.to_sql(m)} from fct_quality").fetchall()[0][0] is None
    assert metrics.compute(m, rows) is None


def test_registry_rejects_bad_definitions(tmp_path):
    bad = tmp_path / "m.yml"
    bad.write_text("metrics:\n  - {name: x, kind: ratio, source: t, numerator: [{col: a}]}\n")
    with pytest.raises(ValueError):
        metrics.load(bad)
    bad.write_text("metrics:\n  - {name: x, kind: sum, source: t, terms: [{col: a}]}\n  - {name: x, kind: sum, source: t, terms: [{col: a}]}\n")
    with pytest.raises(ValueError):
        metrics.load(bad)


def test_registry_and_rules_paths_follow_env(tmp_path):
    """The Lambda image sets MC_METRICS_DIR / MC_REFERENCE_DIR (its code lives in site-packages)."""
    import subprocess
    import sys

    code = "from mc_pipelines import metrics, allocation; print(metrics.REGISTRY_PATH, allocation.RULES_PATH)"
    env = {**__import__("os").environ, "MC_METRICS_DIR": str(tmp_path / "m"), "MC_REFERENCE_DIR": str(tmp_path / "r")}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == [str(tmp_path / "m" / "metrics.yml"), str(tmp_path / "r" / "allocation_rules.yml")]
