"""M1-02 data stack: lake bucket, pipeline Lambda, least-privilege role (synth only)."""

from __future__ import annotations

import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Annotations, Match, Template

from margin_compass_infra.data_stack import LAKE_RETENTION_DAYS, DataStack
from margin_compass_infra.guardrails import ForbiddenResourceGuard
from margin_compass_infra.state_stack import StateStack
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
            "MemorySize": 3008,
            "Timeout": 900,
            "EphemeralStorage": {"Size": 4096},
            "Environment": {"Variables": {"LAKE_BUCKET": Match.any_value(), "MC_ENV": "dev", "REGISTRY_TABLE": Match.any_value()}},
        },
    )


def test_pipeline_logs_keep_seven_days(synth):
    _, t = synth
    t.has_resource_properties("AWS::Logs::LogGroup", {"LogGroupName": "/aws/lambda/mc-dev-data-pipeline", "RetentionInDays": 7})


def test_pipeline_role_only_touches_its_own_resources(synth):
    stack, t = synth
    role_id = stack.get_logical_id(stack.pipeline.role.node.default_child)
    policies = t.find_resources("AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}})
    statements = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    actions = {a for s in statements for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])}
    # bedrock: and s3vectors: arrived in M1-05; their resources are pinned by the M1-05 tests below.
    assert all(a.startswith(("s3:", "logs:", "dynamodb:", "s3vectors:")) or a == "bedrock:InvokeModel" for a in actions), actions
    dynamo = {a for a in actions if a.startswith("dynamodb:")}
    # No deletes, updates, batch writes, or table admin. Scan (M5-03) is only for the opt-in approvals export.
    assert dynamo == {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan"}
    dynamo_resources = [s["Resource"] for s in statements
                        if any(a.startswith("dynamodb:") for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]]))]
    assert len(dynamo_resources) == 1 and not isinstance(dynamo_resources[0], list), dynamo_resources  # the core table only, no indexes
    assert "s3:*" not in actions and not any(a.startswith("s3:PutBucket") for a in actions)


def test_nightly_schedule_exists_but_is_off_by_default(synth):
    """PLAN.md §15: schedules in dev are off by default (enable with -c mc:nightlyEnabled=true)."""
    _, t = synth
    t.resource_count_is("AWS::Scheduler::Schedule", 2)  # nightly + telemetry export
    t.has_resource_properties("AWS::Scheduler::Schedule", {"State": "DISABLED", "ScheduleExpression": "cron(0 5 * * ? *)",
                                                           "Target": {"RetryPolicy": {"MaximumRetryAttempts": 0}}})
    t.resource_count_is("AWS::Events::Rule", 0)


def _machine(t, name):
    return next(m["Properties"] for m in t.find_resources("AWS::StepFunctions::StateMachine").values()
                if m["Properties"]["StateMachineName"] == name)


def test_backfill_machine_maps_19_months_two_at_a_time_then_builds(synth):
    _, t = synth
    sm = _machine(t, "mc-dev-data-backfill")
    assert sm.get("StateMachineType", "STANDARD") == "STANDARD"
    definition = json.dumps(sm["DefinitionString"])
    assert "MaxConcurrency" in definition and "States.ArrayRange" in definition and "BackfillBuild" in definition
    assert definition.index("BackfillStatic") < definition.index("States.ArrayRange") < definition.index("BackfillBuild")
    assert "StaticFailed" in definition and "MonthFailed" in definition and "BuildFailed" in definition


def test_nightly_state_machine_is_standard_and_fails_on_a_bad_status(synth):
    _, t = synth
    sm = _machine(t, "mc-dev-data-nightly")
    assert sm.get("StateMachineType", "STANDARD") == "STANDARD" and sm["StateMachineName"] == "mc-dev-data-nightly"
    definition = json.dumps(sm["DefinitionString"])
    assert "PipelineFailed" in definition and "$.status" in definition and "success" in definition


