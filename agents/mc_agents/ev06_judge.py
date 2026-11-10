"""EV-06 step 2: rubric-based LLM judge over the golden scenarios (PLAN.md §9, gate 90%).

The judge reads one scenario (question, job, expected route and outcome, allowed tools) and one run
(route, tools, status, answer, evidence ledger) and returns a verdict per rubric criterion through a
`record_verdict` tool call. A scenario passes only when every criterion passes; no tool call, a malformed
verdict or a capped run counts as a fail (fail closed).

The judge never computes numbers (rule 3): figures are checked by `verify_answer`, and the judge sees the
ledger only to judge whether the answer addresses the job. Calls go through `BudgetedLLM` with the
per-question caps. CI replays recorded fixtures (`replay`, $0); `record`/`live` call Bedrock via the ops
workflow. Calibration on human labels is open (docs/progress.md, Waiting for owner); until then the judge
is reported next to the deterministic rubric and their agreement.

Coverage: the default replays each scenario's recorded outcome, so only scenarios with a complete one are
judged (a recorded answer, or blocked at intake); the rest are listed under `not_judged` until real graph
runs are recorded for them. Pass `scenarios` (or a graph `run`) to judge others.

Replay: a scenario whose request changed since recording (its golden answer or evidence was edited) gets no
verdict, fails, and is listed under `drifted` until re-recorded; a missing fixture file still raises.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .ev06 import EV06_GATE, reference_run, task_success
from .ev_scenarios import load_scenarios
from .llm import FixtureDrift

JUDGE_PROMPT_VERSION = "ev06-judge-v1"
FIXTURES = Path(__file__).resolve().parent.parent / "golden" / "ev06_judge_fixtures"
CRITERIA = ("route", "tools", "outcome", "addresses_job")

SYSTEM = """You grade one run of a margin-analytics assistant against a golden scenario.
Apply this rubric. Each criterion is true or false:
- route: the run's route equals the expected route.
- tools: every tool the run used is in the allowed tools list (using none is fine).
- outcome: if the expected route is "blocked", the run ended blocked; otherwise it ended answered.
- addresses_job: for an answered run, the answer responds to the question for the stated job, stays on
  the evidence given, and cites evidence ids like [E1] when it states figures; for a blocked run, true.
