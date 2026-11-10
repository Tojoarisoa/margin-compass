"""EV-06 step 2: rubric-based LLM judge (PLAN.md §9, M4-05), with a scripted client (no network)."""

import json

import pytest

from mc_agents.ev06 import reference_run
from mc_agents.ev06_judge import CRITERIA, judge, judge_message, judgeable, parse_verdict, run_judge
from mc_agents.ev_scenarios import load_scenarios
from mc_agents.llm import FixtureDrift, LLMResponse


def _verdict(**over):
    return {"toolUse": {"toolUseId": "v1", "name": "record_verdict",
                        "input": {**{c: True for c in CRITERIA}, "reason": "ok", **over}}}


class Judge:
    """Passes a run only when its route matches the scenario (a stand-in for the model)."""

    def __init__(self):
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        body = json.loads(req.messages[0]["content"][0]["text"])
        good = body["run"]["route"] == body["scenario"]["expected_route"]
        return LLMResponse([_verdict(route=good)], "tool_use", 800, 40)


def test_all_reference_runs_pass_and_agree_with_rubric():
    j = Judge()
    r = judge(lambda sid: j)
    assert r["passed"] and r["judge"] == 1.0 and r["agreement_with_rubric"] == 1.0 and r["failed"] == []
    full = [s for s in load_scenarios() if judgeable(s)]
    assert len(j.requests) == r["judged"] == len(full) >= 13
    assert r["judged"] + len(r["not_judged"]) == len(load_scenarios())
    req = j.requests[0]
    assert req.tools[0]["toolSpec"]["name"] == "record_verdict" and req.max_tokens == 300


def test_judge_fail_lowers_rate_and_is_reported():
    scs = [s for s in load_scenarios() if judgeable(s)]
    bad = {s["id"] for s in scs[:5]}
    r = judge(lambda sid: Judge(), run=lambda s: {**reference_run(s), "route": "x"} if s["id"] in bad else reference_run(s))
    assert set(r["failed"]) == bad and r["judge"] == (len(scs) - 5) / len(scs)
    assert r["agreement_with_rubric"] == 1.0  # the rubric fails the same runs
    assert set(r["reasons"]) == bad


@pytest.mark.parametrize("content", [
    [{"text": "looks fine"}],                       # no tool call
    [_verdict(route="yes")],                        # not a boolean
    [_verdict(), _verdict()],                       # two verdicts
])
def test_missing_or_malformed_verdict_fails_closed(content):
    assert parse_verdict(content) is None

    class Bad:
        def complete(self, req):
            return LLMResponse(content, "end_turn", 800, 40)

    sc = load_scenarios()[0]
    r = judge(lambda sid: Bad(), scenarios=[sc])
    assert r["failed"] == [sc["id"]] and r["no_verdict"] == [sc["id"]] and not r["passed"]


def test_empty_set_fails_closed():
    assert judge(lambda sid: Judge(), scenarios=[])["passed"] is False


def test_message_carries_evidence_but_no_expected_answer():
    sc = next(s for s in load_scenarios() if s.get("answer") and s.get("evidence"))
    body = json.loads(judge_message(sc, reference_run(sc)))
    assert body["run"]["evidence"][0]["id"] == "E1"
    assert "answer" not in body["scenario"]  # the judge grades the run, not a copy of the reference


def test_record_then_replay(tmp_path):
    scs = [s for s in load_scenarios() if judgeable(s)][:3]
    rec = run_judge("haiku-4-5", "record", tmp_path, live_client=Judge(), scenarios=scs)
    assert rec["passed"] and len(list((tmp_path / "haiku-4-5").glob("*.json"))) == 3
    rep = run_judge("haiku-4-5", "replay", tmp_path, scenarios=scs)
    assert rep["judge"] == rec["judge"] == 1.0
    with pytest.raises(FixtureDrift):
        run_judge("haiku-4-5", "replay", tmp_path, scenarios=load_scenarios()[3:4])
