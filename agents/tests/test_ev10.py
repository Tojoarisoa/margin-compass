from mc_agents import ev10


def test_pass():
    r = ev10.score([(0.004, 3.0)] * 19 + [(0.006, 12.0)])
    assert r["passed"] and r["n"] == 20


def test_cost_over_gate_fails():
    assert not ev10.score([(0.02, 1.0)] * 5)["passed"]


def test_p95_latency_fails():
    assert not ev10.score([(0.001, 1.0)] * 18 + [(0.001, 25.0)] * 2)["passed"]


def test_single_slow_outlier_in_20_is_not_p95():
    assert ev10.score([(0.001, 1.0)] * 19 + [(0.001, 99.0)])["passed"]


def test_empty_fails_closed():
    assert not ev10.score([])["passed"]


def test_eval_report_carries_ev10(gold):
    from mc_agents.evaluate import run_eval

    r = run_eval(gold, "haiku-4-5")
    assert r["ev10"]["n"] == r["total"] and all("latency_s" in q for q in r["questions"])
