"""CloudWatch alarms shared by the app stacks (M6-01, PLAN.md §14: at most 10 alarms in the account).

Every alarm e-mails the account-wide alert topic of the foundation stack. Missing data is not breaching:
dev schedules are off, so a quiet function is healthy.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from constructs import Construct

ALERT_TOPIC_NAME = "mc-shared-foundation-alerts"  # foundation stack (account-wide)


def alert_topic(scope: Construct, construct_id: str = "Alerts") -> sns.ITopic:
    stack = cdk.Stack.of(scope)
    return sns.Topic.from_topic_arn(scope, construct_id,
                                    f"arn:{cdk.Aws.PARTITION}:sns:{stack.region}:{stack.account}:{ALERT_TOPIC_NAME}")


def lambda_errors_alarm(scope: Construct, construct_id: str, fn: lambda_.IFunction, *, alarm_name: str,
                        threshold: int, description: str, topic: sns.ITopic) -> cloudwatch.Alarm:
    """Alarm when the function's Errors sum over one hour reaches `threshold` (unhandled errors, timeouts, crashes)."""
    alarm = cloudwatch.Alarm(
        scope, construct_id, alarm_name=alarm_name,
        metric=fn.metric_errors(period=cdk.Duration.hours(1), statistic="Sum"),
        threshold=threshold, evaluation_periods=1,
        comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        alarm_description=description,
    )
    alarm.add_alarm_action(cw_actions.SnsAction(topic))
    return alarm
