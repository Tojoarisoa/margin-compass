"""Specialist nodes AG-03..AG-07 (M4-03 step 4, PLAN.md §8.3).

One generic tool-loop node, configured per specialist: a prompt, an allow-list of registry tools and a
model tier. The model only picks tools and words the answer; every number comes from a registry tool
and lands in the evidence ledger (AGENTS.md rule 3). Tools outside a specialist's allow-list fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import MAX_TOOL_ROUNDS
from .graph import GraphState
from .llm import BudgetedLLM, LLMRequest
from .tools import registry
from .tools.metrics import ToolError

PROMPT_VERSION = "specialists-v3"
_RULES = ("Get every figure from a tool; never calculate or round. Copy figures exactly and cite the evidence ID "
          "such as [E1]. Synthetic data. At most 4 short sentences.")

# 3c-3c (specialists-v2): AG-05 used to ask the user for a plan instead of calling its tools.
# 3c-3d (specialists-v3): one price_plan call does before, after and churn (the cost cap allows about two model
# calls), and figures stay in the tool's units (the verifier rejected "$50" for 5000 cents and "4%" for 400 bps).
_PRICING = ("Never ask the user for plan details or approval context; call price_plan once, with no preamble. "
            "When the question names a tenant ID, first read its plan from the gold marts with query_gold and pass "
            "every plan field. Otherwise pass no plan fields: the tool uses the example plan; say it is an example. "
            "Put a price change or discount in after, for example a 4% discount is after {\"discount_bps\": 400}; "
            "for a price rise, put the new seat_price_cents in after. For churn, pass churn_bps; with no rate given "
            "use 200 and say it is assumed. Report money in cents and rates in bps exactly as the tool returns them; "
            "never convert to dollars or percent. For an approval request, give the before and after figures and "
            "say the discount needs approval by the role with authority.")


@dataclass(frozen=True)
class Specialist:
    node: str
    agent_id: str
    role: str
    tools: tuple[str, ...]
    instructions: str = ""

    @property
    def system(self) -> str:
        return " ".join(p for p in (f"You are the {self.role} for Margin Compass.", self.instructions, _RULES) if p)


SPECIALISTS: dict[str, Specialist] = {s.node: s for s in (
    Specialist("cost_to_serve", "AG-03", "Cost-to-Serve Analyst", ("query_gold",)),
    Specialist("leak", "AG-04", "Margin-Leak Investigator", ("query_gold", "search_knowledge")),
    Specialist("pricing", "AG-05", "Forecast and Pricing Strategist", ("price_plan", "query_gold"),
               _PRICING),
    Specialist("efficiency", "AG-06", "AI Efficiency Engineer", ("replay_lever", "roi_multiple", "query_gold")),
    Specialist("contract_policy", "AG-07", "Contract and Policy Advisor", ("search_knowledge",)),
)}


def tool_specs(spec: Specialist, extra: dict[str, registry.ToolSpec] | None = None) -> list[dict[str, Any]]:
    out = []
    for name in spec.tools:
        t = registry.TOOLS.get(name) or (extra or {}).get(name)
        if t is not None:  # a tool needing runtime dependencies is offered only when supplied
            out.append({"toolSpec": {"name": name, "description": t.description,
                                     "inputSchema": {"json": t.input_schema or {"type": "object"}}}})
    return out


def run_specialist(state: GraphState, llm: BudgetedLLM, model_id: str,
                   extra: dict[str, registry.ToolSpec] | None = None) -> GraphState:
    """Runs the routed specialist's tool loop; leaves the draft in `state.answer` for AG-08."""
    spec = SPECIALISTS.get(state.route or "")
    if spec is None:
        state.status, state.issues = "failed", [f"no specialist for route {state.route!r}"]
        return state
    specs = tool_specs(spec, extra)
    text = state.question
    if state.issues:  # a verifier retry: say what failed (figures and rule names only, no response text)
        text += "\n\nYour previous answer failed verification: " + "; ".join(state.issues) + "."
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": text}]}]
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        resp = llm.complete(LLMRequest(model_id, spec.system, messages, specs if round_ < MAX_TOOL_ROUNDS else []))
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b["toolUse"] for b in resp.content if "toolUse" in b]
        if not uses:
            state.answer = "\n".join(b["text"] for b in resp.content if "text" in b).strip()
            return state
        results = []
        for use in uses:
            name, args = use["name"], use.get("input") or {}
            try:
                if name not in spec.tools:
                    raise ToolError(f"{name!r} is not available to {spec.agent_id}")
                ev = registry.call(name, args, state.ledger, extra)
                payload, status = {"evidence_id": ev.id, **ev.result}, "success"
            except ToolError as exc:
                payload, status = {"error": str(exc)}, "error"
            results.append({"toolResult": {"toolUseId": use["toolUseId"], "content": [{"json": payload}], "status": status}})
        messages.append({"role": "user", "content": results})
    state.status, state.issues = "failed", ["tool round limit reached"]
    return state
