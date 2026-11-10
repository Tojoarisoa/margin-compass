"""EV-06 agent task success over the golden scenarios (PLAN.md §9, gate 90%), step 1: deterministic rubric.

A scenario succeeds when the run took the expected route, used only allowed tools, and finished the job:
blocked scenarios end blocked; answerable ones end with an answer that verifies against the run's own
evidence ledger (`verify_answer`). The rate is also reported per job-to-be-done (`jtbd`).

The rubric-based LLM judge calibrated on human labels is a later step; this rubric is its deterministic
floor and runs with no model. The default runner replays each scenario's recorded evidence and answer
(a harness check, like EV-05 `reference`); pass a graph runner to score a real or recorded run.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .ev_scenarios import _ledger, load_scenarios
from .ledger import Ledger, verify_answer

EV06_GATE = 0.90


def reference_run(sc: dict[str, Any]) -> dict[str, Any]:
    """Replays the scenario's recorded route, tools, evidence and answer (no model)."""
    blocked = sc["route"] == "blocked"
    return {"route": sc["route"], "tools": list(sc["tools"]), "status": "blocked" if blocked else "answered",
            "answer": sc.get("answer") or "", "ledger": _ledger(sc)}


def task_success(sc: dict[str, Any], out: dict[str, Any]) -> bool:
    if out["route"] != sc["route"] or not set(out["tools"]) <= set(sc["tools"]):
        return False
    if sc["route"] == "blocked":
        return out["status"] == "blocked"
    if not sc.get("answer"):  # no expected answer (e.g. unverified, approval-only): route and tools decide
        return out["status"] != "blocked"
    led: Ledger = out["ledger"]
    return out["status"] == "answered" and bool(out["answer"]) and verify_answer(out["answer"], led, sc["question"]).ok


def ev06(run: Callable[[dict[str, Any]], dict[str, Any]] = reference_run,
         scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scs = scenarios if scenarios is not None else load_scenarios()
    ok: dict[str, bool] = {sc["id"]: task_success(sc, run(sc)) for sc in scs}
    by_job: dict[str, list[bool]] = defaultdict(list)
    for sc in scs:
        by_job[sc["jtbd"]].append(ok[sc["id"]])
    rate = sum(ok.values()) / len(ok) if ok else 0.0  # empty set fails closed
    return {"ev06": rate, "passed": bool(ok) and rate >= EV06_GATE,
            "by_jtbd": {k: sum(v) / len(v) for k, v in sorted(by_job.items())},
            "failed": sorted(k for k, v in ok.items() if not v)}
