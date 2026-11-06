"""Publish step (M1-07): gold -> dashboard snapshot for PG-1 (Executive Margin Overview) v0.

Writes <data_root>/publish/latest/pg1.json and publish/history/<ingest_date>/pg1.json.
Every figure is computed here, in Decimal, from the gold marts; the dashboard only formats them.
PLAN.md §7.5: a KPI page snapshot stays ≤ 200 KB (checked here, and the run fails if it isn't).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb

from mc_pipelines import metrics as registry

SCHEMA_VERSION = "pg1.v0"
MAX_BYTES = 200 * 1024
CENT, RATIO = Decimal("0.01"), Decimal("0.000001")


class PublishError(RuntimeError):
    pass


def _money(x) -> float:
    return float(Decimal(x).quantize(CENT, ROUND_HALF_UP))


def _ratio(num, den) -> float | None:
    den = Decimal(den)
    return float((Decimal(num) / den).quantize(RATIO, ROUND_HALF_UP)) if den else None


def _totals(rows) -> dict:
    rev = sum((Decimal(r[0]) for r in rows), Decimal(0))
    cost = sum((Decimal(r[1]) for r in rows), Decimal(0))
    return {"ai_revenue_usd": _money(rev), "ai_cost_to_serve_usd": _money(cost), "ai_gross_margin_usd": _money(rev - cost),
            "ai_gross_margin_pct": _ratio(rev - cost, rev)}


def build_pg1(gold: Path, run_id: str, ingest_date: str) -> dict:
    g = Path(gold)
    con = duckdb.connect()
    kpi = f"read_parquet('{g}/agg_exec_kpis.parquet')"
    days = con.execute(f"""SELECT kpi_date, total_revenue_usd, ai_revenue_usd, ai_cost_to_serve_usd, llm_spend_usd,
                                  unallocated_llm_cost_usd, kpi04_unprofitable_tenants
                           FROM {kpi} ORDER BY kpi_date""").fetchall()
    if not days:
        raise PublishError("agg_exec_kpis is empty")
    first, last = days[0][0], days[-1][0]
    recent_from = last - timedelta(days=29)
    window = [(d[2], d[3]) for d in days]
    recent = [(d[2], d[3]) for d in days if d[0] >= recent_from]
    llm = sum((Decimal(d[4]) for d in days), Decimal(0))
    unalloc = sum((Decimal(d[5]) for d in days), Decimal(0))

    tenants = con.execute(f"""
        WITH m AS (SELECT tenant_id, sum(ai_revenue_usd) rev, sum(cost_to_serve_usd) cost, sum(request_count) req
                   FROM read_parquet('{g}/fct_tenant_margin.parquet') GROUP BY tenant_id),
             p AS (SELECT tenant_id, arg_max(plan, revenue_date) plan FROM read_parquet('{g}/fct_revenue_daily.parquet') GROUP BY tenant_id)
        SELECT m.tenant_id, p.plan, m.rev, m.cost, m.req FROM m LEFT JOIN p USING (tenant_id) ORDER BY m.tenant_id""").fetchall()
    tenant_rows = [{"tenant_id": t, "plan": plan, **_totals([(rev, cost)]), "request_count": int(req)}
                   for t, plan, rev, cost, req in tenants]
    tenant_rows.sort(key=lambda r: (r["ai_gross_margin_pct"] if r["ai_gross_margin_pct"] is not None else -1e9, r["tenant_id"]))

    fc = con.execute(f"""SELECT forecast_date, target_date, p10_usd, p50_usd, p90_usd, model_version, model_alias
                         FROM read_parquet('{g}/fct_forecasts.parquet') WHERE metric = 'ai_cogs_usd' ORDER BY target_date""").fetchall()

    m2 = m2_kpis(g) if _m2_marts_present(g) else None
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "page": "PG-1 Executive Margin Overview (v0)",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": run_id, "ingest_date": ingest_date,
        "data_label": "synthetic", "feature_scope": "F1 only (M1)",
        "window": {"from": first.isoformat(), "to": last.isoformat(), "days": len(days)},
        "headline": {
            "window": _totals(window),
            "last_30_days": {"from": recent_from.isoformat(), "to": last.isoformat(), **_totals(recent)},
            "total_revenue_usd": _money(sum((Decimal(d[1]) for d in days), Decimal(0))),
            "llm_attribution_coverage_pct": _ratio(llm - unalloc, llm),
            "unprofitable_tenants": sum(1 for r in tenant_rows if r["ai_gross_margin_usd"] < 0),
            "tenants": len(tenant_rows),
        },
        "trend": [{"date": d[0].isoformat(), "ai_revenue_usd": _money(d[2]), "ai_cost_to_serve_usd": _money(d[3]),
                   "ai_gross_margin_pct": _ratio(Decimal(d[2]) - Decimal(d[3]), d[2])} for d in days],
        "forecast": {
            "metric": "ai_cogs_usd", "model_version": fc[0][5] if fc else None, "model_alias": fc[0][6] if fc else None,
            "points": [{"date": r[1].isoformat(), "p10": _money(r[2]), "p50": _money(r[3]), "p90": _money(r[4])} for r in fc],
        },
        "tenants": tenant_rows,
        "not_yet_available": {
            "margin_recovered": "M3 (actions)", "cost_per_outcome": "M2 (outcomes)", "roi_multiple": "M5",
            "arr_at_risk": "M2", "plan_target": "M2", "daily_margin_brief": "M5",
        },
    }
    if m2 is not None:
        snapshot["m2_kpis"] = m2  # additive (PG-1 M2-04): registry KPIs over the whole window, metrics/metrics.yml
        snapshot["not_yet_available"].pop("cost_per_outcome", None)
    return snapshot


def publish(data_root: Path, run_id: str, ingest_date: str) -> dict:
    root = Path(data_root)
    snapshot = build_pg1(root / "gold", run_id, ingest_date)
    body = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode()
    if len(body) > MAX_BYTES:
        raise PublishError(f"pg1.json is {len(body)} bytes; the §7.5 limit is {MAX_BYTES}")
    paths = [root / "publish" / "latest" / "pg1.json", root / "publish" / "history" / ingest_date / "pg1.json"]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return {"bytes": len(body), "files": [str(p.relative_to(root)) for p in paths], "days": snapshot["window"]["days"]}


def _m2_marts_present(gold: Path) -> bool:
    return all((Path(gold) / f"{m['source']}.parquet").exists() for m in registry.load().values())


def m2_kpis(gold: Path, names: tuple[str, ...] | None = None) -> dict[str, float | None]:
    """M2 headline KPIs over the whole window, every figure from the metric registry (`metrics/metrics.yml`).

    Rows are read from each metric's source mart and passed to `registry.compute` (sums, then ratios of sums).
    """
    con = duckdb.connect()
    out: dict[str, float | None] = {}
    for name, metric in registry.load().items():
        if names is not None and name not in names:
            continue
        cur = con.execute(f"SELECT * FROM read_parquet('{Path(gold)}/{metric['source']}.parquet')")
        cols = [c[0] for c in cur.description]
        value = registry.compute(metric, [dict(zip(cols, r, strict=True)) for r in cur.fetchall()])
        out[name] = None if value is None else float(value.quantize(RATIO, ROUND_HALF_UP))
    return out
