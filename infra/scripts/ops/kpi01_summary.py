"""Print the AI gross margin (KPI-01) from a published pg1.json (ops verify-backfill; M6-04 case study input).

Usage: kpi01_summary.py <pg1.json>. Prints the whole window, the first and last 30 days of the daily trend, and the
change in margin points between them. Sums revenue and cost first, then takes the ratio (no averaging of daily %s).
Standard library only (Decimal), so the numbers are exact to the cent the snapshot carries.
"""
from __future__ import annotations

import json
import sys
from decimal import ROUND_HALF_UP, Decimal

SPAN = 30


def margin(rows: list[dict]) -> dict:
    rev = sum((Decimal(str(r["ai_revenue_usd"])) for r in rows), Decimal(0))
    cost = sum((Decimal(str(r["ai_cost_to_serve_usd"])) for r in rows), Decimal(0))
    pct = ((rev - cost) / rev * 100).quantize(Decimal("0.01"), ROUND_HALF_UP) if rev else None
    return {"from": rows[0]["date"], "to": rows[-1]["date"], "days": len(rows), "ai_revenue_usd": str(rev),
            "ai_cost_to_serve_usd": str(cost), "ai_gross_margin_pct": None if pct is None else str(pct)}


def summary(pg1: dict) -> dict:
    trend = sorted(pg1.get("trend") or [], key=lambda r: r["date"])
    if not trend:
        return {"error": "pg1.json has no trend"}
    first, last = margin(trend[:SPAN]), margin(trend[-SPAN:])
    delta = None
    if first["ai_gross_margin_pct"] is not None and last["ai_gross_margin_pct"] is not None:
        delta = str(Decimal(last["ai_gross_margin_pct"]) - Decimal(first["ai_gross_margin_pct"]))
    return {"run_id": pg1.get("run_id"), "data_label": pg1.get("data_label"), "window": margin(trend),
            "first_30_days": first, "last_30_days": last, "change_pts": delta,
            "unprofitable_tenants": (pg1.get("headline") or {}).get("unprofitable_tenants"),
            "tenants": (pg1.get("headline") or {}).get("tenants")}


def compare(base: dict, approved: dict) -> dict:
    """KPI-01 margin points recovered: approved run minus counterfactual run, same seed (ops realized-check).

    Both inputs are pg1 snapshots. The change is taken over the last 30 days (effects start after approval) and over the
    whole window; positive means the approved actions raised the AI gross margin.
    """
    b, a = summary(base), summary(approved)
    if "error" in b or "error" in a:
        return {"error": b.get("error") or a.get("error")}

    def pts(key: str) -> str | None:
        x, y = b[key]["ai_gross_margin_pct"], a[key]["ai_gross_margin_pct"]
        return None if x is None or y is None else str(Decimal(y) - Decimal(x))

    return {"data_label": approved.get("data_label"), "counterfactual": {k: b[k] for k in ("window", "last_30_days")},
            "approved": {k: a[k] for k in ("window", "last_30_days")},
            "recovered_pts_last_30_days": pts("last_30_days"), "recovered_pts_window": pts("window")}


def main(path: str) -> int:
    with open(path) as f:
        out = summary(json.load(f))
    print(json.dumps(out, indent=1))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
