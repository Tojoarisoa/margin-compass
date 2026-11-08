"""AG-10 responder (M4-03 step 4b, PLAN.md §8.3): the final, persona-aware answer package.

Deterministic: the verified answer text is passed through unchanged (an LLM rewrite would need a second
verifier pass), and the evidence table and cost-of-answer line are built in code from the ledger and the
budget, never by a model (AGENTS.md rule 3). A state that did not pass AG-08 is never rendered as an answer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .graph import GraphState

_WITHHELD = "I couldn't verify this answer, so I'm not showing it."
_BLOCKED = "I can't help with that request."


def evidence_table(state: GraphState) -> list[dict[str, Any]]:
    return [{"id": e.id, "tool": e.tool.split("@")[0], "version": e.tool.split("@")[1] if "@" in e.tool else "",
             "args": e.args} for e in state.ledger.entries]


def cost_line(usd: Decimal, calls: int, label: str) -> str:
    return (f"Cost of this answer: ${usd.quantize(Decimal('0.0001'))} "
            f"({calls} LLM call{'s' if calls != 1 else ''}, {label}, list price).")


def respond(state: GraphState, *, usd: Decimal = Decimal(0), calls: int = 0, label: str = "") -> dict[str, Any]:
    """Returns the response record. Only `verified` and `needs_approval` states show the answer."""
    if state.status == "blocked":
        text, status = _BLOCKED, "blocked"
    elif state.status in ("verified", "needs_approval") and state.answer:
        text, status = state.answer, state.status
    else:
        text, status = _WITHHELD, "unverified"
    shown = status in ("verified", "needs_approval")
    return {"status": status, "answer": text, "evidence": evidence_table(state) if shown else [],
            "approver": state.approver if status == "needs_approval" else None,
            "actions": state.actions if status == "needs_approval" else [],
            "cost_line": cost_line(usd, calls, label)}
