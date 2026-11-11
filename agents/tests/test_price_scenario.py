"""M4-05 step 3c-3d: price_plan v2 composes the calc-spec functions; it adds no formula of its own."""

import pytest

from mc_agents.ledger import Ledger
from mc_agents.tools import registry
from mc_agents.tools.churn_adjust import churn_adjust
from mc_agents.tools.metrics import ToolError
from mc_agents.tools.price_scenario import EXAMPLE_PLAN, price_scenario
from mc_agents.tools.pricing import price_plan


def test_no_plan_fields_uses_the_labelled_example_plan():
    out = price_scenario({})
    assert out["plan_source"] == "example" and out["plan"] == EXAMPLE_PLAN
    assert {k: out[k] for k in price_plan(EXAMPLE_PLAN)} == price_plan(EXAMPLE_PLAN)
    assert "after" not in out and "churn" not in out


def test_full_plan_matches_price_plan_v1():
    plan = {**EXAMPLE_PLAN, "seats": 3, "usage_cap_cents": 500}
    out = price_scenario(plan)
    assert out["plan_source"] == "given" and {k: out[k] for k in price_plan(plan)} == price_plan(plan)


def test_after_and_churn_are_the_calc_spec_functions():
    out = price_scenario({"after": {"discount_bps": 400}, "churn_bps": 200})
    after = price_plan({**EXAMPLE_PLAN, "discount_bps": 400})
    assert out["after"] == {"changes": {"discount_bps": 400}, **after}
    c = out["churn"]
    assert c["churn_bps"] == 200 and c["months"] == 12
    assert c["before"] == churn_adjust({"revenue_cents": out["revenue_cents"], "cost_cents": 20000, "churn_bps": 200,
                                        "months": 12})
    assert c["after"] == churn_adjust({"revenue_cents": after["revenue_cents"], "cost_cents": 20000, "churn_bps": 200,
                                       "months": 12})


def test_after_cost_change_is_used_for_churn():
    out = price_scenario({"after": {"cost_cents": 10000}, "churn_bps": 100, "months": 6})
    assert out["churn"]["after"]["adj_cost_cents"] == churn_adjust(
        {"revenue_cents": out["after"]["revenue_cents"], "cost_cents": 10000, "churn_bps": 100, "months": 6})["adj_cost_cents"]


@pytest.mark.parametrize("bad", [
    {"seats": 10},  # partial plan: never mixed with example values
    {"after": {}}, {"after": {"bogus": 1}}, {"after": 5},
    {"months": 6},  # months without churn_bps
    {"surprise": 1},
    {"after": {"discount_bps": 10001}}, {"churn_bps": 10001},
])
def test_bad_inputs_fail_closed_and_leave_no_evidence(bad):
    led = Ledger()
    with pytest.raises(ToolError):
        registry.call("price_plan", bad, led)
    assert led.entries == []


def test_ledger_holds_every_figure_the_answer_may_quote():
    led = Ledger()
    registry.call("price_plan", {"after": {"discount_bps": 400}, "churn_bps": 200}, led)
    vals = led.values()
    assert led.entries[0].tool == "price_plan@2"
    assert {5000, 20000, 400, 200, 12} <= {int(v) for v in vals}
