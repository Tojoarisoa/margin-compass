"""EV-12 (Python side): the lever replay matches the shared calc-spec vectors exactly."""

import json
from pathlib import Path

import pytest

from mc_agents.tools.levers import replay_lever

VECTORS = json.loads((Path(__file__).parents[2] / "calc-spec/vectors/levers_v1.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector(v):
    assert replay_lever(v["input"]) == v["expected"]


def test_safety_floor_rejects_even_when_quality_fine():
    r = replay_lever({**VECTORS[0]["input"], "route_bps": 4000, "quality_drop_bps": 0, "recall_drop_bps": 200})
    assert r["quality_ok"] and not r["recall_ok"] and r["applied_savings_cents"] == 0


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        replay_lever({**VECTORS[0]["input"], "route_bps": 10001})
    with pytest.raises(ValueError):
        replay_lever({**VECTORS[0]["input"], "cost_cents": -1})
