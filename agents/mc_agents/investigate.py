"""Nightly margin review, step 6 (M5-01, PLAN.md §8.5): LLM investigation of the top actions, with episodic memory.

Takes the ranked drafts from `nightly.review`, asks the model for a short likely cause and a next step for the top
actions (one call each), and summarizes all lower-ranked ones in a single batched call (PLAN.md §8.5 point 6).
The nightly spend is capped in code at $0.50 and 8 calls per run (AGENTS.md rule 6); the budget is checked before every
call by `BudgetedLLM`. Rule 3: the model gets the figures as text and may not add any; an answer containing a number
that is not in the action's own facts is dropped. Findings are appended to episodic memory (`memory/episodic.jsonl`),
and the next night's prompt includes the last finding for the same target. Prompts and answers are never logged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .budget import BudgetExceeded, QuestionBudget
from .config import MODELS, ModelSpec
from .llm import BudgetedLLM, LLMClient, LLMRequest
from .nightly import Action

PROMPT_VERSION = "nightly-investigate-v1"
NIGHTLY_MAX_USD = Decimal("0.50")  # PLAN.md §11.3: nightly LLM cap
NIGHTLY_MAX_CALLS = 8
TOP_INVESTIGATED = 5
MAX_OUTPUT_TOKENS = 220
SYSTEM = ("You are the Margin-Leak Investigator for Margin Compass (synthetic data). Given a drafted margin action, "
          "write at most 2 short sentences: the most likely cause to check first and the next step. "
          "Never state a number, date or percentage that is not in the facts; do not calculate. "
          "Do not claim a cause is confirmed.")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class Insight:
    action_id: str
    target: str
    text: str


@dataclass
class Result:
    insights: list[Insight] = field(default_factory=list)
    calls: int = 0
    usd: Decimal = field(default_factory=lambda: Decimal(0))
    dropped: int = 0
    stopped: str = ""


def _facts(a: Action) -> str:
    return (f"{a.action_type} {a.target}: {a.title}. Impact ${a.impact_usd_month}/month, confidence {a.confidence}, "
            f"effort {a.effort}, risk {a.risk}.")


def numbers_ok(text: str, facts: str) -> bool:
    """Every number in the answer must already appear in the facts it was given."""
    allowed = {n.rstrip(".,") for n in _NUM.findall(facts)}
    return all(n.rstrip(".,") in allowed for n in _NUM.findall(text))


def load_memory(path: Path) -> dict[str, str]:
    """Latest finding per target from episodic memory (empty when the file is missing or damaged)."""
    last: dict[str, str] = {}
    try:
        for line in Path(path).read_text().splitlines():
            rec = json.loads(line)
            last[rec["target"]] = rec["text"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return last


def _ask(llm: BudgetedLLM, model_id: str, prompt: str) -> str:
    req = LLMRequest(model_id, SYSTEM, [{"role": "user", "content": [{"text": prompt}]}], [], max_tokens=MAX_OUTPUT_TOKENS)
    resp = llm.complete(req)
    return " ".join(b["text"].strip() for b in resp.content if "text" in b).strip()


def investigate(actions: list[Action], client: LLMClient, spec: ModelSpec | None = None,
                memory: dict[str, str] | None = None, max_usd: Decimal = NIGHTLY_MAX_USD) -> Result:
    spec = spec or MODELS["haiku-4-5"]
    budget = QuestionBudget(spec, max_calls=NIGHTLY_MAX_CALLS, max_usd=max_usd)
    llm = BudgetedLLM(client, budget)
    memory = memory or {}
    res = Result()
    try:
        for a in actions[:TOP_INVESTIGATED]:
            facts = _facts(a)
            prior = memory.get(a.target)
            prompt = f"Facts: {facts}" + (f"\nLast night's finding: {prior}" if prior else "")
            text = _ask(llm, spec.target, prompt)
            if text and numbers_ok(text, facts + (prior or "")):
                res.insights.append(Insight(a.action_id, a.target, text))
            else:
                res.dropped += 1
        rest = actions[TOP_INVESTIGATED:]
        if rest:  # one batched call for everything of lower rank
            facts = "\n".join(f"{i + 1}. {_facts(a)}" for i, a in enumerate(rest))
            text = _ask(llm, spec.target, "Summarize the common theme of these lower-ranked actions in 2 sentences.\n" + facts)
            if text and numbers_ok(text, facts):
                res.insights.append(Insight("batch", "lower-ranked", text))
            else:
                res.dropped += 1
    except BudgetExceeded as e:
        res.stopped = str(e)
    res.calls, res.usd = budget.calls, budget.usd
    return res


def remember(path: Path, run_id: str, insights: list[Insight]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for i in insights:
            f.write(json.dumps({"run_id": run_id, "action_id": i.action_id, "target": i.target, "text": i.text},
                               sort_keys=True) + "\n")
