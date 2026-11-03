"""M0-07 foundation stack: synth-time assertions (no AWS account needed; runs locally and in CI)."""

from __future__ import annotations

import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template

from margin_compass_infra.config import FoundationConfig
from margin_compass_infra.foundation_stack import FOCUS_1_2_AWS_COLUMNS, FoundationStack
from margin_compass_infra.guardrails import ForbiddenResourceGuard
from margin_compass_infra.tagging import REQUIRED_TAG_KEYS, apply_tags

ACCOUNT = "123456789012"


def synth(**overrides) -> tuple[FoundationStack, Template]:
    app = cdk.App()
    cfg = FoundationConfig(alert_email="owner@example.com", github_repo="acme/margin-compass", owner="acme", **overrides)
    stack = FoundationStack(app, "Foundation", config=cfg, env=cdk.Environment(account=ACCOUNT, region="us-east-1"))
    apply_tags(stack, project="margin-compass", env="shared", stage="foundation", owner="acme", cost_center="margin-compass")
    cdk.Aspects.of(app).add(ForbiddenResourceGuard())
    return stack, Template.from_stack(stack)


@pytest.fixture(scope="module")
def default():
    return synth()


def test_monthly_budget_alerts_at_3_and_5_usd(default):
    _, t = default
    t.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": {"BudgetType": "COST", "TimeUnit": "MONTHLY", "BudgetLimit": {"Amount": 5, "Unit": "USD"}},
            "NotificationsWithSubscribers": [
                {"Notification": {"NotificationType": "ACTUAL", "Threshold": 3, "ThresholdType": "ABSOLUTE_VALUE"}},
                {"Notification": {"NotificationType": "FORECASTED", "Threshold": 5, "ThresholdType": "ABSOLUTE_VALUE"}},
                {"Notification": {"NotificationType": "ACTUAL", "Threshold": 5, "ThresholdType": "ABSOLUTE_VALUE"}},
            ],
        },
    )


def test_kill_switch_policy_denies_model_spend_and_pipeline_runs(default):
    _, t = default
    t.has_resource_properties(
        "AWS::IAM::ManagedPolicy",
        {
            "ManagedPolicyName": "mc-shared-foundation-kill-switch-deny",
            "PolicyDocument": {
                "Statement": [{"Effect": "Deny", "Action": ["bedrock:*", "states:StartExecution"], "Resource": "*"}]
            },
        },
    )


def test_kill_switch_action_waits_for_workload_roles(default):
    _, t = default
    t.resource_count_is("AWS::Budgets::BudgetsAction", 0)


def test_kill_switch_action_targets_configured_roles():
    _, t = synth(kill_switch_role_names=["mc-prod-agents-api"])
    t.has_resource_properties(
        "AWS::Budgets::BudgetsAction",
        {
            "ActionType": "APPLY_IAM_POLICY",
            "ApprovalModel": "AUTOMATIC",
            "NotificationType": "ACTUAL",
            "ActionThreshold": {"Type": "ABSOLUTE_VALUE", "Value": 5},
            "Definition": {"IamActionDefinition": {"Roles": ["mc-prod-agents-api"]}},
        },
    )


def test_budgets_execution_role_can_only_attach_the_kill_switch_policy(default):
    _, t = default
    t.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
                            "Condition": {"ArnEquals": {"iam:PolicyARN": Match.any_value()}},
                        }
                    )
                ]
            }
        },
    )


def test_alert_topic_allows_budgets_anomaly_detection_and_alarms_only_from_this_account(default):
    _, t = default
    t.has_resource_properties(
        "AWS::SNS::TopicPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Principal": {"Service": ["budgets.amazonaws.com", "costalerts.amazonaws.com", "cloudwatch.amazonaws.com"]},
                                "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}},
                            }
                        )
                    ]
                )
            }
        },
    )
    t.has_resource_properties("AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "owner@example.com"})


def test_anomaly_alerts_are_immediate_via_sns_with_1_usd_threshold(default):
    _, t = default
    t.resource_count_is("AWS::CE::AnomalyMonitor", 1)
    subscription = next(iter(t.find_resources("AWS::CE::AnomalySubscription").values()))["Properties"]
    assert subscription["Frequency"] == "IMMEDIATE"
    expr = json.loads(subscription["ThresholdExpression"])
    assert expr["Dimensions"] == {
        "Key": "ANOMALY_TOTAL_IMPACT_ABSOLUTE",
        "MatchOptions": ["GREATER_THAN_OR_EQUAL"],
        "Values": ["1"],
    }


def test_existing_anomaly_monitor_is_reused_not_duplicated():
    arn = f"arn:aws:ce::{ACCOUNT}:anomalymonitor/existing"
    _, t = synth(existing_anomaly_monitor_arn=arn)
    t.resource_count_is("AWS::CE::AnomalyMonitor", 0)
    t.has_resource_properties("AWS::CE::AnomalySubscription", {"MonitorArnList": [arn]})


def test_focus_1_2_export_is_daily_parquet_with_every_column(default):
    _, t = default
    export = next(iter(t.find_resources("AWS::BCMDataExports::Export").values()))["Properties"]["Export"]
    query = export["DataQuery"]["QueryStatement"]
    assert query.endswith("FROM FOCUS_1_2_AWS")
    assert all(column in query for column in FOCUS_1_2_AWS_COLUMNS)
    assert len(FOCUS_1_2_AWS_COLUMNS) == len(set(FOCUS_1_2_AWS_COLUMNS)) == 60
    assert export["DataQuery"]["TableConfigurations"] == {"FOCUS_1_2_AWS": {"TIME_GRANULARITY": "DAILY"}}
    out = export["DestinationConfigurations"]["S3Destination"]["S3OutputConfigurations"]
    assert out == {"Format": "PARQUET", "Compression": "PARQUET", "OutputType": "CUSTOM", "Overwrite": "OVERWRITE_REPORT"}
    assert export["RefreshCadence"] == {"Frequency": "SYNCHRONOUS"}


def test_billing_bucket_is_private_and_only_data_exports_may_write(default):
    _, t = default
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
        },
    )
    t.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Principal": {"Service": "bcm-data-exports.amazonaws.com"},
                                "Action": "s3:PutObject",
                                "Condition": {
                                    "ArnLike": {
                                        "aws:SourceArn": f"arn:aws:bcm-data-exports:us-east-1:{ACCOUNT}:export/*"
                                    },
                                    "StringEquals": {"aws:SourceAccount": ACCOUNT},
                                },
                            }
                        )
                    ]
                )
            }
        },
    )


