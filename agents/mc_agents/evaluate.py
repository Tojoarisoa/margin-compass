"""M1-06 replay evaluation (ADR-014): 5 questions, scored deterministically.

Checks per question:
- tool: the expected tool was called with the expected arguments (EV-07 route/tool accuracy);
- grounded: the deterministic verifier passed (EV-08 ledger rule);
- correct: every expected figure (from calling the tool directly on the same gold) appears in the answer;
- budget: ≤ 8 LLM calls and ≤ $0.01 (EV-10).
Modes: replay (CI, $0), record (live Bedrock, writes fixtures), live (live, no fixtures written).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .analyst import PROMPT_VERSION, answer_question
from .config import MAX_LLM_CALLS_PER_QUESTION, MAX_USD_PER_QUESTION, MODELS
from .llm import BedrockLLM, RecordingLLM, ReplayLLM
from .tools import MetricTools

REPO = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO / "evals" / "m1_06"


def _figures(result: dict[str, Any], paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        if p.startswith("ranking[]."):
            out += [str(r[p.split(".", 1)[1]]) for r in result["ranking"]]
        else:
            out.append(str(result[p]))
    return out


def run_eval(gold_dir: Path, model_key: str, mode: str = "replay", eval_dir: Path = EVAL_DIR,
             live_client=None) -> dict[str, Any]:
    spec = MODELS[model_key]
    qs = json.loads((eval_dir / "questions.json").read_text())["questions"]
    tools = MetricTools(gold_dir)
    rows = []
    for q in qs:
        fixture = eval_dir / "fixtures" / model_key / f"{q['id']}.json"
        if mode == "replay":
            client = ReplayLLM(fixture)
        elif mode == "record":
            client = RecordingLLM(live_client or BedrockLLM(), fixture)
        else:
            client = live_client or BedrockLLM()
        res = answer_question(q["question"], gold_dir=gold_dir, client=client, model_key=model_key)
        if mode == "record":
            client.save({"question_id": q["id"], "model_id": spec.target, "prompt_version": PROMPT_VERSION})

        exp = q["expected_tool"]
        tool_ok = any(t["tool"] == exp["name"] and t["args"] == exp["args"] for t in res.tool_calls)
        expected = _figures(tools.call(exp["name"], exp["args"]), q["expected_figures"])
        missing = [f for f in expected if f not in res.answer]
        checks = {
            "tool": tool_ok,
            "grounded": res.status == "answered" and res.verification.get("ok", False),
            "correct": res.status == "answered" and not missing,
            "budget": res.llm_calls <= MAX_LLM_CALLS_PER_QUESTION and res.cost_usd <= MAX_USD_PER_QUESTION,
        }
        rows.append({"id": q["id"], "status": res.status, "checks": checks, "passed": all(checks.values()),
                     "missing_figures": missing, "llm_calls": res.llm_calls, "cost_usd": str(res.cost_usd),
                     "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                     "tool_calls": res.tool_calls, "answer": res.answer, "cost_line": res.cost_line})
    total = sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0))
    return {
        "set": "m1-06", "model": spec.target, "mode": mode, "prompt_version": PROMPT_VERSION,
        "passed": sum(r["passed"] for r in rows), "total": len(rows),
        "rates": {k: sum(r["checks"][k] for r in rows) / len(rows) for k in ("tool", "grounded", "correct", "budget")},
        "cost_usd_total": str(total), "cost_usd_per_question": str((total / len(rows)).quantize(Decimal("0.000001"))),
        "max_llm_calls": max(r["llm_calls"] for r in rows), "questions": rows,
    }
