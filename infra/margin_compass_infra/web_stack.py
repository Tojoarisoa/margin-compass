"""Web stack (M1-07): one CloudFront distribution for the dashboard, its snapshots, and the agent API.

  /*          -> lake bucket, origin path /site (dashboard build)          S3 OAC
  /publish/*  -> lake bucket (publish/ snapshots written by the pipeline)  S3 OAC
  /api/*      -> agent API Lambda function URL (AWS_IAM)                   Lambda OAC (ADR-012, VER-08)

The lake's bucket policy (data stack) lets CloudFront distributions of this account read only site/*
and publish/*; importing the bucket here by name avoids a cross-stack cycle.
No VPC (ADR-006), no WAF (§11.2): abuse protection is OAC + rate limits + budgets in DynamoDB (§11.3).
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]

# Interim Mid model (ADR-003) through the us. cross-region inference profile.
AGENT_INFERENCE_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
AGENT_FOUNDATION_MODEL = "anthropic.claude-haiku-4-5-20251001-v1:0"
US_PROFILE_REGIONS = ("us-east-1", "us-east-2", "us-west-2")  # where a us. profile may route
API_RESERVED_CONCURRENCY = 5

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class WebStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, lake_bucket_name: str,
                 core_table: dynamodb.ITable, dashboard_domain: str | None = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = lambda resource: f"mc-{env_name}-web-{resource}"  # noqa: E731
        lake = s3.Bucket.from_bucket_name(self, "Lake", lake_bucket_name)

        # --- agent API -----------------------------------------------------------------------
        fn_name = name("api")
        role = iam.Role(self, "ApiRole", role_name=fn_name, assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                        description="Agent API: read gold, job/budget/rate items in the core table, invoke Haiku 4.5, own logs.")
        role.add_to_policy(iam.PolicyStatement(actions=["s3:GetObject"], resources=[lake.arn_for_objects("gold/*.parquet")]))
        role.add_to_policy(iam.PolicyStatement(actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                                               resources=[core_table.table_arn]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],  # Converse uses InvokeModel permissions; denied by the kill switch
            resources=[f"arn:{cdk.Aws.PARTITION}:bedrock:{self.region}:{self.account}:inference-profile/{AGENT_INFERENCE_PROFILE}"]
            + [f"arn:{cdk.Aws.PARTITION}:bedrock:{r}::foundation-model/{AGENT_FOUNDATION_MODEL}" for r in US_PROFILE_REGIONS],
        ))
        # The ask handler starts the worker by invoking itself asynchronously (ARN by name: no self-reference cycle).
        role.add_to_policy(iam.PolicyStatement(actions=["lambda:InvokeFunction"],
                                               resources=[f"arn:{cdk.Aws.PARTITION}:lambda:{self.region}:{self.account}:function:{fn_name}"]))
        log_group = logs.LogGroup(self, "ApiLogs", log_group_name=f"/aws/lambda/{fn_name}",
                                  retention=logs.RetentionDays.ONE_WEEK, removal_policy=cdk.RemovalPolicy.DESTROY)
        log_group.grant_write(role)

        self.api = lambda_.DockerImageFunction(
            self, "Api", function_name=fn_name,
            description="M1-07 agent API: Cost-to-Serve Analyst (AG-03), polling jobs (synthetic data).",
            code=lambda_.DockerImageCode.from_image_asset(directory=str(REPO_ROOT), file="agents/Dockerfile",
                                                          platform=cdk.aws_ecr_assets.Platform.LINUX_AMD64),
            architecture=lambda_.Architecture.X86_64, memory_size=1024, timeout=cdk.Duration.seconds(60),
            reserved_concurrent_executions=API_RESERVED_CONCURRENCY,
            retry_attempts=0, max_event_age=cdk.Duration.minutes(5),  # a failed job is never re-run (no double spend)
            role=role, log_group=log_group,
            environment={"LAKE_BUCKET": lake_bucket_name, "STATE_TABLE": core_table.table_name, "MC_ENV": env_name},
        )
        url = self.api.add_function_url(auth_type=lambda_.FunctionUrlAuthType.AWS_IAM,
                                        invoke_mode=lambda_.InvokeMode.BUFFERED)

        # --- CloudFront ------------------------------------------------------------------------
        headers = cf.ResponseHeadersPolicy(
            self, "SecurityHeaders", response_headers_policy_name=name("security-headers"),
            security_headers_behavior=cf.ResponseSecurityHeadersBehavior(
                content_security_policy=cf.ResponseHeadersContentSecurityPolicy(content_security_policy=CSP, override=True),
                content_type_options=cf.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cf.ResponseHeadersFrameOptions(frame_option=cf.HeadersFrameOption.DENY, override=True),
                referrer_policy=cf.ResponseHeadersReferrerPolicy(referrer_policy=cf.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN, override=True),
                strict_transport_security=cf.ResponseHeadersStrictTransportSecurity(access_control_max_age=cdk.Duration.days(365),
                                                                                     include_subdomains=True, override=True),
            ),
        )
        short_cache = cf.CachePolicy(self, "ShortCache", cache_policy_name=name("short-cache"),
                                     default_ttl=cdk.Duration.minutes(5), min_ttl=cdk.Duration.seconds(0), max_ttl=cdk.Duration.hours(1),
                                     enable_accept_encoding_gzip=True, enable_accept_encoding_brotli=True)
        api_request = cf.OriginRequestPolicy(
            self, "ApiRequest", origin_request_policy_name=name("api-request"),
            header_behavior=cf.OriginRequestHeaderBehavior.allow_list("CloudFront-Viewer-Address", "content-type"),  # OAC itself signs with x-amz-content-sha256 (not allowed here)
            query_string_behavior=cf.OriginRequestQueryStringBehavior.none(),
            cookie_behavior=cf.OriginRequestCookieBehavior.none(),
        )
        site_origin = origins.S3BucketOrigin.with_origin_access_control(lake, origin_path="/site")
        publish_origin = origins.S3BucketOrigin.with_origin_access_control(lake)
        api_origin = origins.FunctionUrlOrigin.with_origin_access_control(url)

        # Optional custom domain for the dashboard (e.g. medtech.booncore.com). The DNS zone is in Cloudflare, so the
        # certificate is DNS-validated without a Route 53 zone: add the validation CNAME there (docs/runbooks/dashboard-domain.md).
        certificate = None
        if dashboard_domain:
            certificate = acm.Certificate(self, "DashboardCertificate", domain_name=dashboard_domain,
                                          validation=acm.CertificateValidation.from_dns())
        self.distribution = cf.Distribution(
            self, "Distribution", comment=f"Margin Compass {env_name}: dashboard, snapshots, agent API",
            domain_names=[dashboard_domain] if dashboard_domain else None, certificate=certificate,
            default_root_object="index.html", price_class=cf.PriceClass.PRICE_CLASS_100,
            http_version=cf.HttpVersion.HTTP2_AND_3, minimum_protocol_version=cf.SecurityPolicyProtocol.TLS_V1_2_2021,
            default_behavior=cf.BehaviorOptions(origin=site_origin, viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                                                cache_policy=short_cache, response_headers_policy=headers, compress=True),
            additional_behaviors={
                "/publish/*": cf.BehaviorOptions(origin=publish_origin, viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                                                 cache_policy=short_cache, response_headers_policy=headers, compress=True),
                "/api/*": cf.BehaviorOptions(origin=api_origin, viewer_protocol_policy=cf.ViewerProtocolPolicy.HTTPS_ONLY,
                                             allowed_methods=cf.AllowedMethods.ALLOW_ALL, cache_policy=cf.CachePolicy.CACHING_DISABLED,
                                             origin_request_policy=api_request, response_headers_policy=headers),
            },
        )

        # The dashboard build is uploaded by infra/scripts/deploy-dashboard.sh (s3 sync to site/ + invalidation),
        # not by a CDK BucketDeployment, whose helper Lambda would need write and delete on the whole lake.

        cdk.CfnOutput(self, "Url", value=f"https://{self.distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "ApiFunction", value=self.api.function_name)
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        if dashboard_domain:
            cdk.CfnOutput(self, "DashboardUrl", value=f"https://{dashboard_domain}")
