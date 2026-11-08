"""Agent graph, step 2 (M4-03, PLAN.md §8.2-8.3): typed state, supervisor routing and the AG-08 verifier.

Everything here is deterministic. `route` is the supervisor's fast path (no LLM call) and returns the next
node; `verify` is AG-08's rule half (ledger numbers, citations, quality guardrail, discount authority).
Rules only ever tighten: an unknown action type or a missing tool result fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .intake import Intake, screen
from .ledger import Ledger, verify_answer

MAX_VERIFY_ROUNDS = 2  # PLAN.md §8.2: verifier fail loops back to the supervisor at most twice.

# Discount authority matrix v1 (knowledge/policies/discount-authority-matrix.md; thresholds are assumptions).
_AUTHORITY = ((500, "account_manager"), (1500, "revops_lead"), (2500, "head_of_revenue"))
_ACTIONS = {"discount", "apply_lever", "contract_change"}

_SPECIALIST_HINTS = (
    ("contract_policy", ("contract", "clause", "policy", "renewal", "baa", "residency", "authority")),
    ("efficiency", ("lever", "routing", "cache", "downgrade", "quality", "roi", "payback")),
    ("pricing", ("pricing", "price", "plan", "forecast", "churn", "discount")),
    ("leak", ("leak", "spike", "root cause", "why did")),
    ("cost_to_serve", ("margin", "cost", "cogs", "spend", "tenant", "feature")),
)


@dataclass
class GraphState:
    question: str
    intake: Intake | None = None
    route: str | None = None
    ledger: Ledger = field(default_factory=Ledger)
    answer: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    issues: list[str] = field(default_factory=list)
    approver: str | None = None
    status: str = "new"  # new | blocked | routed | verified | needs_approval | failed


def approver_for_discount(discount_bps: int) -> str:
    for limit, role in _AUTHORITY:
        if discount_bps <= limit:
            return role
    return "finance_and_ceo"


def route(state: GraphState) -> str:
    """AG-01 then AG-02 fast path. Returns 'end' (blocked), 'llm_supervisor' (ambiguous) or a specialist."""
    state.intake = screen(state.question)
    if state.intake.verdict == "block":
        state.status = "blocked"
        return "end"
    if state.intake.verdict == "inconclusive":
        return "llm_supervisor"
    q = state.question.lower()
    for node, words in _SPECIALIST_HINTS:
        if any(w in q for w in words):
            state.route, state.status = node, "routed"
            return node
    return "llm_supervisor"


def verify(state: GraphState) -> str:
    """AG-08 rules. Returns 'responder', 'hitl', 'supervisor' (retry) or 'fail'; fills state.issues."""
    issues: list[str] = []
    v = verify_answer(state.answer, state.ledger, state.question)
    if v.unsupported:
        issues.append(f"unsupported figures: {', '.join(v.unsupported)}")
    if state.ledger.entries and not v.cited:
        issues.append("no evidence citation")
    approver = None
    for a in state.actions:
        kind = a.get("type")
        if kind not in _ACTIONS:
            issues.append(f"unknown action type: {kind!r}")
            continue
        if kind == "discount":
            bps = a.get("discount_bps")
            if isinstance(bps, bool) or not isinstance(bps, int) or bps < 0:
                issues.append("discount_bps must be a non-negative integer")
            else:
                role = approver_for_discount(bps)
                approver = role if approver is None or _rank(role) > _rank(approver) else approver
        elif kind == "apply_lever":
            ev = next((e for e in state.ledger.entries if e.id == a.get("evidence")), None)
            if ev is None or ev.tool != "replay_lever":
                issues.append("lever action has no replay evidence")
            elif ev.result.get("allowed") is not True:
                issues.append("lever violates the quality or safety-recall guardrail")
            else:
                approver = approver or "revops_lead"
        else:  # contract_change
            if a.get("waives_non_waivable"):
                issues.append("contract change touches a non-waivable limit")
            approver = approver or "revops_lead"
    state.issues = issues
    if issues:
        state.rounds += 1
        state.status = "failed" if state.rounds > MAX_VERIFY_ROUNDS else "routed"
        return "fail" if state.rounds > MAX_VERIFY_ROUNDS else "supervisor"
    if state.actions:
        state.approver, state.status = approver, "needs_approval"
        return "hitl"
    state.status = "verified"
    return "responder"


def _rank(role: str) -> int:
    order = ["account_manager", "revops_lead", "head_of_revenue", "finance_and_ceo"]
    return order.index(role) if role in order else len(order)
