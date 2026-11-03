import base64
import json
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws
from scripted import good_answer, load_questions

from mc_agents import api
from mc_agents.budget import BudgetExceeded
from mc_agents.evaluate import EVAL_DIR
from mc_agents.guard import Caps, RateLimiter, SpendGuard

Q = load_questions(EVAL_DIR)


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        t = ddb.create_table(TableName="core", KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
                             AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
                             ProvisionedThroughput={"ReadCapacityUnits": 2, "WriteCapacityUnits": 2})
        yield t


def _event(body, ip="203.0.113.5", b64=False):
    raw = json.dumps(body) if not isinstance(body, str) else body
    return {"requestContext": {"http": {"method": "POST", "sourceIp": "130.176.0.1"}}, "rawPath": "/api/ask",
            "headers": {"CloudFront-Viewer-Address": f"{ip}:41234"},
            "body": base64.b64encode(raw.encode()).decode() if b64 else raw, "isBase64Encoded": b64}


def test_ask_starts_a_job_and_invokes_the_worker(table):
    started = []
    r = api.handle_ask(_event({"question": "What was bc-t0003's margin?"}, b64=True), None, table=table,
                       invoke=lambda ctx, jid: started.append(jid))
    assert r["statusCode"] == 202
    job_id = json.loads(r["body"])["job_id"]
    assert started == [job_id]
    item = table.get_item(Key={"PK": f"JOB#{job_id}", "SK": "JOB"})["Item"]
    assert item["status"] == "pending" and item["ttl"] > 0


@pytest.mark.parametrize("body", ["not json", {"question": ""}, {"question": 42}, {"question": "x" * 301}, "x" * 3000, "[1]"])
def test_bad_requests_are_rejected(table, body):
    r = api.handle_ask(_event(body), None, table=table, invoke=lambda *a: pytest.fail("must not start"))
    assert r["statusCode"] == 400


def test_per_client_hourly_limit(table):
    codes = [api.handle_ask(_event({"question": "q"}), None, table=table, invoke=lambda *a: None)["statusCode"] for _ in range(6)]
    assert codes == [202] * 5 + [429]
    other = api.handle_ask(_event({"question": "q"}, ip="198.51.100.7"), None, table=table, invoke=lambda *a: None)
    assert other["statusCode"] == 202


def test_global_daily_limit(table):
    limiter = RateLimiter(table, Caps(global_per_day=3, per_client_per_hour=100, per_client_per_day=100))
    for i in range(3):
        limiter.admit(f"198.51.100.{i}")
    with pytest.raises(api.RateLimited):
        limiter.admit("198.51.100.99")


def test_client_addresses_are_never_stored(table):
    api.handle_ask(_event({"question": "q"}), None, table=table, invoke=lambda *a: None)
    assert "203.0.113.5" not in json.dumps(table.scan()["Items"], default=str)


def test_spend_guard_blocks_before_the_cap(table):
    g = SpendGuard(table, Caps(daily_usd=Decimal("0.01")))
    g.record(Decimal("0.009"))
    g.reserve(Decimal("0.0005"))
    with pytest.raises(BudgetExceeded, match="day"):
        g.reserve(Decimal("0.002"))


def test_no_new_jobs_without_budget_headroom(table):
    SpendGuard(table).record(Decimal("0.095"))  # daily cap $0.10, a question may cost up to $0.01
    r = api.handle_ask(_event({"question": "q"}), None, table=table, invoke=lambda *a: pytest.fail("must not start"))
    assert r["statusCode"] == 503 and json.loads(r["body"])["code"] == "budget"


def test_worker_answers_records_spend_and_never_runs_twice(table, gold):
    r = api.handle_ask(_event({"question": Q["q1"]["question"]}), None, table=table, invoke=lambda *a: None)
    job_id = json.loads(r["body"])["job_id"]
    assert api.run_job(job_id, table=table, gold_dir=gold, client=good_answer(Q, "q1"), sync=False) == "answered"
    assert api.run_job(job_id, table=table, gold_dir=gold, client=good_answer(Q, "q1"), sync=False) == "skipped"
    body = json.loads(api.handle_job(f"/api/jobs/{job_id}", table=table)["body"])
    assert body["status"] == "answered" and "[E1]" in body["answer"] and body["cost_line"].startswith("Cost of this answer")
    assert body["evidence"][0]["tool"] == "tenant_margin"
    spent = SpendGuard(table).spent()
    assert all(v > 0 for v in spent.values())


def test_worker_stops_when_the_shared_budget_runs_out(table, gold):
    SpendGuard(table).record(Decimal("0.0999"))
    table.put_item(Item={"PK": "JOB#" + "a" * 32, "SK": "JOB", "status": "pending", "question": Q["q1"]["question"]})
    client = good_answer(Q, "q1")
    assert api.run_job("a" * 32, table=table, gold_dir=gold, client=client, sync=False) == "budget_exceeded"
    assert client.requests == []  # no model call was made


@pytest.mark.parametrize("path", ["/api/jobs/../../etc", "/api/jobs/" + "b" * 32])
def test_unknown_jobs_are_404(table, path):
    assert api.handle_job(path, table=table)["statusCode"] == 404


def test_router(monkeypatch, table):
    monkeypatch.setattr(api, "_table", lambda: table)
    health = api.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/health"}, None)
    assert health["statusCode"] == 200 and json.loads(health["body"])["caps"]["monthly_usd"] == "1.50"
    assert api.handler({"requestContext": {"http": {"method": "DELETE"}}, "rawPath": "/api/ask"}, None)["statusCode"] == 404
