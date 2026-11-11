
from mc_agents.budget import QuestionBudget
from mc_agents.config import MODELS
from mc_agents.graph import GraphState, route, verify
from mc_agents.llm import BudgetedLLM, LLMRequest, LLMResponse
from mc_agents.specialists import SPECIALISTS, run_specialist, tool_specs

PLAN = {"seats": 10, "seat_price_cents": 5000, "included_units": 1000, "usage_units": 1500,
        "overage_rate_micro": 20000, "discount_bps": 0, "cost_cents": 20000,
        "addon_cents": 0, "outcome_price_micro": 0, "outcomes": 0}


class Script:
    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        step = self.steps.pop(0)
        content = step(req) if callable(step) else step
        return LLMResponse(content, "end_turn", 500, 50)


def use(name, args, i="t1"):
    return [{"toolUse": {"toolUseId": i, "name": name, "input": args}}]


def llm(client):
    return BudgetedLLM(client, QuestionBudget(MODELS["haiku-4-5"]))


def test_pricing_specialist_calls_tool_and_answer_verifies():
    s = GraphState("Forecast pricing for the pro plan")
    assert route(s) == "pricing"

    def answer(req):
        res = req.messages[-1]["content"][0]["toolResult"]["content"][0]["json"]
        return [{"text": f"Margin is {res['margin_cents']} cents [{res['evidence_id']}]."}]

    client = Script(use("price_plan", PLAN), answer)
    run_specialist(s, llm(client), "m")
    assert s.ledger.entries[0].tool == "price_plan@4" and s.answer
    assert verify(s) == "responder"


def test_tool_outside_allow_list_fails_closed():
    s = GraphState("Why did the leak start?")
    route(s)
    client = Script(use("price_plan", PLAN), [{"text": "No data."}])
    run_specialist(s, llm(client), "m")
    assert not s.ledger.entries
    res = client.requests[-1].messages[-2]["content"][0]["toolResult"]
    assert res["status"] == "error"


def test_bad_tool_input_is_a_tool_error_not_a_crash():
    s = GraphState("Forecast pricing")
    route(s)
    client = Script(use("price_plan", {"seats": -1}), [{"text": "Cannot price."}])
    run_specialist(s, llm(client), "m")
    assert not s.ledger.entries and s.answer == "Cannot price."


def test_tool_round_limit_stops_the_loop():
    s = GraphState("Forecast pricing")
    route(s)
    client = Script(*[use("price_plan", PLAN, f"t{i}") for i in range(10)])
    run_specialist(s, llm(client), "m")
    assert s.status == "failed" and s.issues == ["tool round limit reached"]


def test_unknown_route_fails_closed():
    s = GraphState("x")
    run_specialist(s, llm(Script()), "m")
    assert s.status == "failed"


def test_replay_lever_evidence_counts_for_lever_actions():
    s = GraphState("x")
    s.ledger.add("replay_lever@1", {}, {"allowed": True})
    s.answer = "Done [E1]."
    s.actions = [{"type": "apply_lever", "evidence": "E1"}]
    assert verify(s) == "hitl"


def test_every_specialist_tool_is_known_or_runtime_supplied():
    from mc_agents.tools import registry
    runtime = {"query_gold", "search_knowledge"}
    for sp in SPECIALISTS.values():
        assert all(t in registry.TOOLS or t in runtime for t in sp.tools)
        assert tool_specs(sp) is not None


def test_pricing_specialist_calls_tools_instead_of_asking():
    """3c-3c/3c-3d: AG-05 calls price_plan once (example plan, after, churn), keeps tool units, other specialists
    unchanged."""
    from mc_agents.specialists import SPECIALISTS, tool_specs

    pricing = SPECIALISTS["pricing"].system
    assert "Never ask the user" in pricing and "query_gold" in pricing and "churn_bps" in pricing
    assert "never convert to dollars or percent" in pricing
    # 3c-3e: approval requests are priced, churn always passes churn_bps, no partial plans, no restated %
    assert "\"Approve\" a discount means price it" in pricing and "never a partial plan" in pricing
    assert "pass churn_bps 200" in pricing
    # 3c-3g/3c-3i: no computed difference; a change only copies price_plan v4's delta (rule 3)
    assert "a change only a delta field, signed" in pricing and 'not "163 bps reduction"' in pricing
    assert "never restate its inputs" in pricing
    assert "call price_plan before any answer" in pricing and "if it has none, say so and use the example plan" in pricing
    # 3c-3h: a % only copies the price_plan v3 percent echo (changes_pct, churn_pct); the verifier is unchanged
    assert "a % only copies a _pct field" in pricing and "never write a % sign" not in pricing
    assert pricing.endswith("At most 4 short sentences.")
    assert "Never ask the user" not in SPECIALISTS["leak"].system
    # 3c-3g: AG-06 writes no numbered lists or questions; AG-07 answers change/waive/refund requests from the
    # authority documents; AG-03 (replayed by EV-05) keeps the shared rules only
    assert "Never number your points" in SPECIALISTS["efficiency"].system
    assert "never refuse it or ask for details" in SPECIALISTS["contract_policy"].system
    assert SPECIALISTS["cost_to_serve"].instructions == ""
    specs = {s["toolSpec"]["name"]: s["toolSpec"]["inputSchema"]["json"] for s in tool_specs(SPECIALISTS["pricing"])}
    assert SPECIALISTS["pricing"].tools == ("price_plan", "query_gold")  # churn is price_plan's churn_bps now
    assert specs["price_plan"]["required"] == [] and "after" in specs["price_plan"]["properties"]


def test_verifier_retry_tells_the_specialist_what_failed():
    """3c-3d: the retry used to resend the bare question, so the model repeated the same draft."""
    s = GraphState("Forecast pricing")
    route(s)
    s.answer = "Margin is $50."
    assert verify(s) == "supervisor" and s.issues == ["unsupported figures: $50"]
    client = Script([{"text": "No figures."}])
    run_specialist(s, llm(client), "m")
    text = client.requests[0].messages[0]["content"][0]["text"]
    assert text.startswith("Forecast pricing") and "failed verification: unsupported figures: $50." in text


def test_first_attempt_sends_the_bare_question():
    s = GraphState("Forecast pricing")
    route(s)
    client = Script([{"text": "No figures."}])
    run_specialist(s, llm(client), "m")
    assert client.requests[0].messages[0]["content"][0]["text"] == "Forecast pricing"
