import pytest

from mc_agents.ledger import Ledger
from mc_agents.tools.metrics import ToolError
from mc_agents.tools.registry import TOOLS, call, catalog

CHURN = {"revenue_cents": 100000, "cost_cents": 40000, "churn_bps": 200, "months": 12}


def test_call_records_evidence():
    led = Ledger()
    ev = call("churn_adjust", CHURN, led)
    assert ev.id == "E1" and ev.tool == "churn_adjust@1" and led.entries == [ev]
    assert ev.result["survival_bps"] > 0


def test_idempotent_same_hash():
    led = Ledger()
    assert call("churn_adjust", CHURN, led).sha == call("churn_adjust", CHURN, led).sha


def test_unknown_tool_and_bad_input():
    led = Ledger()
    with pytest.raises(ToolError):
        call("drop_table", {}, led)
    with pytest.raises(ToolError):
        call("churn_adjust", {**CHURN, "months": 0}, led)
    with pytest.raises(ToolError):
        call("churn_adjust", {"months": 3}, led)
    assert led.entries == []  # failed calls leave no evidence


def test_catalog_is_read_only():
    assert {c["name"] for c in catalog()} == set(TOOLS)
    assert all(c["read_only"] for c in catalog())


def test_pricing_tool_schemas_match_tool_inputs():
    """3c-3c/3c-3d: price_plan (v2) and churn_adjust are offered with explicit integer schemas matching their inputs."""
    from mc_agents.tools import churn_adjust as ca
    from mc_agents.tools import pricing

    pp = TOOLS["price_plan"].input_schema
    assert TOOLS["price_plan"].version == "4" and pp["required"] == []  # no plan fields: the example plan
    assert set(pp["properties"]) == {*pricing._FIELDS, "usage_cap_cents", "after", "churn_bps", "months"}
    assert set(pp["properties"]["after"]["properties"]) == {*pricing._FIELDS, "usage_cap_cents"}
    ch = TOOLS["churn_adjust"].input_schema
    assert set(ch["required"]) == set(ch["properties"]) == set(ca._FIELDS)
    props = [p for k, p in pp["properties"].items() if k != "after"] + list(ch["properties"].values())
    assert all(p["type"] == "integer" for p in props)
