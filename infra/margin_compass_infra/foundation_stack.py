"""Foundation stack (M0-07): account-wide cost guardrails, billing export, and CI identity.

Deployed once per AWS account, in us-east-1 (ADR-002). Resources:
- SNS alert topic (owner e-mail) that Budgets and Cost Anomaly Detection may publish to.
- Monthly cost budget: alert at $3 actual and $5 forecast/actual (PLAN.md §11).
- Kill switch: an IAM deny policy that a Budgets action attaches to workload roles at $5.
  The action is created only once workload role names are configured (they arrive in M1),
  because Budgets actions must name existing roles. Code-level LLM caps stay the first line.
- Cost Anomaly Detection subscription (reuses the AWS-created default monitor when present).
- AWS Data Exports: FOCUS 1.2 with AWS columns, daily granularity, Parquet, to a private bucket.
- GitHub Actions OIDC provider and a deploy role that may only assume the CDK bootstrap roles.

Verified on 2026-11-03 against AWS docs; see docs/runbooks/m0-07-aws-account-setup.md.
"""

from __future__ import annotations

import json

import aws_cdk as cdk
from aws_cdk import aws_bcmdataexports as bcm
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_ce as ce
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from .config import FoundationConfig

ENV_NAME = "shared"  # account-wide resources serve both dev and prod
STAGE = "foundation"

# FOCUS 1.2 with AWS columns (table FOCUS_1_2_AWS), every column, as listed in the
# AWS Data Exports table dictionary (checked 2026-11-03). The export SQL must name columns.
FOCUS_1_2_AWS_COLUMNS = (
    "AvailabilityZone", "BilledCost", "BillingAccountId", "BillingAccountName", "BillingAccountType",
    "BillingCurrency", "BillingPeriodEnd", "BillingPeriodStart", "CapacityReservationId",
    "CapacityReservationStatus", "ChargeCategory", "ChargeClass", "ChargeDescription", "ChargeFrequency",
    "ChargePeriodEnd", "ChargePeriodStart", "CommitmentDiscountCategory", "CommitmentDiscountId",
    "CommitmentDiscountName", "CommitmentDiscountQuantity", "CommitmentDiscountStatus",
    "CommitmentDiscountType", "CommitmentDiscountUnit", "ConsumedQuantity", "ConsumedUnit",
    "ContractedCost", "ContractedUnitPrice", "EffectiveCost", "InvoiceId", "InvoiceIssuerName",
    "ListCost", "ListUnitPrice", "PricingCategory", "PricingCurrency",
    "PricingCurrencyContractedUnitPrice", "PricingCurrencyEffectiveCost",
    "PricingCurrencyListUnitPrice", "PricingQuantity", "PricingUnit", "ProviderName", "PublisherName",
    "RegionId", "RegionName", "ResourceId", "ResourceName", "ResourceType", "ServiceCategory",
    "ServiceName", "ServiceSubcategory", "SkuId", "SkuMeter", "SkuPriceId", "SkuPriceDetails",
    "SubAccountId", "SubAccountName", "SubAccountType", "Tags", "x_Discounts", "x_Operation",
    "x_ServiceCode",
)

# Actions blocked by the kill switch: all model spend and all pipeline starts.
# The dashboard keeps serving cached snapshots (PLAN.md §8.7 degradation).
KILL_SWITCH_DENIED_ACTIONS = ("bedrock:*", "states:StartExecution")


def name(resource: str) -> str:
    """AGENTS.md naming convention: mc-<env>-<stage>-<name>."""
    return f"mc-{ENV_NAME}-{STAGE}-{resource}"


class FoundationStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, config: FoundationConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.config = config
        self.alerts = self._alert_topic()
        self.kill_switch_policy = self._kill_switch_policy()
        self._budget()
        self._anomaly_detection()
        self.billing_bucket = self._billing_export()
        self.deploy_role = self._github_deploy_role()

    # --- Alerts -----------------------------------------------------------------------------
    def _alert_topic(self) -> sns.Topic:
        topic = sns.Topic(self, "Alerts", topic_name=name("alerts"), display_name="Margin Compass alerts")
        topic.add_subscription(subs.EmailSubscription(self.config.alert_email))
        topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowBudgetsAndCostAnomalyDetection",
                principals=[
                    iam.ServicePrincipal("budgets.amazonaws.com"),
                    iam.ServicePrincipal("costalerts.amazonaws.com"),
                    iam.ServicePrincipal("cloudwatch.amazonaws.com"),  # app-stack alarms (M1-08 nightly)
                ],
                actions=["sns:Publish"],
                resources=[topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )
        topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyInsecureTransport",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["sns:Publish"],
                resources=[topic.topic_arn],
                conditions={"Bool": {"aws:SecureTransport": "false"}},
            )
        )
        return topic

    # --- Budget and kill switch -------------------------------------------------------------
    def _kill_switch_policy(self) -> iam.ManagedPolicy:
        return iam.ManagedPolicy(
            self,
            "KillSwitchDeny",
            managed_policy_name=name("kill-switch-deny"),
            description="Attached by the $5 Budgets action: blocks model spend and pipeline runs.",
            statements=[
                iam.PolicyStatement(effect=iam.Effect.DENY, actions=list(KILL_SWITCH_DENIED_ACTIONS), resources=["*"])
            ],
        )

    def _budget(self) -> None:
        cfg = self.config
        budget_name = name("monthly-total")
        sns_subscriber = budgets.CfnBudget.SubscriberProperty(subscription_type="SNS", address=self.alerts.topic_arn)

        def notify(kind: str, amount: float) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    notification_type=kind,
                    comparison_operator="GREATER_THAN",
                    threshold=amount,
                    threshold_type="ABSOLUTE_VALUE",
                ),
                subscribers=[sns_subscriber],
            )

        budget = budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=budget_name,
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=cfg.budget_limit_usd, unit="USD"),
            ),
            notifications_with_subscribers=[
                notify("ACTUAL", cfg.budget_alert_usd),
                notify("FORECASTED", cfg.budget_limit_usd),
                notify("ACTUAL", cfg.budget_limit_usd),
            ],
        )
        budget.node.add_dependency(self.alerts)

        execution_role = iam.Role(
            self,
            "BudgetsActionRole",
            role_name=name("budgets-action"),
            description="Lets AWS Budgets attach and detach the kill-switch deny policy.",
            assumed_by=iam.ServicePrincipal(
                "budgets.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:budgets::{self.account}:budget/*"},
                },
            ),
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
                resources=[f"arn:aws:iam::{self.account}:role/mc-*"],
                conditions={"ArnEquals": {"iam:PolicyARN": self.kill_switch_policy.managed_policy_arn}},
            )
        )

        if cfg.kill_switch_role_names:
            action = budgets.CfnBudgetsAction(
                self,
                "KillSwitchAction",
                budget_name=budget_name,
                action_type="APPLY_IAM_POLICY",
                approval_model="AUTOMATIC",
                notification_type="ACTUAL",
                action_threshold=budgets.CfnBudgetsAction.ActionThresholdProperty(
                    type="ABSOLUTE_VALUE", value=cfg.budget_limit_usd
                ),
                definition=budgets.CfnBudgetsAction.DefinitionProperty(
                    iam_action_definition=budgets.CfnBudgetsAction.IamActionDefinitionProperty(
                        policy_arn=self.kill_switch_policy.managed_policy_arn,
                        roles=list(cfg.kill_switch_role_names),
                    )
                ),
                execution_role_arn=execution_role.role_arn,
                subscribers=[budgets.CfnBudgetsAction.SubscriberProperty(type="SNS", address=self.alerts.topic_arn)],
            )
            action.add_dependency(budget)

    # --- Cost Anomaly Detection -------------------------------------------------------------
    def _anomaly_detection(self) -> None:
        cfg = self.config
        if cfg.existing_anomaly_monitor_arn:
            monitor_arn = cfg.existing_anomaly_monitor_arn
        else:
            monitor = ce.CfnAnomalyMonitor(
                self,
                "ServiceMonitor",
                monitor_name=name("services"),
                monitor_type="DIMENSIONAL",
                monitor_dimension="SERVICE",
            )
            monitor_arn = monitor.attr_monitor_arn

        threshold = {
            "Dimensions": {
                "Key": "ANOMALY_TOTAL_IMPACT_ABSOLUTE",
                "MatchOptions": ["GREATER_THAN_OR_EQUAL"],
                "Values": [f"{cfg.anomaly_threshold_usd:g}"],
            }
        }
        subscription = ce.CfnAnomalySubscription(
            self,
            "AnomalyAlerts",
            subscription_name=name("anomaly-alerts"),
            frequency="IMMEDIATE",  # SNS subscribers require IMMEDIATE
            monitor_arn_list=[monitor_arn],
            threshold_expression=json.dumps(threshold),
            subscribers=[ce.CfnAnomalySubscription.SubscriberProperty(type="SNS", address=self.alerts.topic_arn)],
        )
        subscription.node.add_dependency(self.alerts)

    # --- Billing export (FOCUS 1.2) ---------------------------------------------------------
    def _billing_export(self) -> s3.Bucket:
        bucket = s3.Bucket(
            self,
            "BillingExports",
            bucket_name=f"{name('billing')}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[s3.LifecycleRule(id="expire-after-25-months", expiration=cdk.Duration.days(760))],
        )
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="EnableAWSDataExportsToWriteToS3",
                principals=[iam.ServicePrincipal("bcm-data-exports.amazonaws.com")],
                actions=["s3:PutObject"],
                resources=[bucket.arn_for_objects("*")],
                conditions={
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bcm-data-exports:us-east-1:{self.account}:export/*"},
                    "StringEquals": {"aws:SourceAccount": self.account},
                },
            )
        )

        export = bcm.CfnExport(
            self,
            "Focus12Export",
            export=bcm.CfnExport.ExportProperty(
                name=name("focus-1-2"),
                description="FOCUS 1.2 with AWS columns, daily, Parquet (ADR-015). Feeds source S7.",
                data_query=bcm.CfnExport.DataQueryProperty(
                    query_statement=f"SELECT {', '.join(FOCUS_1_2_AWS_COLUMNS)} FROM FOCUS_1_2_AWS",
                    table_configurations={"FOCUS_1_2_AWS": {"TIME_GRANULARITY": "DAILY"}},
                ),
                destination_configurations=bcm.CfnExport.DestinationConfigurationsProperty(
                    s3_destination=bcm.CfnExport.S3DestinationProperty(
                        s3_bucket=bucket.bucket_name,
                        s3_prefix="focus-1-2",
                        s3_region="us-east-1",
                        s3_output_configurations=bcm.CfnExport.S3OutputConfigurationsProperty(
                            format="PARQUET",
                            compression="PARQUET",
                            output_type="CUSTOM",
                            overwrite="OVERWRITE_REPORT",
                        ),
                    )
                ),
                refresh_cadence=bcm.CfnExport.RefreshCadenceProperty(frequency="SYNCHRONOUS"),
            ),
        )
        export.node.add_dependency(bucket.policy)
        return bucket

    # --- GitHub Actions OIDC ----------------------------------------------------------------
    def _github_deploy_role(self) -> iam.Role:
        provider = iam.OidcProviderNative(
            self,
            "GitHubOidc",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )
        repo = self.config.github_repo
        role = iam.Role(
            self,
            "GitHubDeployRole",
            role_name=name("github-deploy"),
            description=f"Assumed by GitHub Actions on {repo} main: CDK bootstrap roles, dashboard upload, stack outputs.",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": f"repo:{repo}:ref:refs/heads/main",
                    }
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRolesOnly",
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*-{self.account}-{self.region}"],
            )
        )
        # M1-08: infra/scripts/deploy-dashboard.sh and the smoke test (read stack outputs, upload site/, invalidate).
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadMarginCompassStackOutputs",
                actions=["cloudformation:DescribeStacks"],
                resources=[f"arn:aws:cloudformation:{self.region}:{self.account}:stack/mc-*/*"],
            )
        )
        lake = f"arn:aws:s3:::mc-*-data-lake-{self.account}"
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ListDashboardPrefix", actions=["s3:ListBucket"], resources=[lake],
                conditions={"StringLike": {"s3:prefix": ["site/*", "site/"]}},
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(sid="WriteDashboardPrefix", actions=["s3:PutObject", "s3:DeleteObject"], resources=[f"{lake}/site/*"])
        )
        role.add_to_policy(
            iam.PolicyStatement(sid="InvalidateDashboard", actions=["cloudfront:CreateInvalidation"],
                                resources=[f"arn:aws:cloudfront::{self.account}:distribution/*"])
        )
        cdk.CfnOutput(self, "GitHubDeployRoleArn", value=role.role_arn)
        return role
