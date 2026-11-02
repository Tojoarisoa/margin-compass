"""Typed configuration read from CDK context (cdk.json plus `-c key=value` at deploy time).

The alert e-mail is never committed: pass it with `-c mc:alertEmail=you@example.com`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import aws_cdk as cdk


@dataclass(frozen=True)
class FoundationConfig:
    alert_email: str
    github_repo: str  # "owner/repo"
    project: str = "margin-compass"
    owner: str = "owner"
    cost_center: str = "margin-compass"
    region: str = "us-east-1"
    budget_alert_usd: float = 3.0  # PLAN.md §11: alert at $3
    budget_limit_usd: float = 5.0  # PLAN.md §11: hard ceiling and kill switch at $5
    anomaly_threshold_usd: float = 1.0
    existing_anomaly_monitor_arn: str = ""  # reuse the AWS-created default monitor if present
    kill_switch_role_names: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if "/" not in self.github_repo:
            raise ValueError("mc:githubRepo must look like 'owner/repo'")
        if not 0 < self.budget_alert_usd < self.budget_limit_usd:
            raise ValueError("budget alert must be positive and below the budget limit")
        if "@" not in self.alert_email:
            raise ValueError("pass the alert e-mail with: -c mc:alertEmail=you@example.com")

    @classmethod
    def from_app(cls, app: cdk.App) -> FoundationConfig:
        ctx = app.node.try_get_context
        return cls(
            alert_email=ctx("mc:alertEmail") or "",
            github_repo=ctx("mc:githubRepo"),
            project=ctx("mc:project"),
            owner=ctx("mc:owner"),
            cost_center=ctx("mc:costCenter"),
            region=ctx("mc:region"),
            budget_alert_usd=float(ctx("mc:budgetAlertUsd")),
            budget_limit_usd=float(ctx("mc:budgetLimitUsd")),
            anomaly_threshold_usd=float(ctx("mc:anomalyThresholdUsd")),
            existing_anomaly_monitor_arn=ctx("mc:existingAnomalyMonitorArn") or "",
            kill_switch_role_names=list(ctx("mc:killSwitchRoleNames") or []),
        )