def test_github_deploy_role_trusts_only_main_branch_of_the_repo(default):
    _, t = default
    t.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "mc-shared-foundation-github-deploy",
            "MaxSessionDuration": 3600,
            "AssumeRolePolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Action": "sts:AssumeRoleWithWebIdentity",
                            "Condition": {
                                "StringEquals": {
                                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                    "token.actions.githubusercontent.com:sub": "repo:acme/margin-compass:ref:refs/heads/main",
                                }
                            },
                        }
                    )
                ]
            },
        },
    )


def test_github_deploy_role_may_only_assume_cdk_bootstrap_roles_and_upload_the_dashboard(default):
    stack, t = default
    role_id = stack.get_logical_id(stack.deploy_role.node.default_child)
    policies = t.find_resources("AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}})
    statements = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    assert statements == [
        {
            "Sid": "AssumeCdkBootstrapRolesOnly",
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Resource": f"arn:aws:iam::{ACCOUNT}:role/cdk-hnb659fds-*-{ACCOUNT}-us-east-1",
        },
        {
            "Sid": "ReadMarginCompassStackOutputs",
            "Action": "cloudformation:DescribeStacks",
            "Effect": "Allow",
            "Resource": f"arn:aws:cloudformation:us-east-1:{ACCOUNT}:stack/mc-*/*",
        },
        {
            "Sid": "ListDashboardPrefix",
            "Action": "s3:ListBucket",
            "Condition": {"StringLike": {"s3:prefix": ["site/*", "site/"]}},
            "Effect": "Allow",
            "Resource": f"arn:aws:s3:::mc-*-data-lake-{ACCOUNT}",
        },
        {
            "Sid": "WriteDashboardPrefix",
            "Action": ["s3:PutObject", "s3:DeleteObject"],
            "Effect": "Allow",
            "Resource": f"arn:aws:s3:::mc-*-data-lake-{ACCOUNT}/site/*",
        },
        {
            "Sid": "InvalidateDashboard",
            "Action": "cloudfront:CreateInvalidation",
            "Effect": "Allow",
            "Resource": f"arn:aws:cloudfront::{ACCOUNT}:distribution/*",
        },
    ]


def test_deploy_role_can_trust_the_immutable_github_subject():
    _, t = synth(github_oidc_subject_prefix="repo:acme@1/margin-compass@2")
    roles = t.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": "mc-shared-foundation-github-deploy"}})
    cond = next(iter(roles.values()))["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
    assert cond["token.actions.githubusercontent.com:sub"] == "repo:acme@1/margin-compass@2:ref:refs/heads/main"


@pytest.mark.parametrize("prefix", ["repo:acme/margin-compass", "repo:other@1/margin-compass@2", "repo:acme@x/margin-compass@2"])
def test_immutable_subject_must_match_the_repo(prefix):
    with pytest.raises(ValueError, match="githubOidcSubjectPrefix"):
        FoundationConfig(alert_email="o@example.com", github_repo="acme/margin-compass", github_oidc_subject_prefix=prefix)


def test_cdk_json_uses_the_immutable_subject_for_this_repo():
    import json as _json
    from pathlib import Path as _Path

    ctx = _json.loads((_Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]
    owner, repo = ctx["mc:githubRepo"].split("/")
    assert ctx["mc:githubOidcSubjectPrefix"].startswith(f"repo:{owner}@") and f"/{repo}@" in ctx["mc:githubOidcSubjectPrefix"]


def test_no_access_keys_or_users_are_created(default):
    _, t = default
    t.resource_count_is("AWS::IAM::User", 0)
    t.resource_count_is("AWS::IAM::AccessKey", 0)


def test_every_taggable_resource_has_the_mandatory_tags(default):
    _, t = default
    tagged = 0
    for resource in t.to_json()["Resources"].values():
        tags = resource.get("Properties", {}).get("Tags")
        if isinstance(tags, list):
            keys = {tag["Key"] for tag in tags}
            assert set(REQUIRED_TAG_KEYS) <= keys, resource["Type"]
            tagged += 1
    assert tagged >= 4  # bucket, topic, roles, OIDC provider, export


def test_foundation_has_no_forbidden_resources(default):
    stack, _ = default
    Annotations.from_stack(stack).has_no_error("*", Match.any_value())


def test_config_rejects_missing_alert_email():
    with pytest.raises(ValueError, match="mc:alertEmail"):
        FoundationConfig(alert_email="", github_repo="acme/margin-compass")
