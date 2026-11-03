"""Synth-time guardrail: fail if a forbidden or restricted resource appears (PLAN.md §11.2, ADR-005).

A resource type can be allowed only by an accepted ADR, recorded in ALLOWED_BY_ADR.
"""

from __future__ import annotations

import aws_cdk as cdk
import jsii
from constructs import IConstruct

# CloudFormation type (or prefix ending in "::") -> reason. PLAN.md §11.2.
FORBIDDEN_TYPES: dict[str, str] = {
    "AWS::EC2::NatGateway": "NAT Gateway (hourly cost)",
    "AWS::EC2::EIP": "Elastic IP / public IPv4",
    "AWS::EC2::Instance": "always-on EC2",
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "load balancer (hourly cost)",
    "AWS::ElasticLoadBalancing::LoadBalancer": "load balancer (hourly cost)",
    "AWS::RDS::": "RDS / Aurora (always-on database)",
    "AWS::OpenSearchServerless::": "OpenSearch Serverless (minimum capacity)",
    "AWS::OpenSearchService::": "OpenSearch",
    "AWS::Elasticsearch::": "OpenSearch",
    "AWS::ElastiCache::": "ElastiCache",
    "AWS::Bedrock::ProvisionedModelThroughput": "Bedrock provisioned throughput",
    "AWS::SageMaker::Endpoint": "SageMaker endpoint",
    "AWS::SageMaker::NotebookInstance": "SageMaker notebook",
    "AWS::SageMaker::Domain": "SageMaker Studio",
    "AWS::EKS::": "EKS",
    "AWS::ECS::Service": "always-on ECS / Fargate service",
    "AWS::Redshift::": "Redshift",
    "AWS::RedshiftServerless::": "Redshift Serverless",
    "AWS::EMR::": "EMR",
    "AWS::EMRServerless::": "EMR Serverless",
    "AWS::Glue::Job": "Glue ETL job",
    "AWS::MSK::": "MSK",
    "AWS::QuickSight::": "QuickSight",
    "AWS::SecretsManager::Secret": "Secrets Manager (use SSM Parameter Store)",
    "AWS::KMS::Key": "customer-managed KMS key",
    "AWS::WAFv2::": "WAF",
    "AWS::Route53::HostedZone": "Route 53 hosted zone (no custom domain approved)",
}

# Resource type -> accepted ADR that allows it. Empty until an ADR says otherwise.
ALLOWED_BY_ADR: dict[str, str] = {}


def _forbidden_reason(cfn_type: str) -> str | None:
    if cfn_type in ALLOWED_BY_ADR:
        return None
    for key, reason in FORBIDDEN_TYPES.items():
        if cfn_type == key or (key.endswith("::") and cfn_type.startswith(key)):
            return reason
    return None


def _property_violation(resource: cdk.CfnResource) -> str | None:
    """Restricted configurations of otherwise-allowed services."""
    t = resource.cfn_resource_type
    props = resource._cfn_properties  # noqa: SLF001 - CDK exposes no public getter for raw props
    if t in ("AWS::DynamoDB::Table", "AWS::DynamoDB::GlobalTable"):
        if props.get("billingMode") == "PAY_PER_REQUEST":
            return "DynamoDB on-demand mode (must be provisioned within the free capacity; AGENTS.md rule 2)"
    if t == "AWS::StepFunctions::StateMachine" and props.get("stateMachineType") == "EXPRESS":
        return "Step Functions Express (use Standard)"
    if t == "AWS::Kinesis::Stream":
        details = props.get("streamModeDetails")
        mode = details.get("streamMode") if isinstance(details, dict) else None
        if mode != "ON_DEMAND":
            return "provisioned Kinesis stream"
    if t == "AWS::EC2::VPCEndpoint" and props.get("vpcEndpointType", "Gateway") != "Gateway":
        return "interface VPC endpoint (hourly cost)"
    return None


@jsii.implements(cdk.IAspect)
class ForbiddenResourceGuard:
    """Adds a synth error for every forbidden or restricted resource."""

    def visit(self, node: IConstruct) -> None:
        if not isinstance(node, cdk.CfnResource):
            return
        reason = _forbidden_reason(node.cfn_resource_type) or _property_violation(node)
        if reason:
            cdk.Annotations.of(node).add_error(
                f"Forbidden by PLAN.md §11.2: {node.cfn_resource_type}: {reason}. "
                "Allowed only with an accepted ADR (add it to ALLOWED_BY_ADR)."
            )
