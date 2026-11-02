"""ForbiddenResourceGuard (PLAN.md §11.2, ADR-005): forbidden resources must fail synthesis."""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk.assertions import Annotations, Match

from margin_compass_infra.guardrails import ForbiddenResourceGuard


def errors_for(build) -> list:
    app = cdk.App()
    stack = cdk.Stack(app, "Probe", env=cdk.Environment(account="123456789012", region="us-east-1"))
    build(stack)
    cdk.Aspects.of(app).add(ForbiddenResourceGuard())
    return Annotations.from_stack(stack).find_error("*", Match.string_like_regexp("Forbidden by PLAN.md"))


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda s: ec2.CfnNatGateway(s, "Nat", subnet_id="subnet-1"), id="nat-gateway"),
        pytest.param(lambda s: secretsmanager.Secret(s, "Secret"), id="secrets-manager"),
        pytest.param(
            lambda s: dynamodb.CfnTable(
                s,
                "OnDemand",
                billing_mode="PAY_PER_REQUEST",
                key_schema=[dynamodb.CfnTable.KeySchemaProperty(attribute_name="pk", key_type="HASH")],
                attribute_definitions=[dynamodb.CfnTable.AttributeDefinitionProperty(attribute_name="pk", attribute_type="S")],
            ),
            id="dynamodb-on-demand",
        ),
        pytest.param(
            lambda s: sfn.StateMachine(
                s, "Express", definition_body=sfn.DefinitionBody.from_chainable(sfn.Pass(s, "P")),
                state_machine_type=sfn.StateMachineType.EXPRESS,
            ),
            id="step-functions-express",
        ),
    ],
)
def test_forbidden_resources_fail_synthesis(build):
    assert errors_for(build)


def test_allowed_resources_pass():
    def build(s):
        dynamodb.CfnTable(
            s,
            "Provisioned",
            billing_mode="PROVISIONED",
            provisioned_throughput=dynamodb.CfnTable.ProvisionedThroughputProperty(read_capacity_units=5, write_capacity_units=5),
            key_schema=[dynamodb.CfnTable.KeySchemaProperty(attribute_name="pk", key_type="HASH")],
            attribute_definitions=[dynamodb.CfnTable.AttributeDefinitionProperty(attribute_name="pk", attribute_type="S")],
        )
        sfn.StateMachine(s, "Standard", definition_body=sfn.DefinitionBody.from_chainable(sfn.Pass(s, "P")))

    assert errors_for(build) == []
