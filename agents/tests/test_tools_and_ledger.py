from decimal import Decimal

import duckdb
import pytest

from mc_agents.ledger import Ledger, verify_answer
from mc_agents.tools import MetricTools, ToolError
from mc_agents.tools.metrics import money, pct


def test_formatting_is_half_up_to_the_cent():
    assert money(Decimal("1234.565")) == "$1,234.57"
    assert money(Decimal("-0.005")) == "-$0.01"
    assert pct(Decimal("1"), Decimal("3")) == "33.33%"
    assert pct(Decimal("1"), Decimal("0")) is None


def test_portfolio_margin_matches_the_exec_kpi_mart(gold):
    """The tool's KPI-01 over the window equals the mart's revenue and cost-to-serve totals."""
    t = MetricTools(gold)
    lo, hi = t.window
    r = t.portfolio_margin(lo.isoformat(), hi.isoformat())
    rev, cost = duckdb.sql(f"SELECT sum(ai_revenue_usd), sum(ai_cost_to_serve_usd) FROM read_parquet('{gold}/agg_exec_kpis.parquet')").fetchall()[0]
    assert r["ai_revenue_usd"] == money(rev)
    assert r["ai_gross_margin_pct"] == pct(rev - cost, rev)


def test_tenant_margin_adds_up(gold):
    t = MetricTools(gold)
    r = t.tenant_margin("bc-t0003", "2025-09-01", "2025-09-30")
    d = lambda s: Decimal(s.replace("$", "").replace(",", ""))  # noqa: E731
    assert abs(d(r["ai_revenue_usd"]) - d(r["cost_to_serve_usd"]) - d(r["gross_margin_usd"])) <= Decimal("0.01")
    assert r["days"] == 30 and r["data_label"] == "synthetic"


def test_period_is_clamped_to_the_window(gold):
    r = MetricTools(gold).tenant_margin("bc-t0012", "2025-10-01", "2025-10-31")
    assert r["covered_to"] == "2025-10-29" and r["days"] == 29


@pytest.mark.parametrize("call, message", [
    (lambda t: t.tenant_margin("bc-t9999", "2025-09-01", "2025-09-30"), "unknown tenant"),
    (lambda t: t.tenant_margin("x'; DROP TABLE", "2025-09-01", "2025-09-30"), "tenant_id must look like"),
    (lambda t: t.tenant_margin("bc-t0003", "2025-09-30", "2025-09-01"), "on or before"),
    (lambda t: t.tenant_margin("bc-t0003", "2024-01-01", "2024-01-31"), "no data"),
    (lambda t: t.tenant_ranking("gross_margin_pct", "asc", 50, "2025-08-01", "2025-08-31"), "limit"),
    (lambda t: t.tenant_ranking("churn", "asc", 3, "2025-08-01", "2025-08-31"), "metric"),
    (lambda t: t.call("drop_tables", {}), "unknown tool"),
    (lambda t: t.call("portfolio_margin", {"start_date": "2025-08-01"}), "bad arguments"),
])
def test_tool_inputs_are_validated(gold, call, message):
    with pytest.raises(ToolError, match=message):
        call(MetricTools(gold))


def _ledger():
    led = Ledger()
    led.add("tenant_margin", {"tenant_id": "bc-t0003"}, {"gross_margin_usd": "$3,795.76", "gross_margin_pct": "98.07%", "days": 30})
    return led


@pytest.mark.parametrize("answer, ok", [
    ("bc-t0003 earned $3,795.76 (98.07%) in September 2025 [E1].", True),
    ("bc-t0003 earned $3,795.76 from 2025-09-01 to 2025-09-30, 30 days [E1].", True),
    ("bc-t0003 earned $3,795.76 (98.1%) [E1].", False),      # re-rounded by the model
    ("bc-t0003 earned $3,800 [E1].", False),                 # invented
    ("bc-t0003 earned $3,795.76 (98.07%).", False),          # no citation
    ("Margin rose 12 points [E1].", False),                  # bare integer not in ledger or question
    ("bc-t0003 earned $3,795.76 [E1], see also [E2].", False),  # E2 does not exist (AG-08)
])
def test_verifier_enforces_the_ledger_rule(answer, ok):
    assert verify_answer(answer, _ledger(), "What was bc-t0003's margin in September 2025?").ok is ok


@pytest.mark.parametrize("answer, ok", [
    ("Margin changes by \u2212163 bps [E1].", True),   # Unicode minus = the ledger's -163
    ("Margin changes by -163 bps [E1].", True),
    ("Margin changes by 163 bps [E1].", False),        # sign dropped
    ("Churn adds \u2212200 bps [E1].", False),         # sign added: 200 is in the ledger, -200 is not
])
def test_verifier_checks_the_sign_of_a_unicode_minus(answer, ok):
    """Next 2 (run 117): AG-05 writes deltas with U+2212, which used to read as a positive figure."""
    led = Ledger()
    led.add("price_plan", {"churn_bps": 200}, {"after": {"delta": {"margin_bps": -163}}})
    assert verify_answer(answer, led, "Should we approve the discount?").ok is ok


def test_bare_integer_from_the_question_is_allowed():
    led = Ledger()
    led.add("tenant_ranking", {"limit": 3}, {"ranking": [{"rank": 1, "gross_margin_pct": "98.09%"}]})
    assert verify_answer("The top 3: bc-t0003 at 98.09% [E1].", led, "Which three tenants... top 3?").ok


def test_citation_with_no_evidence_is_rejected():
    """AG-08: an [E<n>] that is not in the ledger fails, including when nothing was retrieved at all."""
    v = verify_answer("The policy is quoted in [E1].", Ledger(), "What does the policy say?")
    assert not v.ok and v.unknown_refs == ["[E1]"]
    assert verify_answer("No policy text was found.", Ledger(), "What does the policy say?").ok