Do not recompute or judge the arithmetic of figures; a separate checker does that.
Call record_verdict exactly once. Keep reason under 25 words. Do not write any other text."""

VERDICT_TOOL = {"toolSpec": {
    "name": "record_verdict",
    "description": "Record the rubric verdict for this run.",
    "inputSchema": {"json": {
        "type": "object",
        "properties": {**{c: {"type": "boolean"} for c in CRITERIA}, "reason": {"type": "string"}},
        "required": [*CRITERIA, "reason"],
    }},
}}


def judgeable(sc: dict[str, Any]) -> bool:
    return sc["route"] == "blocked" or bool(sc.get("answer"))


def judge_message(sc: dict[str, Any], out: dict[str, Any]) -> str:
    expected = {"question": sc["question"], "job": sc["jtbd"], "expected_route": sc["route"],
                "allowed_tools": sc["tools"]}
    run = {"route": out["route"], "tools": out["tools"], "status": out["status"], "answer": out.get("answer") or "",
           "evidence": [{"id": e.id, "tool": e.tool, "args": e.args, "result": e.result} for e in out["ledger"].entries]}
    return json.dumps({"scenario": expected, "run": run}, sort_keys=True, default=str)


def parse_verdict(content: list[dict[str, Any]]) -> dict[str, Any] | None:
    uses = [b["toolUse"] for b in content if "toolUse" in b and b["toolUse"].get("name") == "record_verdict"]
    if len(uses) != 1:
        return None
    v = uses[0].get("input") or {}
    if not all(isinstance(v.get(c), bool) for c in CRITERIA):
        return None
    return {**{c: v[c] for c in CRITERIA}, "reason": str(v.get("reason", ""))[:300]}


def judge_one(client: Any, model_key: str, sc: dict[str, Any], out: dict[str, Any]) -> dict[str, Any] | None:
    """One capped judge call. Returns the verdict, or None (fail closed) when the model gave none."""
    from .budget import BudgetExceeded, QuestionBudget
    from .config import MODELS
    from .llm import BudgetedLLM, LLMRequest

    spec = MODELS[model_key]
    llm = BudgetedLLM(client, QuestionBudget(spec, max_calls=1))
    req = LLMRequest(spec.target, SYSTEM, [{"role": "user", "content": [{"text": judge_message(sc, out)}]}],
                     [VERDICT_TOOL], max_tokens=300)
    try:
        resp = llm.complete(req)
    except BudgetExceeded:
        return None
    return parse_verdict(resp.content)


def judge(make_client: Callable[[str], Any], model_key: str = "haiku-4-5",
          run: Callable[[dict[str, Any]], dict[str, Any]] = reference_run,
          scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Judge pass rate, per job, and agreement with the deterministic rubric (step 1)."""
    every = load_scenarios()
    scs = scenarios if scenarios is not None else [s for s in every if judgeable(s)]
    judged = {s["id"] for s in scs}
    verdicts: dict[str, dict[str, Any] | None] = {}
    rubric: dict[str, bool] = {}
    drifted: list[str] = []
    for sc in scs:
        out = run(sc)
        rubric[sc["id"]] = task_success(sc, out)
        client = make_client(sc["id"])  # a missing replay fixture raises here
        try:
            verdicts[sc["id"]] = judge_one(client, model_key, sc, out)
        except FixtureDrift:  # request changed since recording: no verdict, scores as a fail until re-recorded
            verdicts[sc["id"]] = None
            drifted.append(sc["id"])
    ok = {k: v is not None and all(v[c] for c in CRITERIA) for k, v in verdicts.items()}
    by_job: dict[str, list[bool]] = defaultdict(list)
    for sc in scs:
        by_job[sc["jtbd"]].append(ok[sc["id"]])
    rate = sum(ok.values()) / len(ok) if ok else 0.0  # empty set fails closed
    agree = sum(ok[k] == rubric[k] for k in ok) / len(ok) if ok else 0.0
    return {"judge": rate, "passed": bool(ok) and rate >= EV06_GATE, "agreement_with_rubric": agree,
            "by_jtbd": {k: sum(v) / len(v) for k, v in sorted(by_job.items())},
            "failed": sorted(k for k, v in ok.items() if not v),
            "no_verdict": sorted(k for k, v in verdicts.items() if v is None), "drifted": sorted(drifted),
            "judged": len(scs), "not_judged": sorted(s["id"] for s in every if s["id"] not in judged),
            "reasons": {k: v["reason"] for k, v in verdicts.items() if v is not None and not ok[k]}}


def run_judge(model_key: str, mode: str = "replay", fixtures_dir: Path = FIXTURES, live_client: Any = None,
              scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """replay: recorded fixtures ($0, CI); record: live Bedrock, one fixture per scenario; live: nothing written."""
    from .config import MODELS
    from .llm import BedrockLLM, RecordingLLM, ReplayLLM

    spec = MODELS[model_key]
    recorders: list[tuple[str, Any]] = []

    def make_client(sid: str) -> Any:
        path = fixtures_dir / model_key / f"{sid}.json"
        if mode == "replay":
            return ReplayLLM(path)
        if mode == "record":
            rec = RecordingLLM(live_client or BedrockLLM(), path)
            recorders.append((sid, rec))
            return rec
        return live_client or BedrockLLM()

    out = judge(make_client, model_key, scenarios=scenarios)
    for sid, rec in recorders:
        rec.save({"scenario_id": sid, "model_id": spec.target, "prompt_version": JUDGE_PROMPT_VERSION})
    return {**out, "model": spec.target, "mode": mode}
