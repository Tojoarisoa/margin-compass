"""Subscriptions and monthly invoices (source S3), exact to the cent for the revenue preservation
check (M1-03). Seat subscription and flat AI add-on are billed monthly in advance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .config import SimConfig
from .tenants import CENT, Tenant


@dataclass(frozen=True)
class InvoiceLine:
    invoice_id: str
    tenant_id: str
    billing_period_start: date
    billing_period_end: date  # exclusive
    line_type: str  # "subscription" | "ai_addon"
    amount_usd: Decimal


def _next_month(d: date) -> date:
    return date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def _month_starts(cfg: SimConfig) -> list[date]:
    months, d = [], cfg.start.replace(day=1)
    while d <= cfg.end:
        months.append(d)
        d = _next_month(d)
    return months


def generate_invoices(cfg: SimConfig, tenants: list[Tenant]) -> list[InvoiceLine]:
    lines: list[InvoiceLine] = []
    for month in _month_starts(cfg):
        for t in tenants:
            keep = Decimal(1) - t.discount_pct
            seat_arr = t.arr_usd - t.ai_addon_arr_usd
            invoice_id = f"inv-{month:%Y%m}-{t.tenant_id}"
            for line_type, annual in (("subscription", seat_arr), ("ai_addon", t.ai_addon_arr_usd)):
                lines.append(
                    InvoiceLine(
                        invoice_id=invoice_id,
                        tenant_id=t.tenant_id,
                        billing_period_start=month,
                        billing_period_end=_next_month(month),
                        line_type=line_type,
                        amount_usd=(annual / 12 * keep).quantize(CENT, ROUND_HALF_UP),
                    )
                )
    return lines
