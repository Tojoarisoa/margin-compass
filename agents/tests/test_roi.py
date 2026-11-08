import pytest

from mc_agents.ledger import Ledger
from mc_agents.tools.metrics import ToolError
from mc_agents.tools.registry import call
from mc_agents.tools.roi import roi_multiple


def test_roi_values():
    assert roi_multiple({"margin_recovered_cents": 30000, "platform_cost_cents": 10000}) == {"net_cents": 20000, "roi_bps": 20000}
    r = roi_multiple({"margin_recovered_cents": 5000, "platform_cost_cents": 10000, "monthly_saving_cents": 3000})
    assert r == {"net_cents": -5000, "roi_bps": -5000, "payback_months": 4}
    assert roi_multiple({"margin_recovered_cents": 0, "platform_cost_cents": 1, "monthly_saving_cents": 0})["payback_months"] == -1


def test_roi_rejects_bad_input():
    for bad in ({"margin_recovered_cents": 1, "platform_cost_cents": 0}, {"margin_recovered_cents": -1, "platform_cost_cents": 5},
                {"margin_recovered_cents": 1.5, "platform_cost_cents": 5}):
        with pytest.raises(ValueError):
            roi_multiple(bad)


def test_roi_through_registry():
    led = Ledger()
    ev = call("roi_multiple", {"margin_recovered_cents": 30000, "platform_cost_cents": 10000}, led)
    assert ev.tool == "roi_multiple@1" and ev.result["roi_bps"] == 20000
    with pytest.raises(ToolError):
        call("roi_multiple", {"platform_cost_cents": 0, "margin_recovered_cents": 1}, led)
