"""A scripted stand-in for Bedrock: calls the expected tool, then answers from the tool result."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mc_agents.llm import LLMRequest, LLMResponse


def last_tool_result(req: LLMRequest) -> dict[str, Any]:
    for msg in reversed(req.messages):
        for block in msg["content"]:
            if "toolResult" in block:
                return block["toolResult"]["content"][0]["json"]
    raise AssertionError("no tool result yet")


@dataclass
class ScriptedLLM:
    tool: str
    args: dict[str, Any]
    write: Callable[[dict[str, Any]], str]
    requests: list[LLMRequest] = field(default_factory=list)

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        if not any("toolResult" in b for m in req.messages for b in m["content"]):
            return LLMResponse([{"toolUse": {"toolUseId": "t1", "name": self.tool, "input": self.args}}], "tool_use", 900, 60)
        return LLMResponse([{"text": self.write(last_tool_result(req))}], "end_turn", 1400, 80)


def good_answer(questions: dict, qid: str) -> ScriptedLLM:
    q = questions[qid]
    exp = q["expected_tool"]

    def write(r: dict[str, Any]) -> str:
        ev = r["evidence_id"]
        if "ranking" in r:
            parts = [f"{x['tenant_id']} at {x['gross_margin_pct']} margin, {x['cost_to_serve_usd']} cost to serve [{ev}]"
                     for x in r["ranking"]]
            return "Ranking (F1 only, synthetic): " + "; ".join(parts) + "."
        if "ai_gross_margin_pct" in r:
            return f"Portfolio AI gross margin was {r['ai_gross_margin_pct']} on {r['ai_revenue_usd']} AI revenue [{ev}]. F1 only."
        return (f"{r['tenant_id']} had AI revenue of {r['ai_revenue_usd']}, cost to serve of {r['cost_to_serve_usd']}, "
                f"and gross margin of {r['gross_margin_usd']} ({r['gross_margin_pct']}) from {r['covered_from']} "
                f"to {r['covered_to']} [{ev}]. F1 only.")

    return ScriptedLLM(exp["name"], exp["args"], write)


def load_questions(eval_dir) -> dict:
    return {q["id"]: q for q in json.loads((eval_dir / "questions.json").read_text())["questions"]}
