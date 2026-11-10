"""Nightly margin review, step 1 (M5-01, PLAN.md §8.5): deterministic fan-out, rank and write.

Reads the gold marts, drafts ACT-1 (open margin leaks), ACT-2 (plans under the margin target) and ACT-3 (loss-making tenants) actions, ranks them by
margin $ x confidence / effort, and writes `fct_actions.parquet` and `publish/latest/margin_brief.json`.
No LLM call is made here (specialist investigation and the batched low-severity summary come in later steps),
so the nightly LLM spend of this step is $0. Every figure is computed in Decimal from the marts; the brief
copies those figures and invents none. Actions are drafts: status is always `proposed` (AG-09 approves them).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

CENT = Decimal("0.01")
MONTH_DAYS = 30
TRAILING_DAYS = 28
MAX_ACTIONS = 50
DETERIORATION_PP = Decimal("5")  # margin % fall (points) versus the previous 28 days that counts as deteriorating
RENEWAL_DAYS = 90
RENEWAL_TARGET_PCT = Decimal("30")  # renewals below this 28-day margin % are drafted for an account action
RECENT_LEAK_CONF = Decimal("0.40")  # a leak detected in the last 28 days but already closed
PLAN_MIN_TENANTS = 2  # a pricing draft needs a plan with at least this many tenants, so one account cannot drive it
BRIEF_TOP = 5
ASSUMPTIONS = "Impact is the trailing run-rate x 30 days; confidence and effort are v1 heuristics, not measured."

# Approver roles named in PLAN.md §8.4 (ACT-1 Head of AI Platform, ACT-3 RevOps / CS lead).
APPROVER = {"ACT-1": "head_of_ai_platform", "ACT-2": "pricing_committee", "ACT-3": "revops_lead"}

SCHEMA = pa.schema([
    ("action_id", pa.string()), ("run_id", pa.string()), ("action_type", pa.string()), ("target", pa.string()),
    ("title", pa.string()), ("impact_usd_month", pa.decimal128(18, 2)), ("confidence", pa.decimal128(4, 2)),
    ("effort", pa.int32()), ("score", pa.decimal128(18, 2)), ("quality_impact", pa.string()), ("risk", pa.string()),
    ("status", pa.string()), ("approver", pa.string()), ("assumptions", pa.string()),
])


@dataclass(frozen=True)
class Action:
    action_id: str
    run_id: str
    action_type: str
    target: str
    title: str
    impact_usd_month: Decimal
    confidence: Decimal
    effort: int
    score: Decimal
    quality_impact: str
    risk: str
    status: str
    approver: str
    assumptions: str
    renewal_date: str = ""  # ISO date, only for renewal actions; shown in the Action Center calendar, not stored in the mart


def _q(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def _money(x: Decimal) -> str:
    q = _q(x)
    return f"-${-q:,}" if q < 0 else f"${q:,}"


def _action(run_id: str, kind: str, target: str, title: str, impact: Decimal, confidence: Decimal, effort: int,
            quality: str, risk: str, renewal_date: str = "") -> Action:
    aid = "act-" + hashlib.sha256(f"{run_id}|{kind}|{target}".encode()).hexdigest()[:12]
    return Action(aid, run_id, kind, target, title, _q(impact), confidence, effort, _q(impact * confidence / effort),
                  quality, risk, "proposed", APPROVER[kind], ASSUMPTIONS, renewal_date)


def _leak_actions(con: duckdb.DuckDBPyConnection, gold: Path, run_id: str) -> list[Action]:
    path = gold / "fct_margin_leaks.parquet"
    if not path.exists():
        return []
    rows = con.execute(f"""
        SELECT feature_id, metric, sum(impact_usd_per_day), max(peak_ratio)
        FROM read_parquet('{path}') WHERE status = 'open' AND impact_usd_per_day > 0
        GROUP BY feature_id, metric ORDER BY feature_id, metric""").fetchall()
    recent = con.execute(f"""
        WITH last AS (SELECT max(start_date) AS d FROM read_parquet('{path}'))
        SELECT feature_id, metric, sum(impact_usd_per_day), max(peak_ratio)
        FROM read_parquet('{path}'), last
        WHERE status <> 'open' AND impact_usd_per_day > 0 AND start_date > last.d - INTERVAL {TRAILING_DAYS} DAY
        GROUP BY feature_id, metric ORDER BY feature_id, metric""").fetchall()
    out = []
    open_keys = {(f, m) for f, m, _d, _p in rows}
    rows = rows + [r for r in recent if (r[0], r[1]) not in open_keys]
    closed_keys = {(f, m) for f, m, _d, _p in recent} - open_keys
    for feature, metric, per_day, peak in rows:
        conf = RECENT_LEAK_CONF if (feature, metric) in closed_keys else (
            Decimal("0.80") if peak >= 3 else Decimal("0.60"))
        out.append(_action(run_id, "ACT-1", f"{feature}/{metric}",
                           f"Investigate the open {metric} leak on {feature} and apply the cheapest routing or caching lever",
                           Decimal(per_day) * MONTH_DAYS, conf, 2, "Replay the lever against the quality guardrail first",
                           "low"))
    return out


def _tenant_actions(con: duckdb.DuckDBPyConnection, gold: Path, run_id: str) -> list[Action]:
    path = gold / "fct_m2_tenant_margin.parquet"
    if not path.exists():
        return []
    rows = con.execute(f"""
        WITH last AS (SELECT max(margin_date) AS d FROM read_parquet('{path}'))
        SELECT tenant_id, sum(margin_usd), sum(revenue_usd)
        FROM read_parquet('{path}'), last WHERE margin_date > last.d - INTERVAL {TRAILING_DAYS} DAY
        GROUP BY tenant_id HAVING sum(margin_usd) < 0 ORDER BY tenant_id""").fetchall()
    out = []
    for tenant, margin, _rev in rows:
        monthly = -Decimal(margin) * MONTH_DAYS / TRAILING_DAYS
        out.append(_action(run_id, "ACT-3", tenant,
                           f"Review the contract and usage of {tenant}, which lost money over the last {TRAILING_DAYS} days",
                           monthly, Decimal("0.50"), 3, "No change to the product", "medium"))
    return out


def _windows(con: duckdb.DuckDBPyConnection, gold: Path):
    """Per tenant: revenue and margin of the last 28 days and of the 28 days before, plus the latest date."""
    path = gold / "fct_m2_tenant_margin.parquet"
    if not path.exists():
        return None, []
    rows = con.execute(f"""
        WITH last AS (SELECT max(margin_date) AS d FROM read_parquet('{path}'))
        SELECT last.d, tenant_id,
          sum(revenue_usd) FILTER (margin_date > last.d - INTERVAL {TRAILING_DAYS} DAY),
          sum(margin_usd) FILTER (margin_date > last.d - INTERVAL {TRAILING_DAYS} DAY),
          sum(revenue_usd) FILTER (margin_date <= last.d - INTERVAL {TRAILING_DAYS} DAY
                                   AND margin_date > last.d - INTERVAL {2 * TRAILING_DAYS} DAY),
          sum(margin_usd) FILTER (margin_date <= last.d - INTERVAL {TRAILING_DAYS} DAY
                                  AND margin_date > last.d - INTERVAL {2 * TRAILING_DAYS} DAY)
        FROM read_parquet('{path}'), last GROUP BY last.d, tenant_id ORDER BY tenant_id""").fetchall()
    return (rows[0][0] if rows else None), rows


def _pct(margin, revenue) -> Decimal | None:
    return Decimal(margin) * 100 / Decimal(revenue) if revenue else None


def _next_renewal(base: date, today: date) -> date:
    """Contracts renew every year: the first anniversary of `base` on or after `today`."""
    year = max(base.year, today.year)
    for y in (year, year + 1):
        try:
            due = base.replace(year=y)
        except ValueError:  # 29 February
            due = base.replace(year=y, day=28)
        if due >= today:
            return due
    return due


def _plan_actions(con, gold: Path, run_id: str) -> list[Action]:
    """ACT-2 for plans (current plan of each tenant) whose pooled 28-day margin % is below RENEWAL_TARGET_PCT."""
    path, dim = gold / "fct_m2_tenant_margin.parquet", gold / "dim_tenant.parquet"
    if not path.exists() or not dim.exists():
        return []
    if "plan" not in {r[0] for r in con.execute(f"SELECT name FROM parquet_schema('{dim}')").fetchall()}:
        return []
    rows = con.execute(f"""
        WITH last AS (SELECT max(margin_date) AS d FROM read_parquet('{path}')),
        cur AS (SELECT tenant_id, max(plan) AS plan_name FROM read_parquet('{dim}') WHERE is_current GROUP BY tenant_id)
        SELECT cur.plan_name, count(DISTINCT m.tenant_id), sum(m.revenue_usd), sum(m.margin_usd)
        FROM read_parquet('{path}') m, last JOIN cur ON cur.tenant_id = m.tenant_id
        WHERE m.margin_date > last.d - INTERVAL {TRAILING_DAYS} DAY
        GROUP BY cur.plan_name ORDER BY cur.plan_name""").fetchall()
    out = []
    for plan, n, rev, mar in rows:
        if n < PLAN_MIN_TENANTS or not rev:
            continue
        now = _pct(mar, rev)
        if now >= RENEWAL_TARGET_PCT:
            continue
        gap = (RENEWAL_TARGET_PCT - now) / 100 * Decimal(rev) * MONTH_DAYS / TRAILING_DAYS
        out.append(_action(run_id, "ACT-2", f"plan/{plan}",
                           f"Plan {plan} runs at {now:.1f}% margin across {n} tenants; draft a pricing or packaging change "
                           f"(included usage, overage) to reach {RENEWAL_TARGET_PCT}%",
                           gap, Decimal("0.30"), 4, "Model the churn and downgrade response before the committee decides",
                           "high"))
    return out


def _trend_actions(con, gold: Path, run_id: str) -> list[Action]:
    """ACT-3 for tenants still profitable whose 28-day margin % fell by DETERIORATION_PP or more."""
    _d, rows = _windows(con, gold)
    out = []
    for _d2, tenant, rev, mar, prev_rev, prev_mar in rows:
        now, before = _pct(mar or 0, rev), _pct(prev_mar or 0, prev_rev)
        if now is None or before is None or Decimal(mar) < 0 or before - now < DETERIORATION_PP:
            continue
        monthly = (before - now) / 100 * Decimal(rev) * MONTH_DAYS / TRAILING_DAYS
        out.append(_action(run_id, "ACT-3", f"{tenant}/margin-trend",
                           f"Margin of {tenant} fell from {before:.1f}% to {now:.1f}% over the last {TRAILING_DAYS} days; "
                           "find the usage or cost driver and agree a fix",
                           monthly, Decimal("0.40"), 3, "No change to the product", "medium"))
    return out


def _renewal_actions(con, gold: Path, run_id: str) -> list[Action]:
    """ACT-3 for tenants renewing within RENEWAL_DAYS whose 28-day margin % is below target or falling."""
    last, rows = _windows(con, gold)
    dim = gold / "dim_tenant.parquet"
    if last is None or not dim.exists():
        return []
    renew = dict(con.execute(
        f"SELECT tenant_id, max(renewal_date) FROM read_parquet('{dim}') WHERE is_current GROUP BY tenant_id").fetchall())
    out = []
    for _d, tenant, rev, mar, prev_rev, prev_mar in rows:
        base = renew.get(tenant)
        if base is None or not rev:
            continue
        due = _next_renewal(base, last)
        days = (due - last).days
        now, before = _pct(mar or 0, rev), _pct(prev_mar or 0, prev_rev)
        falling = before is not None and now is not None and before - now >= DETERIORATION_PP
        if days > RENEWAL_DAYS or Decimal(mar) < 0 or not (now < RENEWAL_TARGET_PCT or falling):
            continue
        gap = max(Decimal(0), RENEWAL_TARGET_PCT - now) / 100 * Decimal(rev) * MONTH_DAYS / TRAILING_DAYS
        out.append(_action(run_id, "ACT-3", f"{tenant}/renewal",
                           f"{tenant} renews in {days} days with a {now:.1f}% margin; prepare the renewal terms "
                           "(fair-use cap or price) within the discount-authority matrix",
                           gap, Decimal("0.50"), 2, "No change to the product", "medium", due.isoformat()))
    return out


def review(gold: Path, run_id: str) -> list[Action]:
    """Fan out, deduplicate and rank (highest score first, ties by action id)."""
    con = duckdb.connect()
    con.execute("SET threads = 1")
    g = Path(gold)
    found = {a.action_id: a for a in (_leak_actions(con, g, run_id) + _tenant_actions(con, g, run_id)
                                      + _trend_actions(con, g, run_id) + _renewal_actions(con, g, run_id)
                                      + _plan_actions(con, g, run_id))}
    ranked = sorted(found.values(), key=lambda a: (-a.score, a.action_id))
    return ranked[:MAX_ACTIONS]


def build_brief(actions: list[Action], run_id: str, insights: dict[str, str] | None = None) -> dict:
    total = sum((a.impact_usd_month for a in actions), Decimal(0))
    top = actions[:BRIEF_TOP]
    headline = (f"{len(actions)} proposed actions with {_money(total)} of monthly margin at stake."
                if actions else "No margin actions proposed tonight.")
    return {"schema_version": "brief.v0", "run_id": run_id, "data_label": "synthetic", "headline": headline,
            "action_count": len(actions), "total_impact_usd_month": _money(total),
            "top_actions": [{"action_id": a.action_id, "action_type": a.action_type, "title": a.title,
                             "impact_usd_month": _money(a.impact_usd_month), "approver": a.approver,
                             **({"insight": insights[a.action_id]} if insights and a.action_id in insights else {})}
                            for a in top]}


def build_queue(actions: list[Action], run_id: str, insights: dict[str, str] | None = None) -> dict:
    """PG-7 Action Center queue: every proposed action, grouped by the dashboard into approver-role queues."""
    return {"schema_version": "actions.v0", "run_id": run_id, "data_label": "synthetic",
            "actions": [{"action_id": a.action_id, "action_type": a.action_type, "target": a.target, "title": a.title,
                         "impact_usd_month": _money(a.impact_usd_month), "confidence": str(a.confidence), "effort": a.effort,
                         "quality_impact": a.quality_impact, "risk": a.risk, "status": a.status, "approver": a.approver,
                         "assumptions": a.assumptions,
                         **({"renewal_date": a.renewal_date} if a.renewal_date else {}),
                         **({"insight": insights[a.action_id]} if insights and a.action_id in insights else {})}
                        for a in actions]}


def write(data_root: Path, run_id: str, client=None) -> list[str]:
    """Write gold/fct_actions.parquet and publish/latest/margin_brief.json; returns the published keys.

    With an LLM `client` the top actions are also investigated (investigate.py, capped at $0.50 a night) and the
    findings are added to the brief and to episodic memory. Without one (the default, CI and the build) no LLM is called.
    A failed investigation never blocks the brief.
    """
    root = Path(data_root)
    actions = review(root / "gold", run_id)
    insights: dict[str, str] = {}
    if client is not None:
        from . import investigate  # local import: investigate imports Action from this module
        try:
            mem = root / "memory" / "episodic.jsonl"
            res = investigate.investigate(actions, client, memory=investigate.load_memory(mem))
            investigate.remember(mem, run_id, res.insights)
            insights = {i.action_id: i.text for i in res.insights}
        except Exception:  # noqa: BLE001 - the deterministic brief must still be written
            insights = {}
    table = pa.Table.from_pylist([{k: v for k, v in asdict(a).items() if k != "renewal_date"} for a in actions], schema=SCHEMA.with_metadata({b"synthetic": b"true"}))
    pq.write_table(table, root / "gold" / "fct_actions.parquet", compression="zstd")
    out = root / "publish" / "latest" / "margin_brief.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_brief(actions, run_id, insights), separators=(",", ":"), allow_nan=False))
    queue = root / "publish" / "latest" / "actions.json"
    queue.write_text(json.dumps(build_queue(actions, run_id, insights), separators=(",", ":"), allow_nan=False))
    return ["publish/latest/margin_brief.json", "publish/latest/actions.json"]
