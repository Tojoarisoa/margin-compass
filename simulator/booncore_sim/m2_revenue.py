"""M2-02 step 1c: monthly invoices for the M2 tenants (source S3), exact to the cent.

Seat subscription and the flat AI add-on are billed monthly in advance at gross list price; the contract
discount is its own negative line, so the silver layer can show gross revenue and discounts separately.
The price in force on the first day of a billing month comes from the SCD2 plan history. Parameters marked
(assumption) are labeled inputs. Not wired into the CLI. All output is synthetic.

Not simulated yet: overage charges (every tenant bills a flat add-on, so overage is 0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .m2_tenants import CENT, MONTHS, M2Tenant, TenantVersion, _month_start


@dataclass(frozen=True)
class M2InvoiceLine:
    invoice_id: str
    tenant_id: str
    billing_period_start: date
    billing_period_end: date  # exclusive
    line_type: str  # subscription | ai_addon | discount
    amount_usd: Decimal  # negative for discount


def _month_end(start: date) -> date:
    return date(start.year + (start.month == 12), start.month % 12 + 1, 1)


def _version_on(versions: list[TenantVersion], day: date) -> TenantVersion:
    for v in versions:
        if v.valid_from <= day and (v.valid_to is None or day < v.valid_to):
            return v
    raise KeyError(f"no tenant version on {day}")


def generate_invoices(tenants: list[M2Tenant], history: list[TenantVersion]) -> list[M2InvoiceLine]:
    """One invoice per tenant per month, from the month containing onboarding (assumption: the first month is
    billed in full, no proration)."""
    by_tenant: dict[str, list[TenantVersion]] = {}
    for v in history:
        by_tenant.setdefault(v.tenant_id, []).append(v)
    lines: list[M2InvoiceLine] = []
    for i in range(MONTHS):
        start, end = _month_start(i), _month_end(_month_start(i))
        for t in tenants:
            if t.onboarded_on >= end:
                continue
            v = _version_on(by_tenant[t.tenant_id], max(start, t.onboarded_on))
            seat = ((v.arr_usd - v.ai_addon_arr_usd) / 12).quantize(CENT, ROUND_HALF_UP)
            addon = (v.ai_addon_arr_usd / 12).quantize(CENT, ROUND_HALF_UP)
            discount = -((seat + addon) * v.discount_pct).quantize(CENT, ROUND_HALF_UP)
            invoice_id = f"inv-{start:%Y%m}-{t.tenant_id}"
            for line_type, amount in (("subscription", seat), ("ai_addon", addon), ("discount", discount)):
                lines.append(M2InvoiceLine(invoice_id, t.tenant_id, start, end, line_type, amount))
    return lines


__all__ = ["M2InvoiceLine", "generate_invoices"]
