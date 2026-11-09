from decimal import Decimal

from mc_agents import investigate as inv
from mc_agents.config import MODELS
from mc_agents.llm import LLMRequest, LLMResponse
from mc_agents.nightly import _action


class Fake:
    def __init__(self, text="Check the latest release for a retry loop.", out=80):
        self.text, self.out, self.requests = text, out, []

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        return LLMResponse([{"text": self.text}], "end_turn", 400, self.out)


def _actions(n):
    return [_action("r1", "ACT-1", f"F{i}/cost", f"Leak {i}", Decimal(1000 - i), Decimal("0.8"), 2, "none", "low") for i in range(n)]


def test_top_five_plus_one_batch_call_and_cost_recorded():
    f = Fake()
    r = inv.investigate(_actions(9), f)
    assert r.calls == 6 and len(f.requests) == 6 and len(r.insights) == 6 and r.usd > 0 and not r.stopped
    assert r.insights[-1].action_id == "batch"


def test_answer_with_invented_number_is_dropped():
    r = inv.investigate(_actions(2), Fake("Costs rose 47% after the release."))
    assert r.insights == [] and r.dropped == 2


def test_numbers_from_the_facts_are_allowed():
    a = _actions(1)[0]
    assert inv.numbers_ok("About $1000.00/month is at stake.", inv._facts(a)) and not inv.numbers_ok("12 tenants", inv._facts(a))


def test_nightly_cap_is_enforced_before_the_call():
    f = Fake()
    r = inv.investigate(_actions(6), f, max_usd=Decimal("0.0001"))
    assert f.requests == [] and r.calls == 0 and "cap" in r.stopped


def test_call_cap_and_default_cap_value():
    assert inv.NIGHTLY_MAX_USD == Decimal("0.50") and inv.NIGHTLY_MAX_CALLS == 8
    assert inv.TOP_INVESTIGATED + 1 <= inv.NIGHTLY_MAX_CALLS


def test_memory_roundtrip_feeds_next_prompt(tmp_path):
    p = tmp_path / "memory" / "episodic.jsonl"
    f = Fake()
    r = inv.investigate(_actions(1), f)
    inv.remember(p, "r1", r.insights)
    mem = inv.load_memory(p)
    assert mem["F0/cost"] == r.insights[0].text
    f2 = Fake()
    inv.investigate(_actions(1), f2, memory=mem)
    assert "Last night's finding" in f2.requests[0].messages[0]["content"][0]["text"]
    assert inv.load_memory(tmp_path / "missing.jsonl") == {}


def test_uses_model_target():
    f = Fake()
    inv.investigate(_actions(1), f, spec=MODELS["haiku-4-5"])
    assert f.requests[0].model_id == MODELS["haiku-4-5"].target
