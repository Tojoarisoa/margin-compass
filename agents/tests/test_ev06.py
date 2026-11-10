"""EV-06 task-success rubric (PLAN.md §9, M4-05)."""

from mc_agents.ev06 import EV06_GATE, ev06, reference_run, task_success
from mc_agents.ev_scenarios import load_scenarios, seed_error


def test_reference_run_passes_gate_on_every_job():
    r = ev06()
    assert r["passed"] and r["ev06"] >= EV06_GATE and r["failed"] == []
    assert set(r["by_jtbd"]) >= {"J1 spend", "J2 anomaly", "J3 forecast and pricing", "J4 optimization", "J5 governance"}


def test_empty_set_fails_closed():
    assert ev06(scenarios=[])["passed"] is False


def _first(pred):
    return next(s for s in load_scenarios() if pred(s))


def test_wrong_route_or_forbidden_tool_fails():
    sc = _first(lambda s: s.get("answer") and s["route"] != "blocked")
    assert task_success(sc, {**reference_run(sc), "route": "blocked"}) is False
    assert task_success(sc, {**reference_run(sc), "tools": [*sc["tools"], "delete_everything"]}) is False


def test_corrupted_figure_fails():
    sc = _first(lambda s: s.get("answer") and seed_error(s["answer"]) and s["route"] != "blocked")
    assert task_success(sc, {**reference_run(sc), "answer": seed_error(sc["answer"])}) is False


def test_blocked_scenario_must_end_blocked():
    sc = _first(lambda s: s["route"] == "blocked")
    assert task_success(sc, {**reference_run(sc), "status": "answered"}) is False


def test_rate_counts_failures():
    scs = load_scenarios()
    bad = {s["id"] for s in scs[:5]}
    r = ev06(lambda s: {**reference_run(s), "route": "x"} if s["id"] in bad else reference_run(s), scs)
    assert r["ev06"] == (len(scs) - 5) / len(scs) and set(r["failed"]) == bad and r["passed"] is (r["ev06"] >= EV06_GATE)
