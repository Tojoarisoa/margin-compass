"""AG-03 Cost-to-Serve Analyst: the M1-06 one-node agent (PLAN.md §8.3, ADR-010, ADR-013).

Graph: analyst (LLM) <-> tools (deterministic) -> verify (deterministic ledger check) -> END.
On a failed check the analyst gets one revision with the verifier's findings; if it still fails, the
answer is withheld (fail closed). The cost-of-answer line is computed in code, never by the model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .budget import BudgetExceeded, QuestionBudget
from .config import DEFAULT_ANALYST_MODEL, MAX_REVISIONS, MAX_TOOL_ROUNDS, MODELS
from .ledger import Ledger, Verification, verify_answer
from .llm import BudgetedLLM, LLMClient, LLMRequest
from .tools import MetricTools, ToolError

log = logging.getLogger("mc_agents")
PROMPT_VERSION = "ag03-v1"

SYSTEM_PROMPT = """You are the Cost-to-Serve Analyst for Margin Compass, an AI margin tool for BoonCore (a synthetic company; all data is synthetic).
You answer questions about AI revenue, AI cost to serve, and AI gross margin per tenant or for the portfolio.

Rules:
- Get every figure from a tool. Never calculate, estimate, round, convert, or compare numbers yourself.
- Copy figures exactly as the tool returns them, including "$", "," and "%".
- Cite the evidence for each figure with its ID in square brackets, e.g. [E1]. Evidence IDs are given with each tool result.
- State the period the tool actually covered (covered_from to covered_to) when it differs from the question.
- In M1 the data covers feature F1 (Reply Copilot) only; say so briefly.
- If the question is outside AI cost, revenue, or margin, say you can't answer it and stop.
- Answer in at most 4 short sentences or bullets. No tables, no headings."""


class State(TypedDict, total=False):
    question: str
    messages: list[dict[str, Any]]
    tool_rounds: int
    revisions: int
    answer: str
    status: str
    verification: dict[str, Any]
    error: str


@dataclass
class AnswerResult:
    question: str
    status: Literal["answered", "unverified", "budget_exceeded", "error"]
    answer: str
    cost_line: str
    model: str
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    evidence: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    verification: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["cost_usd"] = str(self.cost_usd)
        return d


def _text(content: list[dict[str, Any]]) -> str:
    return "\n".join(b["text"] for b in content if "text" in b).strip()


def _tools_for(gold_dir):
    """M1 tools, plus the registry `kpi` tool when M2 marts exist and `mc_pipelines` is installed (not in the Lambda image yet)."""
    try:
        from .tools.m2 import analyst_tools
    except ImportError:
        return MetricTools(gold_dir)
    return analyst_tools(gold_dir)


def build_graph(llm: BudgetedLLM, tools: MetricTools, ledger: Ledger, model_id: str, tool_log: list):
    specs = tools.specs()

    def analyst(state: State) -> State:
        req = LLMRequest(model_id=model_id, system=SYSTEM_PROMPT, messages=state["messages"], tools=specs)
        resp = llm.complete(req)
        messages = state["messages"] + [{"role": "assistant", "content": resp.content}]
        uses = [b["toolUse"] for b in resp.content if "toolUse" in b]
        if uses:
            return {"messages": messages, "status": "tool"}
        return {"messages": messages, "answer": _text(resp.content), "status": "draft"}

    def run_tools(state: State) -> State:
        last = state["messages"][-1]["content"]
        results = []
        for use in (b["toolUse"] for b in last if "toolUse" in b):
            name, args = use["name"], use.get("input") or {}
            tool_log.append({"tool": name, "args": args})
            try:
                result = tools.call(name, args)
                ev = ledger.add(name, args, result)
                payload, status = {"evidence_id": ev.id, **result}, "success"
            except ToolError as exc:
                payload, status = {"error": str(exc)}, "error"
            results.append({"toolResult": {"toolUseId": use["toolUseId"], "content": [{"json": payload}], "status": status}})
        return {"messages": state["messages"] + [{"role": "user", "content": results}],
                "tool_rounds": state.get("tool_rounds", 0) + 1}

    def verify(state: State) -> State:
        v: Verification = verify_answer(state.get("answer", ""), ledger, state["question"])
        report = {"ok": v.ok, "unsupported": v.unsupported, "figures_checked": v.checked, "cited": v.cited}
        if v.ok:
            return {"status": "answered", "verification": report}
        if state.get("revisions", 0) < MAX_REVISIONS:
            problems = []
            if v.unsupported:
                problems.append("these figures are not in any tool result: " + ", ".join(v.unsupported))
            if not v.cited:
                problems.append("cite evidence IDs like [E1]")
            feedback = "Verifier: " + "; ".join(problems) + ". Rewrite the answer using only tool figures, copied exactly."
            return {"status": "revise", "verification": report, "revisions": state.get("revisions", 0) + 1,
                    "messages": state["messages"] + [{"role": "user", "content": [{"text": feedback}]}]}
        return {"status": "unverified", "verification": report}

    def after_analyst(state: State) -> str:
        if state["status"] == "tool":
            return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "give_up"
        return "verify"

    def give_up(state: State) -> State:
        return {"status": "unverified", "answer": "", "error": "tool round limit reached"}

    g = StateGraph(State)
    g.add_node("analyst", analyst)
    g.add_node("tools", run_tools)
    g.add_node("verify", verify)
    g.add_node("give_up", give_up)
    g.add_edge(START, "analyst")
    g.add_conditional_edges("analyst", after_analyst, {"tools": "tools", "verify": "verify", "give_up": "give_up"})
    g.add_edge("tools", "analyst")
    g.add_conditional_edges("verify", lambda s: "analyst" if s["status"] == "revise" else END, {"analyst": "analyst", END: END})
    g.add_edge("give_up", END)
    return g.compile()


def answer_question(question: str, *, gold_dir: Path, client: LLMClient, model_key: str = DEFAULT_ANALYST_MODEL,
                    spend=None) -> AnswerResult:
    spec = MODELS[model_key]
    budget = QuestionBudget(spec)
    llm = BudgetedLLM(client, budget, spend)
    ledger, tool_log = Ledger(), []
    graph = build_graph(llm, _tools_for(gold_dir), ledger, spec.target, tool_log)
    state: State = {"question": question, "messages": [{"role": "user", "content": [{"text": question}]}]}
    try:
        final = graph.invoke(state, {"recursion_limit": 20})
        status = final.get("status", "error")
        answer = final.get("answer", "") if status == "answered" else ""
        verification = final.get("verification", {})
    except BudgetExceeded as exc:
        status, answer, verification = "budget_exceeded", "", {"error": str(exc)}
    if status not in ("answered", "unverified", "budget_exceeded"):
        status = "error"
    if not answer:
        answer = {"unverified": "I couldn't verify every figure in my draft, so I'm not showing it.",
                  "budget_exceeded": "This question hit its LLM budget, so I stopped.",
                  "error": "Something went wrong while answering."}.get(status, "")
    cost_line = (f"Cost of this answer: ${budget.usd.quantize(Decimal('0.0001'))} "
                 f"({budget.calls} LLM call{'s' if budget.calls != 1 else ''}, {spec.label}, list price).")
    result = AnswerResult(question, status, answer, cost_line, spec.target, budget.calls, budget.input_tokens,
                          budget.output_tokens, budget.usd, [e.__dict__ for e in ledger.entries], tool_log, verification)
    log.info("agent_answer", extra={"fields": {"status": status, "model": spec.target, "llm_calls": budget.calls,
                                               "cost_usd": str(budget.usd), "prompt_version": PROMPT_VERSION,
                                               "tools": [t["tool"] for t in tool_log]}})
    return result
