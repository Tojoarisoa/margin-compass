"""Data stack (M1-02): the S3 lake and the pipeline Lambda for one environment (dev in M1).
M1-05 adds the knowledge vector index (S3 Vectors, ADR-008) and the Titan v2 embedding grant (ADR-003).

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
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

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
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
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
            memory_size=2048,
            ephemeral_storage_size=cdk.Size.mebibytes(1024),
            timeout=cdk.Duration.minutes(10),
            role=role,
            log_group=log_group,
            environment={
                "LAKE_BUCKET": self.lake.bucket_name,
                "MC_ENV": env_name,
                "REGISTRY_TABLE": core_table.table_name,
                "VECTOR_BUCKET": vector_bucket.vector_bucket_name,
                "VECTOR_INDEX": KNOWLEDGE_INDEX_NAME,
            },
        )

        cdk.CfnOutput(self, "LakeBucket", value=self.lake.bucket_name)
        cdk.CfnOutput(self, "PipelineFunction", value=self.pipeline.function_name)
        cdk.CfnOutput(self, "KnowledgeIndexArn", value=index.attr_index_arn)
