"""Runnable agent graph (M4-03 step 5, PLAN.md §8.2-8.3): route -> specialist -> verify -> responder / HITL.

`ask` drives one question through the nodes. After every node a checkpoint (dict-like store, DynamoDB later)
records the node, status and issues, never prompt or response text (AGENTS.md rule 16). A state that needs
approval is persisted via AG-09 and returns `pending`; `decide` resumes it. Everything fails closed: an
ambiguous route (no LLM supervisor yet) or a failed verifier is withheld, never answered.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from . import approvals
from .approvals import Store
from .graph import GraphState, route, verify
from .llm import BudgetedLLM
from .responder import respond
from .specialists import run_specialist
from .tools import registry

ActionsFn = Callable[[GraphState], list[dict[str, Any]]]


def _checkpoint(store: Store | None, run_id: str, trail: list[dict[str, Any]], node: str, state: GraphState) -> None:
    trail.append({"node": node, "status": state.status, "rounds": state.rounds, "issues": list(state.issues)})
    if store is not None:
        store.put(f"run#{run_id}", {"trail": trail})


def ask(question: str, llm: BudgetedLLM, model_id: str, *, run_id: str, approval_store: Store,
        checkpoints: Store | None = None, extra: dict[str, registry.ToolSpec] | None = None,
        propose_actions: ActionsFn | None = None, usd: Decimal = Decimal(0), calls: int = 0,
        label: str = "", state: GraphState | None = None) -> dict[str, Any]:
    # `state` lets a caller (EV-06 graph runs) read the route and ledger, also after a capped run raises.
    state = state if state is not None else GraphState(question)
    trail: list[dict[str, Any]] = []
    nxt = route(state)
    _checkpoint(checkpoints, run_id, trail, "route", state)
    if nxt == "llm_supervisor":  # no LLM supervisor yet: fail closed
        state.status, state.issues = "failed", ["route is ambiguous"]
    while nxt not in ("end", "llm_supervisor", "fail"):
        state.answer = ""
        run_specialist(state, llm, model_id, extra)
        _checkpoint(checkpoints, run_id, trail, state.route or "specialist", state)
        if state.status == "failed":
            break
        if propose_actions is not None:
            state.actions = propose_actions(state)
        nxt = verify(state)
        _checkpoint(checkpoints, run_id, trail, "verify", state)
        if nxt == "supervisor":
            continue
        break
    out = respond(state, usd=usd, calls=calls, label=label)
    if state.status == "needs_approval" and state.approver:
        ap = approvals.request(approval_store, run_id, question, state.actions, state.approver)
        out.update(approval_id=ap.id, status="pending")
    out["run_id"] = run_id
    return out


def decide(approval_store: Store, approval_id: str, role: str, approve: bool) -> dict[str, Any]:
    """Resumes a pending item. A lower role raises `approvals.NotAuthorized` and changes nothing."""
    ap = approvals.decide(approval_store, approval_id, role, approve)
    return {"approval_id": ap.id, "status": ap.status, "decided_by": ap.decided_by}
