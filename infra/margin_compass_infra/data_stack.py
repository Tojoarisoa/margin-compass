"""Data stack (M1-02): the S3 lake and the pipeline Lambda for one environment (dev in M1).

The Lambda runs the same code as local (`simulator/` + `pipelines/`) from a container image, writes
to /tmp, and uploads to the lake. No schedule yet: the nightly workflow is M1-08.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]

# PLAN.md §7.1 retention, for the prefixes that exist in M1.
LAKE_RETENTION_DAYS = {"landing/": 30, "quarantine/": 30, "bronze/": 90, "silver/": 395, "gold/": 760}


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, core_table: dynamodb.ITable, **kwargs) -> None:
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

        role = iam.Role(
            self,
            "PipelineRole",
            role_name=name("pipeline"),  # targeted by the foundation kill switch from M1-08
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Data pipeline Lambda: read/write the lake, write its own logs.",
        )
        self.lake.grant_read_write(role)  # includes s3:DeleteObject* (needed for idempotent re-ingest)

        # Model registry items in the core table (M1-04): item-level access to this table only.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
                resources=[core_table.table_arn],
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
            description="M1 pipeline: simulator -> ingest -> dbt build -> S3 lake (synthetic data).",
            code=lambda_.DockerImageCode.from_image_asset(
                directory=str(REPO_ROOT),
                file="pipelines/Dockerfile",
                platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            architecture=lambda_.Architecture.X86_64,
            memory_size=2048,
            ephemeral_storage_size=cdk.Size.mebibytes(1024),
            timeout=cdk.Duration.minutes(10),
            role=role,
            log_group=log_group,
            environment={"LAKE_BUCKET": self.lake.bucket_name, "MC_ENV": env_name, "REGISTRY_TABLE": core_table.table_name},
        )

        cdk.CfnOutput(self, "LakeBucket", value=self.lake.bucket_name)
        cdk.CfnOutput(self, "PipelineFunction", value=self.pipeline.function_name)
