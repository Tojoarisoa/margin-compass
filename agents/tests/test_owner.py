"""M5-03 step 4: owner-only approval write path."""

import base64
import json
from datetime import UTC, datetime

import pytest
from test_api import table  # noqa: F401 - moto-backed core table fixture

from mc_agents import api, owner

POOL, CLIENT, REGION = "us-east-1_TESTPOOL", "testclient123", "us-east-1"
NOW = datetime(2026, 11, 11, 13, 30, tzinfo=UTC)
DECISION = {"action_id": "act-0123456789ab", "action_type": "ACT-1", "target": "bc-t0003", "decision": "approved",
            "rationale": "Batch shift is low risk."}


def _token(**over):
    claims = {"token_use": "access", "iss": f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}", "client_id": CLIENT,
              "exp": int(NOW.timestamp()) + 600, "cognito:groups": ["owner"], "username": "owner1"} | over
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


def _event(body, token=None):
    headers = {"content-type": "application/json"} | ({"X-Mc-Owner-Token": token} if token else {})
    return {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/approvals", "headers": headers,
            "body": json.dumps(body)}


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    monkeypatch.setenv("OWNER_POOL_ID", POOL)
    monkeypatch.setenv("OWNER_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AWS_REGION", REGION)


def _ok_user(token):
    return {"Username": "owner1"}


def _items(t):
    return t.scan()["Items"]


def test_owner_decision_is_recorded(table):  # noqa: F811
    r = api.handle_approval(_event(DECISION, _token()), table=table, get_user=_ok_user, now=NOW)
    assert r["statusCode"] == 201
    [item] = _items(table)
    assert item["PK"] == "APPROVAL#act-0123456789ab" and item["SK"] == "DECIDED#2026-11-11T13:30:00+00:00"
    assert item["approver"] == "owner1" and item["decision"] == "approved" and "ttl" not in item
    assert {k: item[k] for k in ("action_id", "action_type", "target", "decision", "decided_at")} == {
        "action_id": "act-0123456789ab", "action_type": "ACT-1", "target": "bc-t0003", "decision": "approved",
        "decided_at": "2026-11-11T13:30:00+00:00"}


@pytest.mark.parametrize("token", [
    None, "", "not-a-jwt", "a.b.c",
    _token(token_use="id"),
    _token(client_id="other"),
    _token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OTHER"),
    _token(exp=int(NOW.timestamp()) - 1),
    _token(**{"cognito:groups": []}),
    _token(**{"cognito:groups": ["viewer"]}),
])
def test_non_owners_are_refused_without_a_cognito_call_or_write(table, token):  # noqa: F811
    r = api.handle_approval(_event(DECISION, token), table=table, get_user=lambda t: pytest.fail("no Cognito call"), now=NOW)
    assert r["statusCode"] == 401 and _items(table) == []


def test_token_cognito_rejects_is_refused(table):  # noqa: F811
    def revoked(token):
        raise RuntimeError("NotAuthorizedException: Access Token has been revoked")
    r = api.handle_approval(_event(DECISION, _token()), table=table, get_user=revoked, now=NOW)
    assert r["statusCode"] == 401 and _items(table) == []


def test_token_for_another_user_is_refused(table):  # noqa: F811
    r = api.handle_approval(_event(DECISION, _token()), table=table, get_user=lambda t: {"Username": "someone"}, now=NOW)
    assert r["statusCode"] == 401 and _items(table) == []


def test_missing_pool_config_refuses_everyone(table, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OWNER_POOL_ID", "")
    r = api.handle_approval(_event(DECISION, _token()), table=table, get_user=_ok_user, now=NOW)
    assert r["statusCode"] == 401 and _items(table) == []


@pytest.mark.parametrize("change", [
    {"action_id": "ACT-1"}, {"action_id": "act-xyz"}, {"action_type": "ACT-9"}, {"target": ""}, {"target": "a b"}, {"target": "a/b/c"}, {"target": "../x"},
    {"decision": "maybe"}, {"rationale": 5}, {"rationale": "x" * 501},
])
def test_bad_decisions_are_rejected_for_the_owner(table, change):  # noqa: F811
    r = api.handle_approval(_event(DECISION | change, _token()), table=table, get_user=_ok_user, now=NOW)
    assert r["statusCode"] == 400 and _items(table) == []


def test_latest_decision_wins_and_is_kept_as_history(table):  # noqa: F811
    api.handle_approval(_event(DECISION, _token()), table=table, get_user=_ok_user, now=NOW)
    later = NOW.replace(minute=45)
    api.handle_approval(_event(DECISION | {"decision": "rejected"}, _token(exp=int(later.timestamp()) + 60)),
                        table=table, get_user=_ok_user, now=later)
    items = sorted(_items(table), key=lambda i: i["SK"])
    assert [i["decision"] for i in items] == ["approved", "rejected"]


def test_route_is_wired(monkeypatch):
    seen = []
    monkeypatch.setattr(api, "handle_approval", lambda e: seen.append(e) or {"statusCode": 401})
    api.handler(_event(DECISION), None)
    assert seen and api.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/approvals"}, None)["statusCode"] == 404


@pytest.mark.parametrize("target", ["bc-t0003", "bc-t0003/renewal", "plan/growth", "summarize/cost_per_request"])
def test_nightly_target_shapes_are_accepted(target):
    assert owner.clean_decision(DECISION | {"target": target})["target"] == target


def test_rationale_control_characters_are_stripped():
    assert owner.clean_decision(DECISION | {"rationale": " ok\x07 "})["rationale"] == "ok"


def test_owner_config_is_public_but_only_when_set(monkeypatch):
    get = {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/owner-config"}
    r = api.handler(get, None)
    assert r["statusCode"] == 200 and json.loads(r["body"]) == {"pool_id": POOL, "client_id": CLIENT, "region": REGION}
    monkeypatch.setenv("OWNER_CLIENT_ID", "")
    assert api.handler(get, None)["statusCode"] == 404
