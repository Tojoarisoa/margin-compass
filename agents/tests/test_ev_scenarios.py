from mc_agents import ev_scenarios as ev


def test_golden_set_shape():
    scs = ev.load_scenarios()
    assert len(scs) >= 30 and len({s["id"] for s in scs}) == len(scs)
    assert {s["jtbd"].split()[0] for s in scs} >= {"J1", "J2", "J3", "J4", "J5"}
    assert {t for s in scs for t in s["tools"]} <= ev.known_tools()


def test_ev07_fast_path_routes_every_scenario():
    r = ev.ev07()
    assert r["passed"] and r["ev07"] == 1.0, r


def test_ev07_flags_wrong_route_forbidden_tool_and_budget():
    scs = ev.load_scenarios()
    sc = next(s for s in scs if s["route"] == "pricing")

    def run(kind):
        out = {"route": sc["route"], "tools": [sc["tools"][0]], "llm_calls": 2}
        patch = {"route": {"route": "leak"}, "tool": {"tools": ["query_gold", "apply_everything"]},
                 "budget": {"llm_calls": 99}}.get(kind, {})
        return out | patch

    for kind in ("route", "tool", "budget"):
        assert ev.ev07(lambda s, k=kind: run(k), [sc])["failed"] == [sc["id"]]
    assert ev.ev07(lambda s: run("ok"), [sc])["passed"]


def test_ev08_grounded_and_seeded_errors_caught():
    r = ev.ev08()
    assert r["passed"] and r["catch_rate"] == 1.0 and r["ungrounded"] == 0, r


def test_seed_error_changes_the_first_figure_only():
    assert ev.seed_error("Margin is 30000 cents [E1].") == "Margin is 300007 cents [E1]."
    assert ev.seed_error("No figures [E1].") is None


def test_ev13_levers_and_discount_authority():
    r = ev.ev13()
    assert r["passed"] and r["ev13"] == 1.0, r


def test_ev13_detects_a_wrong_expectation():
    scs = [dict(s) for s in ev.load_scenarios() if s["id"] == "act-02"]
    scs[0]["expect"] = {"verdict": "hitl", "approver": "account_manager"}
    assert ev.ev13(scs)["failed"] == ["act-02"]


def test_ev07_over_the_real_graph_with_scripted_clients():
    from test_specialists import PLAN, Script, use
    scs = [s for s in ev.load_scenarios() if s["id"] in ("prc-01", "sec-01", "amb-01", "gov-01")]

    def client(sc):
        if sc["id"] == "prc-01":
            return Script(use("price_plan", PLAN), [{"text": "Done."}], [{"text": "Done."}], [{"text": "Done."}])
        if sc["id"] == "gov-01":
            return Script([{"text": "No policy found."}])
        return Script()

    assert ev.ev07(ev.graph_runner(client), scs)["failed"] == []
    # a model that asks for a tool outside the scenario's set is flagged
    bad = ev.ev07(ev.graph_runner(lambda sc: Script(use("price_plan", PLAN), [{"text": "x"}])), scs[1:2])
    assert bad["failed"] == ["gov-01"]


def test_cli_ev_runs_all_scorers(gold, capsys):
    import json

    from mc_agents.cli import main

    assert main(["--gold", str(gold), "ev"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"ev05": True, "ev06": True, "ev07": True, "ev08": True, "ev13": True, "passed": True}
