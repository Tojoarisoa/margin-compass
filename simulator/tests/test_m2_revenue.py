"""M2-02 step 1c: invoices from the SCD2 plan history."""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

import pyarrow.parquet as pq
import pytest

from booncore_sim import m2_revenue as rev
from booncore_sim import m2_tenants as mt
from booncore_sim import m2_writer as w

SEED = 42


@pytest.fixture(scope="module")
def data():
    tenants, history = mt.generate_m2_tenants(SEED)
    return tenants, history, rev.generate_invoices(tenants, history)


def test_every_tenant_is_billed_from_its_onboarding_month_without_gaps(data):
    tenants, _, lines = data
    months = {}
    for ln in lines:
        months.setdefault(ln.tenant_id, set()).add(ln.billing_period_start)
    for t in tenants:
        got = sorted(months[t.tenant_id])
        assert got[0] == max(t.onboarded_on.replace(day=1), mt.WINDOW_START)
        assert got[-1] == mt._month_start(mt.MONTHS - 1)
        first = max(t.onboarded_on.replace(day=1), mt.WINDOW_START)
        want = [mt._month_start(i) for i in range(mt.MONTHS) if mt._month_start(i) >= first]
        assert got == want


def test_three_lines_per_invoice_and_discount_is_negative(data):
    _, _, lines = data
    kinds = Counter((ln.invoice_id, ln.line_type) for ln in lines)
    assert set(kinds.values()) == {1}
    assert {ln.line_type for ln in lines} == {"subscription", "ai_addon", "discount"}
    assert all((ln.amount_usd <= 0) == (ln.line_type == "discount") for ln in lines if ln.amount_usd != 0)


def test_full_year_invoice_matches_arr_after_discount(data):
    tenants, history, lines = data
    t = next(x for x in tenants if x.onboarded_on <= mt.WINDOW_START and len(
        [v for v in history if v.tenant_id == x.tenant_id]) == 1)
    first_year = [ln for ln in lines if ln.tenant_id == t.tenant_id and ln.billing_period_start < date(2026, 4, 1)]
    net = sum(ln.amount_usd for ln in first_year)
    assert abs(net - t.arr_usd * (1 - t.discount_pct)) < Decimal("1.00")


def test_plan_change_moves_the_price_from_the_change_month(data):
    tenants, history, lines = data
    changed = {v.tenant_id for v in history if not v.is_current and v.valid_to and v.valid_to > mt.WINDOW_START}
    assert changed
    tid = sorted(changed)[0]
    subs = [ln.amount_usd for ln in lines if ln.tenant_id == tid and ln.line_type == "subscription"]
    assert len(set(subs)) >= 2


def test_landing_is_deterministic_and_synthetic(data, tmp_path):
    tenants, history, _ = data
    a = w.write_revenue(tmp_path / "a", SEED, tenants, history)
    b = w.write_revenue(tmp_path / "b", SEED, tenants, history)
    assert a == b and a[0]["path"] == "s3_revenue/invoices.parquet"
    assert pq.read_schema(tmp_path / "a" / a[0]["path"]).metadata[b"synthetic"] == b"true"
