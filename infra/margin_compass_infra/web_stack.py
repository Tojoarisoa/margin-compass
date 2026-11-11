"""Web stack (M1-07): one CloudFront distribution for the dashboard, its snapshots, and the agent API.

  /*          -> lake bucket, origin path /site (dashboard build)          S3 OAC
  /publish/*  -> lake bucket (publish/ snapshots written by the pipeline)  S3 OAC
  /api/*      -> agent API Lambda function URL (AWS_IAM)                   Lambda OAC (ADR-012, VER-08)

Owner sign-in (M5-03 step 5): a Cognito user pool (Lite plan, free up to 10,000 MAU; VER-02) with one public
app client, self sign-up off. No user is created here: the owner adds their user in the console (AGENTS.md §8.3).

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
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from .alarms import alert_topic, lambda_errors_alarm

REPO_ROOT = Path(__file__).resolve().parents[2]
KILL_SWITCH_CODE = REPO_ROOT / "infra" / "functions" / "kill_switch"
KILL_SWITCH_POLICY_NAME = "mc-shared-foundation-kill-switch-deny"  # foundation stack (account-wide)

# Interim Mid model (ADR-003) through the us. cross-region inference profile.
AGENT_INFERENCE_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
AGENT_FOUNDATION_MODEL = "anthropic.claude-haiku-4-5-20251001-v1:0"
US_PROFILE_REGIONS = ("us-east-1", "us-east-2", "us-west-2")  # where a us. profile may route
API_RESERVED_CONCURRENCY = 5

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self' https://cognito-idp.us-east-1.amazonaws.com; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


class WebStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, lake_bucket_name: str,
                 core_table: dynamodb.ITable, dashboard_domain: str | None = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = lambda resource: f"mc-{env_name}-web-{resource}"  # noqa: E731
        lake = s3.Bucket.from_bucket_name(self, "Lake", lake_bucket_name)

        # --- owner sign-in (M5-03 step 5) ------------------------------------------------------
        self.user_pool = cognito.UserPool(
            self, "OwnerPool", user_pool_name=name("owners"), feature_plan=cognito.FeaturePlan.LITE,
            self_sign_up_enabled=False, sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            password_policy=cognito.PasswordPolicy(min_length=14, require_lowercase=True, require_uppercase=True,
                                                   require_digits=True, require_symbols=True,
                                                   temp_password_validity=cdk.Duration.days(3)),
            mfa=cognito.Mfa.OPTIONAL, mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            account_recovery=cognito.AccountRecovery.NONE,  # the owner resets through the console; no e-mail/SMS sending
            deletion_protection=True, removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        self.owner_group = cognito.CfnUserPoolGroup(self, "OwnerGroup", user_pool_id=self.user_pool.user_pool_id,
                                                    group_name="owner", description="May record approvals (M5-03)")
        self.user_pool_client = self.user_pool.add_client(
            "DashboardClient", user_pool_client_name=name("dashboard"), generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True), disable_o_auth=True,  # SRP only: no OAuth flows, scopes or hosted UI
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            prevent_user_existence_errors=True, enable_token_revocation=True,
            access_token_validity=cdk.Duration.hours(1), id_token_validity=cdk.Duration.hours(1),
            refresh_token_validity=cdk.Duration.days(1),
        )

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
            environment={"LAKE_BUCKET": lake_bucket_name, "STATE_TABLE": core_table.table_name, "MC_ENV": env_name,
                         "MC_CACHE_PROMPT": "1",  # M4-04: Bedrock prompt caching on the agent worker
                         "OWNER_POOL_ID": self.user_pool.user_pool_id,  # M5-03: owner-only approval writes
                         "OWNER_CLIENT_ID": self.user_pool_client.user_pool_client_id},
        )
        # M6-01 (§14 "API errors"): handled 4xx/5xx answers are not Lambda errors; this counts crashes and timeouts.
        lambda_errors_alarm(self, "ApiErrorsAlarm", self.api, alarm_name=name("api-errors"), threshold=3, topic=alert_topic(self),
                            description="The agent API Lambda crashed or timed out 3+ times in an hour. See its log group (runbook: docs/runbooks/alarms.md).")
        self._kill_switch(name, env_name, lake, role)

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
            header_behavior=cf.OriginRequestHeaderBehavior.allow_list("CloudFront-Viewer-Address", "content-type", "x-mc-owner-token"),  # owner token: M5-03  # OAC itself signs with x-amz-content-sha256 (not allowed here)
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
        cdk.CfnOutput(self, "OwnerPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "OwnerClientId", value=self.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        if dashboard_domain:
            cdk.CfnOutput(self, "DashboardUrl", value=f"https://{dashboard_domain}")

    def _kill_switch(self, name, env_name: str, lake: s3.IBucket, api_role: iam.IRole) -> None:
        """G1 (PLAN.md §11.3 item 4): on any alert, follow the deny policy (API concurrency 0, schedules off, banner).

        Not a kill-switch target itself (no model calls). Every grant names one mc-* resource; no List* on "*".
        """
        acct, region, part = self.account, self.region, cdk.Aws.PARTITION
        schedules = [f"mc-{env_name}-data-{s}" for s in ("nightly", "telemetry")]  # data stack schedules
        scheduler_role = f"arn:{part}:iam::{acct}:role/mc-{env_name}-data-nightly-scheduler"
        fn_name = name("kill-switch")
        role = iam.Role(self, "KillSwitchRole", role_name=fn_name, assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
                        description="Kill switch: read the API role's attached policies, set API concurrency, toggle mc-* schedules, flag.")
        statements = [
            ("ReadApiRolePolicies", ["iam:ListAttachedRolePolicies"], [api_role.role_arn]),
            ("SetApiConcurrency", ["lambda:PutFunctionConcurrency"], [self.api.function_arn]),
            ("ToggleSchedules", ["scheduler:GetSchedule", "scheduler:UpdateSchedule"],
             [f"arn:{part}:scheduler:{region}:{acct}:schedule/default/{s}" for s in schedules]),
            ("FlagAndState", ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
             [lake.arn_for_objects("publish/latest/kill_switch.json"), lake.arn_for_objects("kill_switch/state.json")]),
        ]
        for sid, actions, resources in statements:
            role.add_to_policy(iam.PolicyStatement(sid=sid, actions=actions, resources=resources))
        # Without List, GetObject on the missing state key is a 403 instead of NoSuchKey; limit it to that key.
        role.add_to_policy(iam.PolicyStatement(sid="ListStateKey", actions=["s3:ListBucket"], resources=[lake.bucket_arn],
                                               conditions={"StringEquals": {"s3:prefix": "kill_switch/state.json"}}))
        # UpdateSchedule re-sends the target, which passes the scheduler role again.
        role.add_to_policy(iam.PolicyStatement(sid="PassSchedulerRole", actions=["iam:PassRole"], resources=[scheduler_role],
                                               conditions={"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}}))
        log_group = logs.LogGroup(self, "KillSwitchLogs", log_group_name=f"/aws/lambda/{fn_name}",
                                  retention=logs.RetentionDays.ONE_WEEK, removal_policy=cdk.RemovalPolicy.DESTROY)
        log_group.grant_write(role)
        self.kill_switch = lambda_.Function(
            self, "KillSwitch", function_name=fn_name, runtime=lambda_.Runtime.PYTHON_3_12, handler="handler.handler",
            code=lambda_.Code.from_asset(str(KILL_SWITCH_CODE)), architecture=lambda_.Architecture.ARM_64,
            memory_size=128, timeout=cdk.Duration.seconds(90), retry_attempts=0, role=role, log_group=log_group,
            description="Kill switch (PLAN.md 11.3): follow the budget deny policy; pause the API and schedules, raise the banner.",
            environment={"KILL_SWITCH_POLICY_ARN": f"arn:{part}:iam::{acct}:policy/{KILL_SWITCH_POLICY_NAME}",
                         "API_ROLE_NAME": api_role.role_name, "API_FUNCTION_NAME": self.api.function_name,
                         "API_RESERVED_CONCURRENCY": str(API_RESERVED_CONCURRENCY), "SCHEDULE_NAMES": ",".join(schedules),
                         "LAKE_BUCKET": lake.bucket_name},
        )
        alert_topic(self, "KillSwitchAlerts").add_subscription(subs.LambdaSubscription(self.kill_switch))
        cdk.CfnOutput(self, "KillSwitchFunction", value=self.kill_switch.function_name)
