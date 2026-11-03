import json
from decimal import Decimal

import pytest

from mc_agents.analyst import answer_question
from mc_agents.budget import BudgetExceeded, QuestionBudget, call_cost
from mc_agents.config import MODELS
from mc_agents.evaluate import EVAL_DIR, run_eval
from mc_agents.llm import FixtureDrift, LLMRequest, LLMResponse, RecordingLLM, ReplayLLM

from scripted import ScriptedLLM, good_answer, load_questions

Q = load_questions(EVAL_DIR)


@pytest.mark.parametrize("qid", sorted(Q))
def test_good_model_answers_every_question_grounded(gold, qid):
    r = answer_question(Q[qid]["question"], gold_dir=gold, client=good_answer(Q, qid))
    assert r.status == "answered", r.verification
    assert r.llm_calls == 2 and r.cost_usd <= Decimal("0.01")
    assert r.evidence[0]["tool"] == Q[qid]["expected_tool"]["name"]
    assert r.cost_line.startswith("Cost of this answer: $") and "Claude Haiku 4.5" in r.cost_line


def test_cost_is_computed_from_adr003_prices(gold):
    r = answer_question(Q["q1"]["question"], gold_dir=gold, client=good_answer(Q, "q1"), model_key="haiku-5-5")
    spec = MODELS["haiku-5-5"]
    assert r.cost_usd == call_cost(spec, 900, 60) + call_cost(spec, 1400, 80)
    assert r.cost_usd == Decimal("0.000330")  # (2,300 x $0.11 + 140 x $0.55) / 1M


def test_fabricated_figure_is_revised_once_then_withheld(gold):
    client = ScriptedLLM("tenant_margin", Q["q1"]["expected_tool"]["args"],
                         lambda r: f"Margin was about $3,800 (98%) [{r['evidence_id']}].")
    r = answer_question(Q["q1"]["question"], gold_dir=gold, client=client)
    assert r.status == "unverified" and "$3,800" not in r.answer
    assert r.llm_calls == 3  # tool call, draft, one revision
    assert "Verifier:" in client.requests[-1].messages[-1]["content"][0]["text"]


def test_revision_that_fixes_the_figure_is_accepted(gold):
    drafts = iter(["Margin was about $3,800 [E1].", None])

    def write(r):
        d = next(drafts)
        return d if d else f"Margin was {r['gross_margin_usd']} ({r['gross_margin_pct']}) [{r['evidence_id']}]."

    client = ScriptedLLM("tenant_margin", Q["q1"]["expected_tool"]["args"], write)
    r = answer_question(Q["q1"]["question"], gold_dir=gold, client=client)
    assert r.status == "answered" and r.llm_calls == 3


def test_tool_error_is_returned_to_the_model_not_raised(gold):
    client = ScriptedLLM("tenant_margin", {"tenant_id": "bc-t9999", "start_date": "2025-09-01", "end_date": "2025-09-30"},
                         lambda r: "I couldn't find that tenant.")
    r = answer_question("What was bc-t9999's margin?", gold_dir=gold, client=client)
    assert r.status == "answered" and r.evidence == []
    tool_msg = client.requests[1].messages[-1]["content"][0]["toolResult"]
    assert tool_msg["status"] == "error" and "unknown tenant" in json.dumps(tool_msg)


def test_call_cap_stops_before_the_ninth_call():
    b = QuestionBudget(MODELS["haiku-5-5"], max_calls=8)
    for _ in range(8):
        b.reserve("x")
        b.record(10, 10)
    with pytest.raises(BudgetExceeded, match="call cap"):
        b.reserve("x")


def test_default_model_is_the_interim_mid_choice():
    from mc_agents.config import DEFAULT_ANALYST_MODEL

    assert DEFAULT_ANALYST_MODEL == "haiku-4-5" and MODELS[DEFAULT_ANALYST_MODEL].tier == "mid"


def test_dollar_cap_blocks_an_expensive_call():
    b = QuestionBudget(MODELS["haiku-4-5"], max_usd=Decimal("0.001"))
    with pytest.raises(BudgetExceeded, match="cost cap"):
        b.reserve("x" * 3000)


def test_tool_loop_is_bounded(gold):
    class AlwaysTool:
        def complete(self, req):
            return LLMResponse([{"toolUse": {"toolUseId": "t", "name": "portfolio_margin",
                                             "input": {"start_date": "2025-08-01", "end_date": "2025-08-31"}}}], "tool_use", 500, 30)

    r = answer_question("loop", gold_dir=gold, client=AlwaysTool())
    assert r.status == "unverified" and r.llm_calls <= 8


def test_record_then_replay_round_trip_and_drift(gold, tmp_path):
    fixture = tmp_path / "q1.json"
    rec = RecordingLLM(good_answer(Q, "q1"), fixture)
    first = answer_question(Q["q1"]["question"], gold_dir=gold, client=rec)
    rec.save({"question_id": "q1"})
    replay = answer_question(Q["q1"]["question"], gold_dir=gold, client=ReplayLLM(fixture))
    assert replay.answer == first.answer and replay.cost_usd == first.cost_usd
    with pytest.raises(FixtureDrift, match="changed"):
        answer_question("A different question", gold_dir=gold, client=ReplayLLM(fixture))


def test_no_prompt_content_in_telemetry(gold, caplog):
    caplog.set_level("INFO", logger="mc_agents")
    answer_question(Q["q1"]["question"], gold_dir=gold, client=good_answer(Q, "q1"))
    fields = [getattr(r, "fields", {}) for r in caplog.records]
    blob = json.dumps(fields)
    assert "gen_ai.usage.input_tokens" in blob
    assert "bc-t0003" not in blob and "September" not in blob and "$" not in blob.replace("mc.cost_usd", "")


def test_eval_runner_scores_the_scripted_model(gold, tmp_path):
    import shutil

    eval_dir = tmp_path / "m1_06"
    eval_dir.mkdir()
    shutil.copy(EVAL_DIR / "questions.json", eval_dir)

    class Router:
        """Picks the scripted answer for whichever question is being asked."""

        def complete(self, req: LLMRequest):
            text = req.messages[0]["content"][0]["text"]
            qid = next(k for k, q in Q.items() if q["question"] == text)
            return good_answer(Q, qid).complete(req)

    report = run_eval(gold, "haiku-5-5", mode="record", eval_dir=eval_dir, live_client=Router())
    assert report["passed"] == 5, [q for q in report["questions"] if not q["passed"]]
    replayed = run_eval(gold, "haiku-5-5", mode="replay", eval_dir=eval_dir)
    assert replayed["passed"] == 5 and replayed["cost_usd_total"] == report["cost_usd_total"]


@pytest.mark.parametrize("model_key", sorted(p.name for p in (EVAL_DIR / "fixtures").iterdir() if p.is_dir()))
def test_recorded_fixtures_replay_and_pass(gold, model_key):
    """M1-06 exit: the 5-question replay evaluation passes on the recorded Bedrock responses ($0, no network)."""
    report = run_eval(gold, model_key, mode="replay")
    assert report["passed"] == report["total"] == 5, [q for q in report["questions"] if not q["passed"]]
    assert report["max_llm_calls"] <= 8 and Decimal(report["cost_usd_per_question"]) <= Decimal("0.01")
