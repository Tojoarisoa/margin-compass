from decimal import Decimal

import pytest

from mc_agents.budget import BudgetExceeded
from mc_agents.limits import RateLimited, RateLimiter, SpendCaps, pick_model


def test_pick_model_cheapest_and_preferred():
    assert pick_model("small").key == "nova-micro"
    assert pick_model("mid", "haiku-4-5").key == "haiku-4-5"
    assert pick_model("mid", "haiku-4-5").key == "haiku-4-5"
    assert pick_model("small", "haiku-4-5").key == "nova-micro"
    with pytest.raises(ValueError):
        pick_model("huge")


def test_rate_limiter_window():
    t = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: t[0])
    rl.acquire()
    rl.acquire()
    with pytest.raises(RateLimited):
        rl.acquire()
    t[0] = 11
    rl.acquire()


def test_spend_caps_fail_closed():
    s = SpendCaps(Decimal("0.01"))
    s.reserve(Decimal("0.006"))
    with pytest.raises(BudgetExceeded):
        s.reserve(Decimal("0.006"))
    s.record(Decimal("0.002"))
    s.reserve(Decimal("0.006"))


def test_budgeted_llm_uses_limiter_and_spend_caps():
    from mc_agents.budget import QuestionBudget
    from mc_agents.config import MODELS
    from mc_agents.llm import BudgetedLLM, LLMRequest, LLMResponse

    class Fake:
        calls = 0

        def complete(self, request):
            Fake.calls += 1
            return LLMResponse([{"text": "ok"}], "end_turn", 10, 5)

    caps = SpendCaps(Decimal("1"))
    llm = BudgetedLLM(Fake(), QuestionBudget(MODELS["haiku-4-5"]), spend=caps, limiter=RateLimiter(1))
    req = LLMRequest("m", "s", [{"role": "user", "content": [{"text": "hi"}]}], [])
    llm.complete(req)
    assert caps.spent > 0 and caps.reserved == 0
    with pytest.raises(RateLimited):
        llm.complete(req)
    assert Fake.calls == 1


def test_bedrock_config_retries_throttling_adaptively():
    from botocore.config import Config

    from mc_agents.llm import bedrock_config

    cfg = bedrock_config(Config)
    assert cfg.retries == {"mode": "adaptive", "max_attempts": 8}
    assert cfg.read_timeout == 60
