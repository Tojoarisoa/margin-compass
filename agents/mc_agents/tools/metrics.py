"""Deterministic metric tools over the gold marts (PLAN.md §8.6 tool contracts).

Read-only, idempotent, row-limited, input-validated. All arithmetic happens here, in Decimal, never in
the LLM (AGENTS.md: no LLM arithmetic). Money is rounded half-up to the cent and percentages to two
decimals; the answer must copy these display values exactly (the verifier checks).

Guarded SQL generation (EV-05) arrives in M4-02; M1 exposes fixed, parameterized queries only.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import duckdb

_TENANT = re.compile(r"^bc-t\d{4}$")
CENT, BP = Decimal("0.01"), Decimal("0.01")
RANK_METRICS = ("gross_margin_pct", "gross_margin_usd", "cost_to_serve_usd", "ai_revenue_usd")
MAX_RANK_LIMIT = 10


class ToolError(ValueError):
    """Bad tool input. The message is returned to the model as a tool error."""


def money(x: Decimal) -> str:
    q = Decimal(x).quantize(CENT, ROUND_HALF_UP)
    return f"-${-q:,}" if q < 0 else f"${q:,}"


def pct(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == 0:
        return None
    return f"{(Decimal(numerator) * 100 / Decimal(denominator)).quantize(BP, ROUND_HALF_UP)}%"


def _date(name: str, value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


class MetricTools:
    def __init__(self, gold_dir: Path) -> None:
        self.margin = Path(gold_dir) / "fct_tenant_margin.parquet"
        if not self.margin.exists():
            raise FileNotFoundError(f"{self.margin} not found: run the pipeline first")
        self.con = duckdb.connect()
        self.con.execute("SET threads = 1")
        lo, hi = self.con.execute(f"SELECT min(margin_date), max(margin_date) FROM read_parquet('{self.margin}')").fetchall()[0]
        self.window = (lo, hi)
        self.tenants = {r[0] for r in self.con.execute(
            f"SELECT DISTINCT tenant_id FROM read_parquet('{self.margin}')").fetchall()}

    # --- shared ---------------------------------------------------------------------------------
    def _period(self, start: Any, end: Any) -> tuple[date, date]:
        s, e = _date("start_date", start), _date("end_date", end)
        if s > e:
            raise ToolError("start_date must be on or before end_date")
        lo, hi = self.window
        if e < lo or s > hi:
            raise ToolError(f"no data in {s}..{e}; gold covers {lo}..{hi}")
        return max(s, lo), min(e, hi)

    def _period_fields(self, s: date, e: date) -> dict[str, Any]:
        return {"covered_from": s.isoformat(), "covered_to": e.isoformat(), "days": (e - s).days + 1,
                "feature_scope": "F1 only (M1)", "data_label": "synthetic"}

    def _sums(self, s: date, e: date, tenant: str | None = None) -> list[tuple]:
        where = "margin_date BETWEEN ? AND ?" + (" AND tenant_id = ?" if tenant else "")
        params = [s, e] + ([tenant] if tenant else [])
        return self.con.execute(
            f"""SELECT tenant_id, sum(ai_revenue_usd), sum(cost_to_serve_usd), sum(gross_margin_usd), sum(request_count)
                FROM read_parquet('{self.margin}') WHERE {where} GROUP BY tenant_id ORDER BY tenant_id""", params,
        ).fetchall()

    @staticmethod
    def _row(tenant: str, rev: Decimal, cost: Decimal, gm: Decimal, req: int) -> dict[str, Any]:
        return {"tenant_id": tenant, "ai_revenue_usd": money(rev), "cost_to_serve_usd": money(cost),
                "gross_margin_usd": money(gm), "gross_margin_pct": pct(gm, rev), "request_count": int(req)}

    # --- tools ----------------------------------------------------------------------------------
    def tenant_margin(self, tenant_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        if not isinstance(tenant_id, str) or not _TENANT.match(tenant_id):
            raise ToolError(f"tenant_id must look like bc-t0001, got {tenant_id!r}")
        if tenant_id not in self.tenants:
            raise ToolError(f"unknown tenant {tenant_id}")
        s, e = self._period(start_date, end_date)
        rows = self._sums(s, e, tenant_id)
        return {**self._row(*rows[0]), **self._period_fields(s, e)}

    def tenant_ranking(self, metric: str, order: str, limit: int, start_date: str, end_date: str) -> dict[str, Any]:
        if metric not in RANK_METRICS:
            raise ToolError(f"metric must be one of {RANK_METRICS}")
        if order not in ("asc", "desc"):
            raise ToolError("order must be 'asc' or 'desc'")
        if not isinstance(limit, int) or not 1 <= limit <= MAX_RANK_LIMIT:
            raise ToolError(f"limit must be an integer in 1..{MAX_RANK_LIMIT}")
        s, e = self._period(start_date, end_date)
        rows = self._sums(s, e)

        def key(r):
            _, rev, cost, gm, _ = r
            value = {"gross_margin_pct": (gm / rev) if rev else Decimal("-Infinity"), "gross_margin_usd": gm,
                     "cost_to_serve_usd": cost, "ai_revenue_usd": rev}[metric]
            return value

        ranked = sorted(rows, key=lambda r: (key(r), r[0]), reverse=(order == "desc"))[:limit]
        return {"metric": metric, "order": order, "limit": limit, "tenants_considered": len(rows),
                "ranking": [{"rank": i, **self._row(*r)} for i, r in enumerate(ranked, start=1)],
                **self._period_fields(s, e)}

    def portfolio_margin(self, start_date: str, end_date: str) -> dict[str, Any]:
        s, e = self._period(start_date, end_date)
        rows = self._sums(s, e)
        rev = sum((r[1] for r in rows), Decimal(0))
        cost = sum((r[2] for r in rows), Decimal(0))
        gm = sum((r[3] for r in rows), Decimal(0))
        return {"tenants": len(rows), "ai_revenue_usd": money(rev), "cost_to_serve_usd": money(cost),
                "gross_margin_usd": money(gm), "ai_gross_margin_pct": pct(gm, rev),
                "unprofitable_tenants": sum(1 for r in rows if r[3] < 0),
                "request_count": int(sum(r[4] for r in rows)), **self._period_fields(s, e)}

    # --- schemas for the model ------------------------------------------------------------------
    def specs(self) -> list[dict[str, Any]]:
        lo, hi = self.window
        period = {
            "start_date": {"type": "string", "description": f"ISO date, inclusive. Data covers {lo} to {hi}."},
            "end_date": {"type": "string", "description": "ISO date, inclusive."},
        }

        def spec(name, description, props, required):
            return {"toolSpec": {"name": name, "description": description, "inputSchema": {"json": {
                "type": "object", "properties": props, "required": required, "additionalProperties": False}}}}

        return [
            spec("tenant_margin", "AI revenue, cost to serve, gross margin ($ and %), and requests for one tenant over a period.",
                 {"tenant_id": {"type": "string", "description": "Tenant ID like bc-t0003."}, **period},
                 ["tenant_id", "start_date", "end_date"]),
            spec("tenant_ranking", "Rank tenants by an AI margin metric over a period.",
                 {"metric": {"type": "string", "enum": list(RANK_METRICS)},
                  "order": {"type": "string", "enum": ["asc", "desc"], "description": "asc = lowest first."},
                  "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RANK_LIMIT}, **period},
                 ["metric", "order", "limit", "start_date", "end_date"]),
            spec("portfolio_margin", "Portfolio-wide AI revenue, cost to serve, AI gross margin (KPI-01), and unprofitable tenant count over a period.",
                 period, ["start_date", "end_date"]),
        ]

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = {"tenant_margin": self.tenant_margin, "tenant_ranking": self.tenant_ranking,
              "portfolio_margin": self.portfolio_margin}.get(name)
        if fn is None:
            raise ToolError(f"unknown tool {name}")
        try:
            return fn(**args)
        except TypeError as exc:
            raise ToolError(f"bad arguments for {name}: {exc}") from None