def test_scheduler_role_may_only_start_the_nightly_machine(synth):
    stack, t = synth
    roles = t.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": "mc-dev-data-nightly-scheduler"}})
    role_id = next(iter(roles))
    policies = t.find_resources("AWS::IAM::Policy", {"Properties": {"Roles": [{"Ref": role_id}]}})
    stmts = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    assert {a for s in stmts for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])} == {
        "states:StartExecution", "lambda:InvokeFunction"}  # nightly machine + pipeline Lambda (telemetry export)
    assert not any(s["Resource"] == "*" for s in stmts)


def test_telemetry_export_is_scheduled_daily_off_by_default_and_reads_only_the_api_and_pipeline_log_groups(synth):
    _, t = synth
    t.has_resource_properties("AWS::Scheduler::Schedule", {
        "State": "DISABLED", "ScheduleExpression": "cron(30 0 * * ? *)",
        "Target": {"Input": '{"profile":"telemetry"}', "RetryPolicy": {"MaximumRetryAttempts": 0}}})
    fn = next(iter(t.find_resources("AWS::Lambda::Function", {"Properties": {"FunctionName": "mc-dev-data-pipeline"}}).values()))
    assert fn["Properties"]["Environment"]["Variables"]["MC_API_LOG_GROUP"] == "/aws/lambda/mc-dev-web-api"
    stmts = [s for p in t.find_resources("AWS::IAM::Policy").values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    logs_stmt = [s for s in stmts if "logs:FilterLogEvents" in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])]
    assert len(logs_stmt) == 1 and len(logs_stmt[0]["Resource"]) == 2
    res = json.dumps(logs_stmt[0]["Resource"])
    assert "mc-dev-web-api" in res and "PipelineLogs" in res  # M6-01: the pipeline's own log group, nothing else
    assert "MC_PIPELINE_LOG_GROUP" in fn["Properties"]["Environment"]["Variables"]


def test_nightly_and_pipeline_alarms_to_the_alert_topic(synth):
    _, t = synth
    t.resource_count_is("AWS::CloudWatch::Alarm", 2)
    alarms = {a["Properties"]["AlarmName"]: a["Properties"] for a in t.find_resources("AWS::CloudWatch::Alarm").values()}
    assert set(alarms) == {"mc-dev-data-nightly-failed", "mc-dev-data-pipeline-errors"}
    for alarm in alarms.values():
        assert "mc-shared-foundation-alerts" in json.dumps(alarm["AlarmActions"]) and alarm["TreatMissingData"] == "notBreaching"
    errors = alarms["mc-dev-data-pipeline-errors"]  # M6-01: any pipeline Lambda error in an hour
    assert (errors["MetricName"], errors["Statistic"], errors["Period"], errors["Threshold"]) == ("Errors", "Sum", 3600, 1)
    assert errors["Dimensions"][0]["Name"] == "FunctionName"


def test_nightly_can_be_enabled_by_context():
    app = cdk.App()
    env = cdk.Environment(account=ACCOUNT, region="us-east-1")
    state = StateStack(app, "S2", env_name="dev", env=env)
    t = Template.from_stack(DataStack(app, "D2", env_name="dev", core_table=state.core, nightly_enabled=True, env=env))
    t.has_resource_properties("AWS::Scheduler::Schedule", {"State": "ENABLED"})


def test_tags_and_guardrails(synth):
    stack, t = synth
    for resource in t.to_json()["Resources"].values():
        tags = resource.get("Properties", {}).get("Tags")
        if isinstance(tags, list):
            assert set(REQUIRED_TAG_KEYS) <= {tag["Key"] for tag in tags}, resource["Type"]
    Annotations.from_stack(stack).has_no_error("*", Match.any_value())


# --- M1-05: knowledge vector index + embedding grant -------------------------------------------------

