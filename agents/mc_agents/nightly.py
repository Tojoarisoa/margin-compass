"""Nightly margin review, step 1 (M5-01, PLAN.md §8.5): deterministic fan-out, rank and write.

Reads the gold marts, drafts ACT-1 (open margin leaks) and ACT-3 (loss-making tenants) actions, ranks them by
margin $ x confidence / effort, and writes `fct_actions.parquet` and `publish/latest/margin_brief.json`.
No LLM call is made here (specialist investigation and the batched low-severity summary come in later steps),
so the nightly LLM spend of this step is $0. Every figure is computed in Decimal from the marts; the brief
copies those figures and invents none. Actions are drafts: status is always `proposed` (AG-09 approves them).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

CENT = Decimal("0.01")
MONTH_DAYS = 30
TRAILING_DAYS = 28
MAX_ACTIONS = 50
BRIEF_TOP = 5
ASSUMPTIONS = "Impact is the trailing run-rate x 30 days; confidence and effort are v1 heuristics, not measured."

# Approver roles named in PLAN.md §8.4 (ACT-1 Head of AI Platform, ACT-3 RevOps / CS lead).
APPROVER = {"ACT-1": "head_of_ai_platform", "ACT-3": "revops_lead"}

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


def _q(x: Decimal) -> Decimal:
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def _money(x: Decimal) -> str:
    q = _q(x)
    return f"-${-q:,}" if q < 0 else f"${q:,}"


def _action(run_id: str, kind: str, target: str, title: str, impact: Decimal, confidence: Decimal, effort: int,
            quality: str, risk: str) -> Action:
    aid = "act-" + hashlib.sha256(f"{run_id}|{kind}|{target}".encode()).hexdigest()[:12]
    return Action(aid, run_id, kind, target, title, _q(impact), confidence, effort, _q(impact * confidence / effort),
                  quality, risk, "proposed", APPROVER[kind], ASSUMPTIONS)


def _leak_actions(con: duckdb.DuckDBPyConnection, gold: Path, run_id: str) -> list[Action]:
    path = gold / "fct_margin_leaks.parquet"
    if not path.exists():
        return []
    rows = con.execute(f"""
        SELECT feature_id, metric, sum(impact_usd_per_day), max(peak_ratio)
        FROM read_parquet('{path}') WHERE status = 'open' AND impact_usd_per_day > 0
        GROUP BY feature_id, metric ORDER BY feature_id, metric""").fetchall()
    out = []
    for feature, metric, per_day, peak in rows:
        conf = Decimal("0.80") if peak >= 3 else Decimal("0.60")
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


def review(gold: Path, run_id: str) -> list[Action]:
    """Fan out, deduplicate and rank (highest score first, ties by action id)."""
    con = duckdb.connect()
    con.execute("SET threads = 1")
    found = {a.action_id: a for a in _leak_actions(con, Path(gold), run_id) + _tenant_actions(con, Path(gold), run_id)}
    ranked = sorted(found.values(), key=lambda a: (-a.score, a.action_id))
    return ranked[:MAX_ACTIONS]


def build_brief(actions: list[Action], run_id: str) -> dict:
    total = sum((a.impact_usd_month for a in actions), Decimal(0))
    top = actions[:BRIEF_TOP]
    headline = (f"{len(actions)} proposed actions with {_money(total)} of monthly margin at stake."
                if actions else "No margin actions proposed tonight.")
    return {"schema_version": "brief.v0", "run_id": run_id, "data_label": "synthetic", "llm_calls": 0, "headline": headline,
            "action_count": len(actions), "total_impact_usd_month": _money(total),
            "top_actions": [{"action_id": a.action_id, "action_type": a.action_type, "title": a.title,
                             "impact_usd_month": _money(a.impact_usd_month), "approver": a.approver} for a in top]}


def write(data_root: Path, run_id: str) -> list[str]:
    """Write gold/fct_actions.parquet and publish/latest/margin_brief.json; returns the published keys."""
    root = Path(data_root)
    actions = review(root / "gold", run_id)
    table = pa.Table.from_pylist([asdict(a) for a in actions], schema=SCHEMA.with_metadata({b"synthetic": b"true"}))
    pq.write_table(table, root / "gold" / "fct_actions.parquet", compression="zstd")
    out = root / "publish" / "latest" / "margin_brief.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_brief(actions, run_id), separators=(",", ":"), allow_nan=False))
    return ["publish/latest/margin_brief.json"]
