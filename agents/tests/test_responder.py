from decimal import Decimal

from mc_agents.graph import GraphState
from mc_agents.responder import respond


def _state(status, answer="Margin is 5 [E1]."):
    s = GraphState("q")
    s.ledger.add("price_plan@1", {"a": 1}, {"margin_cents": 5})
    s.answer, s.status = answer, status
    return s


def test_verified_answer_shows_evidence_and_cost():
    r = respond(_state("verified"), usd=Decimal("0.00331"), calls=2, label="Claude Haiku 4.5")
    assert r["answer"] == "Margin is 5 [E1]." and r["evidence"][0]["tool"] == "price_plan"
    assert r["cost_line"] == "Cost of this answer: $0.0033 (2 LLM calls, Claude Haiku 4.5, list price)."


def test_needs_approval_carries_approver_and_actions():
    s = _state("needs_approval")
    s.approver, s.actions = "revops_lead", [{"type": "discount", "discount_bps": 600}]
    r = respond(s)
    assert r["approver"] == "revops_lead" and r["actions"]


def test_failed_and_routed_states_are_withheld():
    for st in ("failed", "routed", "new"):
        r = respond(_state(st))
        assert r["status"] == "unverified" and r["evidence"] == [] and "Margin" not in r["answer"]


def test_blocked_is_refused_without_evidence():
    r = respond(_state("blocked"))
    assert r["status"] == "blocked" and r["evidence"] == []