def test_knowledge_index_matches_the_rag_package(synth):
    import ast
    from pathlib import Path

    from margin_compass_infra.data_stack import EMBEDDING_DIMENSIONS, KNOWLEDGE_INDEX_NAME, NON_FILTERABLE_METADATA_KEYS

    rag = Path(__file__).resolve().parents[2] / "rag" / "mc_rag"  # read, not imported: infra has no numpy

    def constant(module: str, name: str):
        tree = ast.parse((rag / module).read_text())
        return next(ast.literal_eval(n.value) for n in tree.body
                    if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == name for t in n.targets))

    assert EMBEDDING_DIMENSIONS == constant("embed.py", "DIMENSIONS")
    assert tuple(NON_FILTERABLE_METADATA_KEYS) == constant("store.py", "NON_FILTERABLE_KEYS")
    _, t = synth
    t.has_resource_properties("AWS::S3Vectors::VectorBucket", {
        "VectorBucketName": f"mc-dev-knowledge-{ACCOUNT}", "EncryptionConfiguration": {"SseType": "AES256"},
    })
    t.has_resource_properties("AWS::S3Vectors::Index", {
        "IndexName": KNOWLEDGE_INDEX_NAME, "DataType": "float32", "Dimension": 512, "DistanceMetric": "cosine",
        "MetadataConfiguration": {"NonFilterableMetadataKeys": ["text", "heading"]},
    })


def test_vector_resources_are_tagged(synth):
    _, t = synth
    for cfn_type in ("AWS::S3Vectors::VectorBucket", "AWS::S3Vectors::Index"):
        for res in t.find_resources(cfn_type).values():
            keys = {tag["Key"] for tag in res["Properties"].get("Tags", [])}
            assert set(REQUIRED_TAG_KEYS) <= keys, cfn_type


def _statements(t):
    policies = t.find_resources("AWS::IAM::Policy")
    return [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]


def test_pipeline_may_invoke_only_titan_v2(synth):
    _, t = synth
    bedrock = [s for s in _statements(t) if any(str(a).startswith("bedrock:") for a in
                                               (s["Action"] if isinstance(s["Action"], list) else [s["Action"]]))]
    assert len(bedrock) == 1
    assert bedrock[0]["Action"] == "bedrock:InvokeModel"
    resource = bedrock[0]["Resource"]
    assert "amazon.titan-embed-text-v2:0" in str(resource) and "*" not in str(resource)


def test_vector_permissions_are_scoped_to_the_index(synth):
    _, t = synth
    vec = [s for s in _statements(t) if "s3vectors" in str(s["Action"])]
    assert len(vec) == 1
    assert set(vec[0]["Action"]) == {"s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:QueryVectors",
                                     "s3vectors:ListVectors", "s3vectors:DeleteVectors"}
    assert "Fn::GetAtt" in vec[0]["Resource"] and vec[0]["Resource"]["Fn::GetAtt"][1] == "IndexArn"


def test_pipeline_gets_vector_env(synth):
    _, t = synth
    fn = next(iter(t.find_resources("AWS::Lambda::Function", {"Properties": {"FunctionName": "mc-dev-data-pipeline"}}).values()))
    env = fn["Properties"]["Environment"]["Variables"]
    assert env["VECTOR_INDEX"] == "kb-titan-v2-512" and "VECTOR_BUCKET" in env


def test_cdk_json_puts_the_pipeline_behind_the_kill_switch():
    import json
    from pathlib import Path

    ctx = json.loads((Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]
    assert {"mc-dev-data-pipeline", "mc-dev-data-nightly-scheduler"} <= set(ctx["mc:killSwitchRoleNames"])
    assert ctx["mc:nightlyEnabled"] is False  # PLAN.md §15: dev schedules off by default



def test_backfill_static_step_gets_the_execution_input_for_the_approvals_flag(synth):
    """M5-03: only the static step sees the execution input (`"approvals": true` opts in); months read the lake."""
    _, t = synth
    parts = _machine(t, "mc-dev-data-backfill")["DefinitionString"]["Fn::Join"][1]
    states = json.loads("".join(p if isinstance(p, str) else "X" for p in parts))["States"]
    with_input = [n for n, st in states.items() if "input.$" in st.get("Parameters", {})]
    assert with_input == ["BackfillStatic"] and states["BackfillStatic"]["Parameters"]["input.$"] == "$"
