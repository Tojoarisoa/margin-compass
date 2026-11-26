"""M2-02 step 1c: monthly invoices for the M2 tenants (source S3), exact to the cent.

Seat subscription and the flat AI add-on are billed monthly in advance at gross list price; the contract
discount is its own negative line, so the silver layer can show gross revenue and discounts separately.
The price in force on the first day of a billing month comes from the SCD2 plan history. Parameters marked
(assumption) are labeled inputs. Not wired into the CLI. All output is synthetic.

Not simulated yet: overage charges (every tenant bills a flat add-on, so overage is 0).

M5-04: an approved ACT-2 "plan/<plan>" raises the AI add-on line of that plan's tenants by `ACT2_ADDON_UPLIFT` from
the action's explicit effective date (`m5_effects.effective_on`); a month the date falls inside is prorated by day
(assumption), so the invoices carry the same uplift the realized rows count. Without approvals nothing changes.
An approved ACT-3 whose account churns (`m5_effects.churn_day`, seeded) stops that tenant's invoices from the churn
day: no invoice for a month starting on or after it, the month it falls inside billed for the days before it
(prorated by day, assumption), as the realized rows count the loss from that day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .m2_tenants import CENT, MONTHS, M2Tenant, TenantVersion, _month_start
from .m5_effects import ACT2_ADDON_UPLIFT, Approval, churn_day, effective_on, plan_of


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


def uplift_share(approvals: list[Approval], plan: str, start: date, end: date) -> Decimal:
    """Add-on uplift factor for one billing period [start, end) of a tenant on `plan`: the sum over approved ACT-2
    "plan/<plan>" actions of uplift x share of the period's days on or after the effective date."""
    days = (end - start).days
    total = Decimal(0)
    for a in approvals:
        if plan_of(a) == plan:
            on = (end - max(start, effective_on(a))).days
            if on > 0:
                total += Decimal(str(ACT2_ADDON_UPLIFT)) * Decimal(min(on, days)) / Decimal(days)
    return total


def churned_on(approvals: list[Approval], seed: int) -> dict[str, date]:
    """tenant_id -> first day without service, for approved ACT-3 actions whose account churns (earliest wins)."""
    out: dict[str, date] = {}
    for a in approvals:
        if a.action_type == "ACT-3":
            cd = churn_day(seed, a)
            tenant = a.target.split("/")[0]
            if cd is not None and (tenant not in out or cd < out[tenant]):
                out[tenant] = cd
    return out


def generate_invoices(
    tenants: list[M2Tenant], history: list[TenantVersion], approvals: list[Approval] | None = None, seed: int = 0
) -> list[M2InvoiceLine]:
    """One invoice per tenant per month, from the month containing onboarding (assumption: the first month is
    billed in full, no proration). `approvals` (M5-04): ACT-2 plan price changes raise the add-on line; an ACT-3
    churn (seeded with `seed`, as in the telemetry) ends the tenant's invoices from the churn day."""
    by_tenant: dict[str, list[TenantVersion]] = {}
    for v in history:
        by_tenant.setdefault(v.tenant_id, []).append(v)
    gone = churned_on(approvals or [], seed)
    lines: list[M2InvoiceLine] = []
    for i in range(MONTHS):
        start, end = _month_start(i), _month_end(_month_start(i))
        for t in tenants:
            if t.onboarded_on >= end:
                continue
            cd = gone.get(t.tenant_id)
            if cd is not None and cd <= start:
                continue
            v = _version_on(by_tenant[t.tenant_id], max(start, t.onboarded_on))
            seat = ((v.arr_usd - v.ai_addon_arr_usd) / 12).quantize(CENT, ROUND_HALF_UP)
            up = uplift_share(approvals or [], t.plan, start, end)
            addon = (v.ai_addon_arr_usd * (1 + up) / 12).quantize(CENT, ROUND_HALF_UP)
            if cd is not None and cd < end:
                part = Decimal((cd - start).days) / Decimal((end - start).days)
                seat, addon = (seat * part).quantize(CENT, ROUND_HALF_UP), (addon * part).quantize(CENT, ROUND_HALF_UP)
            discount = -((seat + addon) * v.discount_pct).quantize(CENT, ROUND_HALF_UP)
            invoice_id = f"inv-{start:%Y%m}-{t.tenant_id}"
            for line_type, amount in (("subscription", seat), ("ai_addon", addon), ("discount", discount)):
                lines.append(M2InvoiceLine(invoice_id, t.tenant_id, start, end, line_type, amount))
    return lines


__all__ = ["M2InvoiceLine", "churned_on", "generate_invoices"]
