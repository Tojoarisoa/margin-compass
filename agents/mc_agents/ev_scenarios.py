"""EV-07 trajectory, EV-08 groundedness and EV-13 recommendation quality over the golden scenarios (PLAN.md §9).

The scorers are deterministic and need no model: EV-07 scores a `run(scenario)` callable (the real graph in
production, the supervisor fast path by default, a stub in tests); EV-08 and EV-13 replay each scenario's
recorded evidence and answer through the same verifier the graph uses (`verify_answer`, `verify`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .graph import GraphState, route, verify
from .ledger import Ledger, verify_answer
from .tools import registry

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "scenarios.json"
EV07_GATE, EV08_GATE, EV13_GATE = 0.95, 0.95, 1.0
MAX_LLM_CALLS = 6  # specialist tool rounds plus one verifier retry; above this the trajectory is too long

_NUMBER = re.compile(r"(?<![\w\[-])-?\d[\d,]*(?:\.\d+)?")


def load_scenarios(path: Path = GOLDEN) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text())["scenarios"]


def fast_path(sc: dict[str, Any]) -> dict[str, Any]:
    """Default EV-07 runner: the deterministic supervisor route, no specialist and no model call."""
    st = GraphState(sc["question"])
    nxt = route(st)
    got = st.route or ("blocked" if nxt == "end" else "unverified")
    return {"route": got, "tools": [], "llm_calls": 0}


def ev07(run: Callable[[dict[str, Any]], dict[str, Any]] = fast_path,
         scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Route accuracy, tools inside the scenario's allowed set (none forbidden), LLM-call budget."""
    scs = scenarios if scenarios is not None else load_scenarios()
    results = {}
    for sc in scs:
        out = run(sc)
        results[sc["id"]] = (out["route"] == sc["route"] and set(out["tools"]) <= set(sc["tools"])
                             and out["llm_calls"] <= MAX_LLM_CALLS)
    rate = sum(results.values()) / len(results) if results else 0.0
    return {"ev07": rate, "passed": rate >= EV07_GATE, "failed": sorted(k for k, v in results.items() if not v)}


def _ledger(sc: dict[str, Any]) -> Ledger:
    led = Ledger()
    if sc.get("evidence"):
        e = sc["evidence"]
        led.add(e["tool"], e["args"], e["result"])
    return led


def seed_error(answer: str) -> str | None:
    """Corrupts the first figure of a grounded answer (appends a digit); None if it has no figure."""
    m = _NUMBER.search(answer)
    return None if m is None else answer[:m.end()] + "7" + answer[m.end():]


def ev08(scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Grounded answers must verify; each seeded numeric error must be caught."""
    scs = [s for s in (scenarios if scenarios is not None else load_scenarios()) if s.get("answer")]
    supported = ungrounded = caught = seeded = 0
    for sc in scs:
        led = _ledger(sc)
        supported += verify_answer(sc["answer"], led, sc["question"]).ok
        bad = seed_error(sc["answer"])
        if bad is not None:
            seeded += 1
            v = verify_answer(bad, led, sc["question"])
            caught += not v.ok
            ungrounded += v.ok  # a corrupted figure that passed as grounded
    sup = supported / len(scs) if scs else 0.0
    catch = caught / seeded if seeded else 0.0
    return {"ev08": sup, "catch_rate": catch, "ungrounded": ungrounded,
            "passed": sup >= EV08_GATE and catch >= EV08_GATE and ungrounded == 0}


def ev13(scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Levers respect the quality guardrail and discounts the authority matrix: 100% of cases."""
    scs = [s for s in (scenarios if scenarios is not None else load_scenarios()) if s.get("expect")]
    bad = []
    for sc in scs:
        st = GraphState(sc["question"])
        st.ledger, st.answer, st.actions = _ledger(sc), sc.get("answer") or "", sc["actions"]
        verdict = "hitl" if verify(st) == "hitl" else "fail"
        want = sc["expect"]
        if verdict != want["verdict"] or (verdict == "hitl" and st.approver != want["approver"]):
            bad.append(sc["id"])
    rate = 1 - len(bad) / len(scs) if scs else 0.0
    return {"ev13": rate, "passed": rate >= EV13_GATE, "failed": bad}


def known_tools() -> set[str]:
    return set(registry.TOOLS) | {"query_gold", "search_knowledge"}
