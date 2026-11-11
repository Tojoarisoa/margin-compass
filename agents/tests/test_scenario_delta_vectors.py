"""EV-12 (Python side): scenario difference v1 matches the shared calc-spec vectors exactly (M4-05 step 3c-3i)."""

import json
from pathlib import Path

import pytest

from mc_agents.tools.scenario_delta import scenario_delta

VECTORS = json.loads((Path(__file__).parents[2] / "calc-spec/vectors/delta_v1.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector(v):
    assert scenario_delta(v["input"]) == v["expected"]


def test_enough_vectors():
    assert len(VECTORS) >= 8


@pytest.mark.parametrize("bad", [
    {"before": {"revenue_cents": 1}, "after": {}},              # one side only
    {"before": {}, "after": {}},                                # nothing to compare
    {"before": {"revenue_cents": None}, "after": {"revenue_cents": 1}},  # null only for margin_bps
    {"before": {"margin_cents": 1.5}, "after": {"margin_cents": 1}},
    {"before": {"margin_cents": True}, "after": {"margin_cents": 1}},
])
def test_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        scenario_delta(bad)
