#!/usr/bin/env python3
"""CDK app entry point (ADR-005). Deploy: see docs/runbooks/m0-07-aws-account-setup.md."""

import os

import aws_cdk as cdk

from margin_compass_infra.config import FoundationConfig
from margin_compass_infra.data_stack import DataStack
from margin_compass_infra.foundation_stack import ENV_NAME, STAGE, FoundationStack
from margin_compass_infra.guardrails import ForbiddenResourceGuard
from margin_compass_infra.state_stack import StateStack
from margin_compass_infra.tagging import apply_tags
from margin_compass_infra.web_stack import WebStack

app = cdk.App()
# An empty CDK_DEFAULT_ACCOUNT (e.g. expired credentials) would leak into resource names; fail clearly instead.
account = os.environ.get("CDK_DEFAULT_ACCOUNT") or None
if account is None:
    raise SystemExit("No AWS account resolved (CDK_DEFAULT_ACCOUNT is empty). Sign in first: aws login --profile mc-admin")
config = FoundationConfig.from_app(app)

foundation = FoundationStack(
    app,
    "mc-shared-foundation",
    config=config,
    env=cdk.Environment(account=account, region=config.region),
    description="Margin Compass foundation: budgets, kill switch, anomaly alerts, FOCUS 1.2 export, GitHub OIDC (M0-07)",
)
apply_tags(foundation, project=config.project, env=ENV_NAME, stage=STAGE, owner=config.owner, cost_center=config.cost_center)
state_dev = StateStack(
    app,
    "mc-dev-state",
    env_name="dev",
    env=cdk.Environment(account=account, region=config.region),
    description="Margin Compass dev state: DynamoDB core table (ADR-011; M1-04 model registry)",
)
apply_tags(state_dev, project=config.project, env="dev", stage="state", owner=config.owner, cost_center=config.cost_center)

data_dev = DataStack(
    app,
    "mc-dev-data",
    env_name="dev",
    core_table=state_dev.core,
    nightly_enabled=str(app.node.try_get_context("mc:nightlyEnabled")).lower() == "true",
    env=cdk.Environment(account=account, region=config.region),
    description="Margin Compass dev data: S3 lake, pipeline Lambda, knowledge index, nightly run (M1-02, M1-05, M1-08)",
)
apply_tags(data_dev, project=config.project, env="dev", stage="data", owner=config.owner, cost_center=config.cost_center)

web_dev = WebStack(
    app,
    "mc-dev-web",
    env_name="dev",
    lake_bucket_name=data_dev.lake.bucket_name,
    core_table=state_dev.core,
    dashboard_domain=app.node.try_get_context("mc:dashboardDomain") or None,
    env=cdk.Environment(account=account, region=config.region),
    description="Margin Compass dev web: CloudFront for the dashboard, snapshots, and agent API (M1-07)",
)
apply_tags(web_dev, project=config.project, env="dev", stage="web", owner=config.owner, cost_center=config.cost_center)

cdk.Aspects.of(app).add(ForbiddenResourceGuard())

app.synth()
