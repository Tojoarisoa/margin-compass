"""EV-12 (Python side): churn-adjusted revenue matches the shared calc-spec vectors exactly."""

import json
from pathlib import Path

import pytest

from mc_agents.tools.churn_adjust import churn_adjust

VECTORS = json.loads((Path(__file__).parents[2] / "calc-spec/vectors/churn_v1.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector(v):
    assert churn_adjust(v["input"]) == v["expected"]


def test_no_churn_keeps_full_revenue():
    r = churn_adjust({"revenue_cents": 1000, "cost_cents": 400, "churn_bps": 0, "months": 12})
    assert r["adj_revenue_cents"] == 12000 and r["adj_margin_cents"] == 7200


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        churn_adjust({"revenue_cents": 1, "cost_cents": 1, "churn_bps": 10001, "months": 1})
    with pytest.raises(ValueError):
        churn_adjust({"revenue_cents": 1, "cost_cents": 1, "churn_bps": 1, "months": 0})
