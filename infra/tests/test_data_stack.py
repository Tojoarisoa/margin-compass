"""M1-02 data stack: lake bucket, pipeline Lambda, least-privilege role (synth only)."""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template

from margin_compass_infra.data_stack import LAKE_RETENTION_DAYS, DataStack
from margin_compass_infra.state_stack import StateStack
from margin_compass_infra.guardrails import ForbiddenResourceGuard
from margin_compass_infra.tagging import REQUIRED_TAG_KEYS, apply_tags

ACCOUNT = "123456789012"


@pytest.fixture(scope="module")
def synth():
    app = cdk.App()
    env = cdk.Environment(account=ACCOUNT, region="us-east-1")
    state = StateStack(app, "State", env_name="dev", env=env)
    stack = DataStack(app, "Data", env_name="dev", core_table=state.core, env=env)
    apply_tags(stack, project="margin-compass", env="dev", stage="data", owner="acme", cost_center="margin-compass")
    cdk.Aspects.of(app).add(ForbiddenResourceGuard())
    return stack, Template.from_stack(stack)


def test_lake_is_private_encrypted_and_https_only(synth):
    _, t = synth
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "BucketName": f"mc-dev-data-lake-{ACCOUNT}",
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
            },
            "BucketEncryption": {"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        },
    )
    t.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {"PolicyDocument": {"Statement": Match.array_with([Match.object_like({"Effect": "Deny", "Condition": {"Bool": {"aws:SecureTransport": "false"}}})])}},
    )


def test_lake_retention_follows_plan_7_1(synth):
    _, t = synth
    rules = next(iter(t.find_resources("AWS::S3::Bucket").values()))["Properties"]["LifecycleConfiguration"]["Rules"]
    assert {r["Prefix"]: r["ExpirationInDays"] for r in rules} == LAKE_RETENTION_DAYS


def test_pipeline_lambda_is_container_with_bounded_resources(synth):
    _, t = synth
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "mc-dev-data-pipeline",
            "PackageType": "Image",
            "Architectures": ["x86_64"],
            "MemorySize": 2048,
            "Timeout": 600,
            "EphemeralStorage": {"Size": 1024},
            "Environment": {"Variables": {"LAKE_BUCKET": Match.any_value(), "MC_ENV": "dev", "REGISTRY_TABLE": Match.any_value()}},
        },
    )


def test_pipeline_logs_keep_seven_days(synth):
    _, t = synth
    t.has_resource_properties("AWS::Logs::LogGroup", {"LogGroupName": "/aws/lambda/mc-dev-data-pipeline", "RetentionInDays": 7})


def test_pipeline_role_only_touches_the_lake_and_its_logs(synth):
    stack, t = synth
    role_id = stack.get_logical_id(stack.pipeline.role.node.default_child)
    policies = t.find_resources("AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}})
    statements = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    actions = {a for s in statements for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])}
    assert all(a.startswith(("s3:", "logs:", "dynamodb:")) for a in actions), actions
    dynamo = {a for a in actions if a.startswith("dynamodb:")}
    assert dynamo == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"}  # no scans, deletes, or table admin
    assert "s3:*" not in actions and not any(a.startswith("s3:PutBucket") for a in actions)


def test_no_schedule_yet(synth):
    _, t = synth
    t.resource_count_is("AWS::Scheduler::Schedule", 0)
    t.resource_count_is("AWS::Events::Rule", 0)


def test_tags_and_guardrails(synth):
    stack, t = synth
    for resource in t.to_json()["Resources"].values():
        tags = resource.get("Properties", {}).get("Tags")
        if isinstance(tags, list):
            assert set(REQUIRED_TAG_KEYS) <= {tag["Key"] for tag in tags}, resource["Type"]
    Annotations.from_stack(stack).has_no_error("*", Match.any_value())
