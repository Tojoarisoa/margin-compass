"""Data stack (M1-02): the S3 lake and the pipeline Lambda for one environment (dev in M1).
M1-05 adds the knowledge vector index (S3 Vectors, ADR-008) and the Titan v2 embedding grant (ADR-003).

The Lambda runs the same code as local (`simulator/` + `pipelines/`) from a container image, writes
to /tmp, and uploads to the lake. No schedule yet: the nightly workflow is M1-08.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_scheduler_targets as scheduler_targets
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from .alarms import alert_topic, lambda_errors_alarm

REPO_ROOT = Path(__file__).resolve().parents[2]

# PLAN.md §7.1 retention, for the prefixes that exist in M1.
LAKE_RETENTION_DAYS = {"landing/": 30, "quarantine/": 30, "bronze/": 90, "silver/": 395, "gold/": 760,
                       "publish/history/": 30}  # publish/latest is overwritten each run (§7.1: latest + 30 days)
WEB_READABLE_PREFIXES = ("site/*", "publish/*")  # served by CloudFront (web stack, M1-07)

# Knowledge index (M1-05). Must match rag/mc_rag (embed.DIMENSIONS, store.NON_FILTERABLE_KEYS).
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 512
KNOWLEDGE_INDEX_NAME = "kb-titan-v2-512"  # a new embedding model or dimension means a new index
NON_FILTERABLE_METADATA_KEYS = ["text", "heading"]

# Nightly orchestration (M1-08, PLAN.md §6): EventBridge Scheduler -> Step Functions Standard -> pipeline.
NIGHTLY_CRON = "cron(0 5 * * ? *)"  # 05:00 UTC; gold is due by 07:00 UTC (§14)
TELEMETRY_CRON = "cron(30 0 * * ? *)"  # 00:30 UTC: exports the previous UTC day of the API's gen_ai_call logs (S7)
API_LOG_GROUP = "/aws/lambda/mc-{env}-web-api"  # web stack's API log group, by name (no cross-stack reference)


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, core_table: dynamodb.ITable,
                 nightly_enabled: bool = False, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = lambda resource: f"mc-{env_name}-data-{resource}"  # noqa: E731 - AGENTS.md naming

        self.lake = s3.Bucket(
            self,
            "Lake",
            bucket_name=f"{name('lake')}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(id=f"expire-{prefix.rstrip('/')}", prefix=prefix, expiration=cdk.Duration.days(days))
                for prefix, days in LAKE_RETENTION_DAYS.items()
            ],
        )

        # CloudFront (OAC) may read only the dashboard and its snapshots. Scoped to this account's
        # distributions so the web stack can import the bucket without a cross-stack cycle.
        self.lake.add_to_resource_policy(
            iam.PolicyStatement(
                sid="CloudFrontReadsSiteAndPublish",
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                actions=["s3:GetObject"],
                resources=[self.lake.arn_for_objects(p) for p in WEB_READABLE_PREFIXES],
                conditions={"StringEquals": {"aws:SourceAccount": self.account},
                            "ArnLike": {"aws:SourceArn": f"arn:{cdk.Aws.PARTITION}:cloudfront::{self.account}:distribution/*"}},
            )
        )

        role = iam.Role(
            self,
            "PipelineRole",
            role_name=name("pipeline"),  # targeted by the foundation kill switch from M1-08
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Data pipeline Lambda: lake read/write, model registry, knowledge index, Titan v2 embeddings, own logs.",
        )
        self.lake.grant_read_write(role)  # includes s3:DeleteObject* (needed for idempotent re-ingest)

        # Model registry items in the core table (M1-04): item-level access to this table only.
        # Scan (M5-03): the backfill's opt-in approvals export reads the owner's APPROVAL# items; no index needed.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan"],
                resources=[core_table.table_arn],
            )
        )

        # Knowledge vectors (M1-05): derived from knowledge/ and rebuilt by the pipeline, so DESTROY is safe.
        vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "KnowledgeVectors",
            vector_bucket_name=f"mc-{env_name}-knowledge-{self.account}",
            encryption_configuration=s3vectors.CfnVectorBucket.EncryptionConfigurationProperty(sse_type="AES256"),
        )
        vector_bucket.apply_removal_policy(cdk.RemovalPolicy.DESTROY)
        index = s3vectors.CfnIndex(
            self,
            "KnowledgeIndex",
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            index_name=KNOWLEDGE_INDEX_NAME,
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=NON_FILTERABLE_METADATA_KEYS,
            ),
        )
        index.apply_removal_policy(cdk.RemovalPolicy.DESTROY)
        self.vector_bucket_name = vector_bucket.vector_bucket_name
        role.add_to_policy(
            iam.PolicyStatement(
                # GetVectors is also required by QueryVectors with a filter or returnMetadata.
                actions=["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:QueryVectors",
                         "s3vectors:ListVectors", "s3vectors:DeleteVectors"],
                resources=[index.attr_index_arn],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],  # embeddings only; denied by the kill switch when it fires
                resources=[f"arn:{cdk.Aws.PARTITION}:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL_ID}"],
            )
        )

        log_group = logs.LogGroup(
            self,
            "PipelineLogs",
            log_group_name=f"/aws/lambda/{name('pipeline')}",
            retention=logs.RetentionDays.ONE_WEEK,  # PLAN.md §14: 7-day retention
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        log_group.grant_write(role)

        self.pipeline = lambda_.DockerImageFunction(
            self,
            "Pipeline",
            function_name=name("pipeline"),
            description="M1 pipeline: simulator -> ingest -> dbt build -> forecast -> embed (synthetic data).",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=str(REPO_ROOT),
                file="pipelines/Dockerfile",
                platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            architecture=lambda_.Architecture.X86_64,
            memory_size=3008,  # account Lambda memory quota is 3,008 MB (owner, 2026-11-07); m2-plan D5 asked for 4 GB
            ephemeral_storage_size=cdk.Size.mebibytes(4096),
            timeout=cdk.Duration.minutes(15),
            role=role,
            log_group=log_group,
            environment={
                "LAKE_BUCKET": self.lake.bucket_name,
                "MC_ENV": env_name,
                "REGISTRY_TABLE": core_table.table_name,
                "VECTOR_BUCKET": vector_bucket.vector_bucket_name,
                "VECTOR_INDEX": KNOWLEDGE_INDEX_NAME,
                "MC_API_LOG_GROUP": API_LOG_GROUP.format(env=env_name),
                "MC_PIPELINE_LOG_GROUP": log_group.log_group_name,  # M6-01: own run logs -> telemetry/pipeline_runs.parquet
                "MC_BILLING_BUCKET": f"mc-shared-foundation-billing-{self.account}",  # foundation stack's FOCUS export (read-only)
            },
        )
        # S7 FOCUS export (PG-8 Platform FinOps): read-only on the billing bucket, nothing else.
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"], resources=[f"arn:{cdk.Aws.PARTITION}:s3:::mc-shared-foundation-billing-{self.account}"]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject"], resources=[f"arn:{cdk.Aws.PARTITION}:s3:::mc-shared-foundation-billing-{self.account}/focus-1-2/*"]))
        # S7 dogfood + M6-01 telemetry lake: read the API's and the pipeline's own log groups (filter only; no write).
        role.add_to_policy(iam.PolicyStatement(
            actions=["logs:FilterLogEvents"],
            resources=[f"arn:{cdk.Aws.PARTITION}:logs:{self.region}:{self.account}:log-group:{API_LOG_GROUP.format(env=env_name)}:*",
                       log_group.log_group_arn],  # GetAtt Arn already ends in :*
        ))

        self._nightly(name, nightly_enabled)
        self._backfill(name)

        cdk.CfnOutput(self, "LakeBucket", value=self.lake.bucket_name)
        cdk.CfnOutput(self, "PipelineFunction", value=self.pipeline.function_name)
        cdk.CfnOutput(self, "KnowledgeIndexArn", value=index.attr_index_arn)

    # --- M2 chunked backfill (M2-01) -------------------------------------------------------------
    def _backfill(self, name) -> None:
        """Standard state machine: static tables, then a Map over the 19 months (2 at a time), then one dbt build.

        Started by hand (`start-execution`, no schedule). About 50 transitions per run (free allowance: 4,000 per month).
        Any step whose payload status is not `success` fails the execution.
        """
        def invoke(id_: str, payload: dict, minutes: int) -> tasks.LambdaInvoke:
            return tasks.LambdaInvoke(
                self, id_, lambda_function=self.pipeline, payload_response_only=True,
                payload=sfn.TaskInput.from_object({"profile": "m2", **payload}),
                task_timeout=sfn.Timeout.duration(cdk.Duration.minutes(minutes)), retry_on_service_exceptions=True,
            )

        def step(id_: str, task: tasks.LambdaInvoke, then: sfn.IChainable) -> sfn.IChainable:
            """task -> success? -> `then`; any other status fails the execution."""
            bad = sfn.Fail(self, f"{id_}Failed", error=f"{id_}Failed", cause_path=sfn.JsonPath.string_at("$.status"))
            ok = (sfn.Choice(self, f"{id_}Ok?").when(sfn.Condition.string_equals("$.status", "success"), then).otherwise(bad))
            return task.next(ok)

        run = {"run_id": sfn.JsonPath.string_at("$$.Execution.Name")}
        month = step("Month", invoke("BackfillMonth", {"step": "month", "month": sfn.JsonPath.string_at("$"), **run}, 14),
                     sfn.Succeed(self, "MonthDone"))
        months = sfn.Map(self, "BackfillMonths", max_concurrency=2, items_path="$.months", result_path=sfn.JsonPath.DISCARD)
        months.item_processor(month)
        build = step("Build", invoke("BackfillBuild", {"step": "build", **run}, 14), sfn.Succeed(self, "BackfillDone"))
        months.next(build)
        plan = sfn.Pass(self, "BackfillPlan", parameters={"months": sfn.JsonPath.array_range(0, 18, 1)})
        plan.next(months)
        static = step("Static", invoke("BackfillStatic", {"step": "static", **run}, 14), plan)
        role = iam.Role(self, "BackfillRole", role_name=name("backfill"), assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
                        description="M2 backfill state machine: invoke the pipeline Lambda.")
        self.backfill = sfn.StateMachine(
            self, "Backfill", state_machine_name=name("backfill"), state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(static), role=role,
            timeout=cdk.Duration.hours(2), comment="M2 backfill: static -> 19 monthly chunks (2 at a time) -> dbt build",
        )
        cdk.CfnOutput(self, "BackfillStateMachine", value=self.backfill.state_machine_arn)

    # --- nightly (M1-08) ------------------------------------------------------------------------
    def _nightly(self, name, enabled: bool) -> None:
        """One Standard state machine, about 4 transitions per run (free allowance: 4,000 per month).

        Schedules in dev are off by default (PLAN.md §15); enable with `-c mc:nightlyEnabled=true`.
        The scheduler role is a kill-switch target: the budget action denies it states:StartExecution.
        """
        run = tasks.LambdaInvoke(
            self, "RunPipeline", lambda_function=self.pipeline, payload_response_only=True,
            payload=sfn.TaskInput.from_object({"run_id": sfn.JsonPath.string_at("$$.Execution.Name")}),
            task_timeout=sfn.Timeout.duration(cdk.Duration.minutes(12)),
            retry_on_service_exceptions=True,
        )
        failed = sfn.Fail(self, "PipelineFailed", error="PipelineFailed", cause_path=sfn.JsonPath.string_at("$.status"))
        check = (sfn.Choice(self, "Succeeded?")
                 .when(sfn.Condition.string_equals("$.status", "success"), sfn.Succeed(self, "Done"))
                 .otherwise(failed))
        machine_role = iam.Role(self, "NightlyRole", role_name=name("nightly"),
                                assumed_by=iam.ServicePrincipal("states.amazonaws.com"),
                                description="Nightly state machine: invoke the pipeline Lambda.")
        self.nightly = sfn.StateMachine(
            self, "Nightly", state_machine_name=name("nightly"), state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(run.next(check)), role=machine_role,
            timeout=cdk.Duration.minutes(20), comment="M1 nightly: simulate -> ingest -> dbt -> train -> embed -> publish",
        )

        scheduler_role = iam.Role(self, "NightlySchedulerRole", role_name=name("nightly-scheduler"),
                                  assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com", conditions={
                                      "StringEquals": {"aws:SourceAccount": self.account}}),
                                  description="EventBridge Scheduler: start the nightly state machine (kill-switch target).")
        scheduler.Schedule(
            self, "NightlySchedule", schedule_name=name("nightly"),
            schedule=scheduler.ScheduleExpression.expression(NIGHTLY_CRON),
            target=scheduler_targets.StepFunctionsStartExecution(self.nightly, role=scheduler_role, retry_attempts=0),
            enabled=enabled, description="Nightly pipeline run (dev schedules are off by default, PLAN.md §15).",
        )
        # S7: daily export of the API's gen_ai_call logs; reuses this (kill-switch target) role to invoke the Lambda.
        scheduler.Schedule(
            self, "TelemetrySchedule", schedule_name=name("telemetry"),
            schedule=scheduler.ScheduleExpression.expression(TELEMETRY_CRON),
            target=scheduler_targets.LambdaInvoke(
                self.pipeline, role=scheduler_role, retry_attempts=0,
                input=scheduler.ScheduleTargetInput.from_object({"profile": "telemetry"})),
            enabled=enabled, description="Daily export of API gen_ai_call and pipeline run logs (dev schedules are off by default).",
        )

        # One alarm (of the ≤ 10 in §14): any failed, timed-out, or aborted run e-mails the alert topic.
        bad = cloudwatch.MathExpression(
            expression="FILL(f, 0) + FILL(t, 0) + FILL(a, 0)", period=cdk.Duration.hours(1), label="bad runs",
            using_metrics={"f": self.nightly.metric_failed(), "t": self.nightly.metric_timed_out(), "a": self.nightly.metric_aborted()},
        )
        alarm = cloudwatch.Alarm(
            self, "NightlyFailedAlarm", alarm_name=name("nightly-failed"), metric=bad, threshold=1, evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="The nightly pipeline run failed, timed out, or was aborted. See the Step Functions execution.",
        )
        topic = alert_topic(self)
        alarm.add_alarm_action(cw_actions.SnsAction(topic))
        # M6-01: the pipeline Lambda also runs outside the state machine (telemetry export schedule, ops runs).
        lambda_errors_alarm(self, "PipelineErrorsAlarm", self.pipeline, alarm_name=name("pipeline-errors"), threshold=1, topic=topic,
                            description="The pipeline Lambda returned an error, timed out, or crashed. See its log group (runbook: docs/runbooks/alarms.md).")
        cdk.CfnOutput(self, "NightlyStateMachine", value=self.nightly.state_machine_arn)
