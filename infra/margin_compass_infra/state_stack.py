"""State stack (M1-04): the single-table DynamoDB `core` store for one environment (ADR-011).

Provisioned capacity, autoscaling off: every table and GSI across dev and prod shares the free
allowance of 25 RCU / 25 WCU (ADR-011, AGENTS.md rule 2). M1 uses it for the model registry; agents
(rate limits, budgets, actions, job status) add item types later, not new tables.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

CORE_READ_CAPACITY = 2
CORE_WRITE_CAPACITY = 2


class StateStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, env_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.core = dynamodb.Table(
            self,
            "Core",
            table_name=f"mc-{env_name}-state-core",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PROVISIONED,
            read_capacity=CORE_READ_CAPACITY,
            write_capacity=CORE_WRITE_CAPACITY,
            time_to_live_attribute="ttl",
            encryption=dynamodb.TableEncryption.DEFAULT,  # AWS-owned key: free (no customer-managed KMS)
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        cdk.CfnOutput(self, "CoreTable", value=self.core.table_name)
