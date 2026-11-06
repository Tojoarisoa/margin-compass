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
EXPLORE_MAX_BYTES = 5 * 1024 * 1024  # M2-04: exploration Parquet for PG-2 (DuckDB-WASM)
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
        snapshot["m2_at_risk"] = m2_at_risk(g)  # additive (PG-1 M2-04): unprofitable tenants and ARR at risk
        snapshot["m2_margin_forecast"] = margin_forecast(recent, fc)  # additive (PG-1 M2-04): margin % band
        snapshot["m2_features"] = m2_feature_costs(g)  # additive (PG-1 M2-04): fully loaded cost by feature
        snapshot["not_yet_available"].pop("cost_per_outcome", None)
        snapshot["not_yet_available"].pop("arr_at_risk", None)
    return snapshot


def write_explore_parquet(gold: Path, out: Path) -> int:
    """PG-2 exploration Parquet: fully loaded cost to serve at tenant x feature x month grain, with names.

    Sums only (no ratios), so the browser can roll up any slice and stay equal to the marts. Fails if over 5 MB.
    """
    g = Path(gold)
    out.parent.mkdir(parents=True, exist_ok=True)
    duckdb.connect().execute(f"""
        COPY (SELECT date_trunc('month', c.cost_date)::DATE AS month, c.tenant_id, c.feature_id, any_value(f.feature_name) AS feature_name,
                     sum(c.requests) AS requests, sum(c.llm_cost_usd) AS llm_cost_usd, sum(c.agent_compute_usd) AS agent_compute_usd,
                     sum(c.vector_usd) AS vector_usd, sum(c.network_observability_usd) AS network_observability_usd,
                     sum(c.third_party_usd) AS third_party_usd, sum(c.cost_to_serve_usd) AS cost_to_serve_usd
              FROM read_parquet('{g}/fct_cost_to_serve.parquet') c
              LEFT JOIN read_parquet('{g}/dim_feature.parquet') f USING (feature_id)
              GROUP BY 1, 2, 3 ORDER BY 1, 2, 3) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    size = out.stat().st_size
    if size > EXPLORE_MAX_BYTES:
        out.unlink()
        raise PublishError(f"explore.parquet is {size} bytes; the M2-04 limit is {EXPLORE_MAX_BYTES}")
    return size


PG2_MAX_BYTES = 1024 * 1024  # M2-04: pre-aggregated PG-2 JSON (ADR-009 fallback), served gzip by CloudFront
_PG2_COLS = ("requests", "llm_cost_usd", "agent_compute_usd", "vector_usd", "network_observability_usd", "third_party_usd",
             "cost_to_serve_usd")


def build_pg2(gold: Path, run_id: str) -> dict:
    """PG-2 cost-to-serve explorer data, pre-aggregated in the pipeline (ADR-009 fallback: DuckDB-WASM needs the
    parquet extension from a public CDN, which the ADR rules out). Sums only; every view totals to `fct_cost_to_serve`.
    """
    g = Path(gold)
    con = duckdb.connect()
    base = (f"FROM read_parquet('{g}/fct_cost_to_serve.parquet') c "
            f"LEFT JOIN read_parquet('{g}/dim_feature.parquet') f USING (feature_id)")
    sums = ", ".join(f"sum(c.{c})" for c in _PG2_COLS)

    def view(keys: list[str], names: list[str]) -> list[dict]:
        sel = ", ".join(keys)
        rows = con.execute(f"SELECT {sel}, {sums} {base} GROUP BY {sel} ORDER BY {sel}").fetchall()
        out = []
        for r in rows:
            d = {n: (v.isoformat() if hasattr(v, "isoformat") else v) for n, v in zip(names, r[:len(names)], strict=True)}
            d["requests"] = int(r[len(names)])
            d.update({c: _money(v) for c, v in zip(_PG2_COLS[1:], r[len(names) + 1:], strict=True)})
            out.append(d)
        return out

    names = {r[0]: r[1] for r in con.execute(f"SELECT feature_id, any_value(feature_name) {base} GROUP BY feature_id").fetchall()}
    by_feature = view(["c.feature_id"], ["feature_id"])
    for r in by_feature:
        r["feature_name"] = names.get(r["feature_id"])
    waterfall = [{"tenant_id": r[0], "revenue_usd": _money(r[1]), "discount_usd": _money(r[2]), "llm_cost_usd": _money(r[3]),
                  "infra_cost_usd": _money(r[4]), "margin_usd": _money(r[5])}
                 for r in con.execute(f"""
        SELECT tenant_id, sum(revenue_usd), sum(discount_usd), sum(llm_cost_usd), sum(infra_cost_usd), sum(margin_usd)
        FROM read_parquet('{g}/fct_m2_tenant_margin.parquet') GROUP BY 1 ORDER BY sum(margin_usd), 1""").fetchall()]
    coverage = [{"month": r[0].isoformat(), "allocated_usd": _money(r[1]), "unallocated_usd": _money(r[2]),
                 "coverage": _ratio(Decimal(r[1]), Decimal(r[1]) + Decimal(r[2]))}
                for r in con.execute(f"""
        SELECT date_trunc('month', cost_date)::DATE, coalesce(sum(allocated_cost_usd) FILTER (WHERE rule_id <> 'UNALLOCATED'), 0),
               coalesce(sum(allocated_cost_usd) FILTER (WHERE rule_id = 'UNALLOCATED'), 0)
        FROM read_parquet('{g}/fct_infra_cost_allocated.parquet') GROUP BY 1 ORDER BY 1""").fetchall()]
    by_tenant = view(["c.tenant_id"], ["tenant_id"])
    usage = {r["tenant_id"]: r["requests"] for r in by_tenant}
    for w in waterfall:
        w["requests"] = usage.get(w["tenant_id"], 0)  # usage axis of the margin-vs-usage scatter
    return {"schema_version": "pg2.v0", "run_id": run_id, "data_label": "synthetic",
            "margin_waterfall": waterfall, "attribution_by_month": coverage,
            "by_tenant": by_tenant, "by_feature": by_feature,
            "by_month": view(["date_trunc('month', c.cost_date)::DATE"], ["month"]),
            "by_tenant_feature": view(["c.tenant_id", "c.feature_id"], ["tenant_id", "feature_id"])}


def margin_forecast(recent: list[tuple], fc: list[tuple]) -> dict:
    """Forecast margin % band: trailing daily AI revenue (mean of the last 30 days, held flat) minus the COGS forecast.

    Higher cost means lower margin, so the P90 cost gives the low end of the margin band.
    """
    if not recent or not fc:
        return {"assumption": "no recent revenue or no forecast", "points": []}
    rev = sum((Decimal(r[0]) for r in recent), Decimal(0)) / len(recent)
    pts = [{"date": r[1].isoformat(), "low": _ratio(rev - Decimal(r[4]), rev), "mid": _ratio(rev - Decimal(r[3]), rev),
            "high": _ratio(rev - Decimal(r[2]), rev)} for r in fc]
    return {"assumption": "daily AI revenue held at the last-30-day mean; cost from the P10/P50/P90 COGS forecast",
            "daily_revenue_usd": _money(rev), "points": pts}


def publish(data_root: Path, run_id: str, ingest_date: str) -> dict:
    root = Path(data_root)
    snapshot = build_pg1(root / "gold", run_id, ingest_date)
    body = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode()
    if len(body) > MAX_BYTES:
        raise PublishError(f"pg1.json is {len(body)} bytes; the §7.5 limit is {MAX_BYTES}")
    explore = None
    if _m2_marts_present(root / "gold"):
        explore = write_explore_parquet(root / "gold", root / "publish" / "latest" / "explore.parquet")
    if explore is not None:
        pg2 = json.dumps(build_pg2(root / "gold", run_id), separators=(",", ":"), allow_nan=False).encode()
        if len(pg2) > PG2_MAX_BYTES:
            raise PublishError(f"pg2.json is {len(pg2)} bytes; the M2-04 limit is {PG2_MAX_BYTES}")
        (root / "publish" / "latest" / "pg2.json").write_bytes(pg2)
    paths = [root / "publish" / "latest" / "pg1.json", root / "publish" / "history" / ingest_date / "pg1.json"]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return {"bytes": len(body), "files": [str(p.relative_to(root)) for p in paths], "days": snapshot["window"]["days"],
            **({"explore_bytes": explore} if explore is not None else {})}


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


def m2_feature_costs(gold: Path) -> list[dict]:
    """Fully loaded cost to serve per feature over the whole window, by component (fct_cost_to_serve + dim_feature).

    Revenue is booked per tenant, not per feature, so this is cost and share of cost, not a per-feature margin %.
    """
    g = Path(gold)
    rows = duckdb.connect().execute(f"""
        SELECT c.feature_id, any_value(f.feature_name), sum(c.requests), sum(c.llm_cost_usd), sum(c.agent_compute_usd),
               sum(c.vector_usd), sum(c.network_observability_usd), sum(c.third_party_usd), sum(c.cost_to_serve_usd)
        FROM read_parquet('{g}/fct_cost_to_serve.parquet') c
        LEFT JOIN read_parquet('{g}/dim_feature.parquet') f USING (feature_id)
        GROUP BY c.feature_id ORDER BY c.feature_id""").fetchall()
    total = sum((Decimal(r[8]) for r in rows), Decimal(0))
    return [{"feature_id": r[0], "feature_name": r[1], "requests": int(r[2]), "llm_cost_usd": _money(r[3]),
             "agent_compute_usd": _money(r[4]), "vector_usd": _money(r[5]), "network_observability_usd": _money(r[6]),
             "third_party_usd": _money(r[7]), "cost_to_serve_usd": _money(r[8]), "cost_share": _ratio(Decimal(r[8]), total)}
            for r in rows]


def m2_at_risk(gold: Path, top: int = 10) -> dict:
    """Tenants with a negative fully loaded margin over the whole window, and the current ARR they carry.

    ARR is the current `dim_tenant` row (`arr_usd` + `ai_addon_arr_usd`); the worst `top` tenants are listed.
    """
    g = Path(gold)
    rows = duckdb.connect().execute(f"""
        WITH m AS (SELECT tenant_id, sum(revenue_usd) AS rev, sum(cost_to_serve_usd) AS cost, sum(margin_usd) AS margin
                   FROM read_parquet('{g}/fct_m2_tenant_margin.parquet') GROUP BY tenant_id),
             t AS (SELECT tenant_id, any_value(plan) AS plan, sum(arr_usd + ai_addon_arr_usd) AS arr
                   FROM read_parquet('{g}/dim_tenant.parquet') WHERE is_current GROUP BY tenant_id)
        SELECT m.tenant_id, t.plan, coalesce(t.arr, 0), m.rev, m.cost, m.margin
        FROM m LEFT JOIN t USING (tenant_id) WHERE m.margin < 0 ORDER BY m.margin, m.tenant_id""").fetchall()
    return {
        "unprofitable_tenants": len(rows),
        "arr_at_risk_usd": _money(sum((Decimal(r[2]) for r in rows), Decimal(0))),
        "worst": [{"tenant_id": r[0], "plan": r[1], "arr_usd": _money(r[2]), "revenue_usd": _money(r[3]),
                   "cost_to_serve_usd": _money(r[4]), "margin_usd": _money(r[5])} for r in rows[:top]],
    }
