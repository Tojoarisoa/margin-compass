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
