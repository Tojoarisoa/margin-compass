"""EV-12 (Python side): the pricing engine matches the shared calc-spec vectors exactly."""

import json
from pathlib import Path

import pytest

from mc_agents.tools.pricing import price_plan, round_div

VECTORS = json.loads((Path(__file__).parents[2] / "calc-spec/vectors/pricing_v1.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector(v):
    assert price_plan(v["input"]) == v["expected"]


def test_round_half_up():
    assert round_div(5, 10) == 1 and round_div(4, 10) == 0 and round_div(15, 10) == 2


def test_rejects_bad_input():
    bad = {**VECTORS[0]["input"], "seats": -1}
    with pytest.raises(ValueError):
        price_plan(bad)
    with pytest.raises(ValueError):
        price_plan({**VECTORS[0]["input"], "discount_bps": 10001})
