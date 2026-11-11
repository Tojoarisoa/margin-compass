"""EV-09 live API check (M6-03): selection and the stop-on-accept rule, with a fake transport."""

import json

from mc_agents import ev09_live
from mc_agents.api import API_BLOCKED


def test_selects_only_cases_the_api_refuses_before_spend():
    sel = ev09_live.live_cases()
    assert sel and all(c["critical"] for c in sel)
    assert {c["category"] for c in sel} <= set(API_BLOCKED) | {"too_long"}
    assert not [c for c in sel if c["category"] == "secrets"]  # the API leaves that rule to the analyst


def test_all_refused_passes():
    def post(url, body, headers):
        assert url == "https://x.example/api/ask" and headers["x-amz-content-sha256"]
        q = json.loads(body)["question"]
        return 400, ({} if len(q) > 300 else {"code": "blocked"})

    r = ev09_live.run("https://x.example/", post=post)
    assert r["passed"] and r["sent"] == r["selected"] and not r["failed"]
    assert "question" not in json.dumps(r)


def test_stops_at_the_first_accepted_case():
    calls = []

    def post(url, body, headers):
        calls.append(1)
        return (202, {"job_id": "a" * 32}) if len(calls) == 2 else (400, {"code": "blocked"})

    r = ev09_live.run("https://x.example", post=post, cases=[c for c in ev09_live.load_cases() if c["category"] == "injection"])
    assert len(calls) == 2 and r["accepted"] and not r["passed"] and r["sent"] == 2


def test_empty_selection_fails_closed():
    assert not ev09_live.run("https://x.example", post=lambda *a: (400, {}), cases=[])["passed"]
