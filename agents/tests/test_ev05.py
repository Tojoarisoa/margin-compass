"""EV-05 scorer: execution-result comparison against the golden questions."""

import pytest

from mc_agents import ev05
from mc_agents.tools.sql_guard import make_query_gold

QS = ev05.load_golden()


@pytest.fixture(scope="module")
def q(gold):
    return make_query_gold(gold)


def test_golden_is_well_formed():
    assert len(QS) >= 8 and len({x["id"] for x in QS}) == len(QS)
    assert all({"question", "reference_sql", "equivalent_sql", "wrong_sql"} <= set(x) for x in QS)


def test_reference_scores_full(q):
    by_q = {x["question"]: x["reference_sql"] for x in QS}
    out = ev05.score(q, by_q.__getitem__)
    assert out["ev05"] == 1.0 and out["passed"]


def test_equivalent_queries_pass(q):
    by_q = {x["question"]: x["equivalent_sql"] for x in QS}
    out = ev05.score(q, by_q.__getitem__)
    assert out["ev05"] == 1.0, [k for k, v in out["results"].items() if not v]


def test_wrong_queries_fail(q):
    by_q = {x["question"]: x["wrong_sql"] for x in QS}
    out = ev05.score(q, by_q.__getitem__)
    assert out["ev05"] == 0.0 and not out["passed"], [k for k, v in out["results"].items() if v]


def test_rejected_sql_is_a_miss(q):
    out = ev05.score(q, lambda _: "DROP TABLE fct_tenant_margin", QS[:2])
    assert out["ev05"] == 0.0


def test_order_matters_only_when_ordered():
    a, b = [[1, "x"], [2, "y"]], [[2, "y"], [1, "x"]]
    assert ev05.rows_match(a, b, ordered=False) and not ev05.rows_match(a, b, ordered=True)
    assert ev05.rows_match([[1.0000000001]], [[1.0]], ordered=True)


class _Script:
    """Asks `query_gold` with the given SQL (if any), then answers from the tool result."""

    def __init__(self, sql):
        self.sql, self.requests = sql, []

    def complete(self, req):
        from mc_agents.llm import LLMResponse
        self.requests.append(req)
        if self.sql is None or any("toolResult" in b for m in req.messages for b in m["content"]):
            return LLMResponse([{"text": "Done [E1]."}], "end_turn", 500, 50)
        return LLMResponse([{"toolUse": {"toolUseId": "t1", "name": "query_gold", "input": {"sql": self.sql}}}],
                           "tool_use", 500, 50)


def test_specialist_generator_scores_the_sql_the_model_sent(gold, q):
    for kind, want in (("reference_sql", 1.0), ("wrong_sql", 0.0)):
        by_q = {x["question"]: x[kind] for x in QS}
        gen = ev05.specialist_generator(lambda question, m=by_q: _Script(m[question]), gold)
        assert ev05.score(q, gen)["ev05"] == want


def test_specialist_generator_without_a_query_is_a_miss(gold, q):
    gen = ev05.specialist_generator(lambda _: _Script(None), gold)
    assert gen(QS[0]["question"]) == ""
    assert ev05.score(q, gen, QS[:2])["ev05"] == 0.0


def test_specialist_generator_offers_only_ag03_tools(gold):
    client = _Script(QS[0]["reference_sql"])
    ev05.specialist_generator(lambda _: client, gold)(QS[0]["question"])
    assert [t["toolSpec"]["name"] for t in client.requests[0].tools] == ["query_gold"]
