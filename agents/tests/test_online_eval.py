"""M6-02 step 2: online evaluation sampling, scripted clients (no network)."""

from datetime import date

import pytest
from test_ev06_graph import SC_PRICING, good
from test_specialists import PLAN, Script, use

from mc_agents.ev06_graph import default_scenarios, run_graph
from mc_agents.online_eval import daily_sample, online_eval

DAY = date(2026, 11, 11)


def test_sample_is_deterministic_and_rotates():
    scs = default_scenarios()
    a = daily_sample(DAY)
    assert a == daily_sample(DAY) and len(a) == 3 and all(s in scs for s in a)
    days = [date(2026, 11, d) for d in range(1, 31)]
    seen = {s["id"] for d in days for s in daily_sample(d)}
    assert len(seen) > 3  # different days pick different scenarios
    assert daily_sample(DAY, k=0) == []


def test_empty_sample_fails_loudly(gold, tmp_path):
    with pytest.raises(ValueError):
        online_eval(gold, "haiku-4-5", DAY, k=0, fixtures_dir=tmp_path)


def test_live_matches_recording(gold, tmp_path):
    run_graph(gold, "haiku-4-5", "record", tmp_path, live_client=Script(use("price_plan", PLAN), good), scenarios=[SC_PRICING])
    out = online_eval(gold, "haiku-4-5", DAY, fixtures_dir=tmp_path, scenarios=[SC_PRICING],
                      live_client=Script(use("price_plan", PLAN), good))
    assert out["sample"] == ["t-prc"] and out["changed"] == [] and out["stale_fixtures"] is False
    assert out["live"]["ev06"] == 1.0 and out["recorded"]["ev06"] == 1.0 and out["synthetic"] is True


def test_live_change_marks_fixtures_stale(gold, tmp_path):
    run_graph(gold, "haiku-4-5", "record", tmp_path, live_client=Script(use("price_plan", PLAN), good), scenarios=[SC_PRICING])
    bad = [{"text": "Margin is 999999 cents [E1]."}]
    out = online_eval(gold, "haiku-4-5", DAY, fixtures_dir=tmp_path, scenarios=[SC_PRICING],
                      live_client=Script(*([use("price_plan", PLAN), bad] * 3)))
    assert out["changed"] == ["t-prc"] and out["stale_fixtures"] is True
    assert out["live"]["runs"]["t-prc"]["status"] == "unverified" and out["live"]["failed"] == ["t-prc"]


def test_report_has_no_question_or_answer_text(gold, tmp_path):
    run_graph(gold, "haiku-4-5", "record", tmp_path, live_client=Script(use("price_plan", PLAN), good), scenarios=[SC_PRICING])
    out = online_eval(gold, "haiku-4-5", DAY, fixtures_dir=tmp_path, scenarios=[SC_PRICING],
                      live_client=Script(use("price_plan", PLAN), good))
    text = repr(out)
    assert SC_PRICING["question"] not in text and "Margin is" not in text


def test_cli_online_eval(gold, tmp_path, monkeypatch):
    import json

    from mc_agents import cli
    from mc_agents import online_eval as mod

    seen = {}

    def fake(gold_dir, model_key, day, k, live_client):
        seen.update(day=day, k=k)
        return {"day": day.isoformat(), "model": "m", "sample": ["x"], "changed": [], "stale_fixtures": False, "synthetic": True}

    monkeypatch.setattr(mod, "online_eval", fake)
    monkeypatch.setattr(cli, "BedrockLLM", lambda: object())
    out = tmp_path / "online.json"
    assert cli.main(["--gold", str(gold), "online-eval", "--day", "2026-11-11", "--k", "2", "--out", str(out)]) == 0
    assert seen == {"day": DAY, "k": 2} and json.loads(out.read_text())["sample"] == ["x"]
