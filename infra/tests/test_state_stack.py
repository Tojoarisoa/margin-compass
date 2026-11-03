"""M1-04 state stack: the DynamoDB core table stays provisioned inside the free capacity (ADR-011)."""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk.assertions import Annotations, Match, Template

from margin_compass_infra.guardrails import ForbiddenResourceGuard
from margin_compass_infra.state_stack import CORE_READ_CAPACITY, CORE_WRITE_CAPACITY, StateStack
from margin_compass_infra.tagging import REQUIRED_TAG_KEYS, apply_tags

FREE_CAPACITY_UNITS = 25  # per Region per payer account, shared by all tables and GSIs (VER-02)


def synth():
    app = cdk.App()
    stack = StateStack(app, "State", env_name="dev", env=cdk.Environment(account="123456789012", region="us-east-1"))
    apply_tags(stack, project="margin-compass", env="dev", stage="state", owner="acme", cost_center="margin-compass")
    cdk.Aspects.of(app).add(ForbiddenResourceGuard())
    return stack, Template.from_stack(stack)


def test_core_table_is_provisioned_single_table_with_ttl():
    _, t = synth()
    t.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "TableName": "mc-dev-state-core",
            "BillingMode": Match.absent(),  # absent = PROVISIONED; PAY_PER_REQUEST is forbidden
            "ProvisionedThroughput": {"ReadCapacityUnits": CORE_READ_CAPACITY, "WriteCapacityUnits": CORE_WRITE_CAPACITY},
            "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
        },
    )
    t.resource_count_is("AWS::ApplicationAutoScaling::ScalableTarget", 0)  # autoscaling off


def test_dev_leaves_most_of_the_free_capacity_for_prod_and_agents():
    # dev core uses 2/25; prod core and the checkpoints tables must fit in the rest (ADR-011).
    dev_share = FREE_CAPACITY_UNITS // 4  # at most a quarter of the free capacity for dev's core table
    assert CORE_READ_CAPACITY <= dev_share and CORE_WRITE_CAPACITY <= dev_share


def test_tags_and_guardrails():
    stack, t = synth()
    for resource in t.to_json()["Resources"].values():
        tags = resource.get("Properties", {}).get("Tags")
        if isinstance(tags, list):
            assert set(REQUIRED_TAG_KEYS) <= {tag["Key"] for tag in tags}, resource["Type"]
    Annotations.from_stack(stack).has_no_error("*", Match.any_value())
