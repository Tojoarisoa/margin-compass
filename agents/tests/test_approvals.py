import pytest

from mc_agents.approvals import MemoryStore, NotAuthorized, decide, request

ACTS = [{"type": "discount", "discount_bps": 1200}]


def test_flow_and_higher_role_may_approve():
    st = MemoryStore()
    assert request(st, "a1", "q", ACTS, "revops_lead").status == "pending"
    done = decide(st, "a1", "head_of_revenue", True)
    assert done.status == "approved" and done.decided_by == "head_of_revenue"


def test_lower_or_unknown_role_rejected():
    st = MemoryStore()
    request(st, "a1", "q", ACTS, "revops_lead")
    for role in ("account_manager", "visitor"):
        with pytest.raises(NotAuthorized):
            decide(st, "a1", role, True)
    assert st.get("a1")["status"] == "pending"


def test_double_decision_and_bad_requests():
    st = MemoryStore()
    request(st, "a1", "q", ACTS, "revops_lead")
    assert decide(st, "a1", "revops_lead", False).status == "rejected"
    with pytest.raises(ValueError):
        decide(st, "a1", "revops_lead", True)
    with pytest.raises(ValueError):
        request(st, "a1", "q", ACTS, "revops_lead")
    with pytest.raises(ValueError):
        request(st, "a2", "q", [], "revops_lead")
    with pytest.raises(ValueError):
        request(st, "a2", "q", ACTS, "ceo")
    with pytest.raises(KeyError):
        decide(st, "zz", "revops_lead", True)


def test_dynamo_store_round_trip_and_flow(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    import boto3
    from moto import mock_aws

    from mc_agents.approvals import DynamoStore, NotAuthorized, decide, request

    with mock_aws():
        t = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="core", KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 2, "WriteCapacityUnits": 2})
        s = DynamoStore(t, ttl_seconds=100, now=lambda: 1000)
        assert s.get("a1") is None
        request(s, "a1", "q", [{"type": "discount", "discount_bps": 1000}], "revops_lead")
        assert t.get_item(Key={"PK": "a1", "SK": "item"})["Item"]["ttl"] == 1100
        try:
            decide(s, "a1", "account_manager", True)
            raise AssertionError("expected NotAuthorized")
        except NotAuthorized:
            pass
        assert decide(s, "a1", "revops_lead", True).status == "approved"
        assert s.get("a1")["status"] == "approved"
