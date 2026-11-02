# ADR-002: Region: us-east-1

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §10.2, ADR-003, ADR-008, VER-03, VER-04, VER-05, VER-10

## Context

Everything runs in one Region. The Region must offer S3 Vectors, the Bedrock models in ADR-003, and AWS Data Exports.

## Decision

Deploy all stacks to **us-east-1**.

## Alternatives

| Option | Why not |
| --- | --- |
| eu-west-1 | S3 Vectors available, but FOCUS exports are hosted in us-east-1 and model breadth is widest in us-east-1 |
| eu-west-3 | Same, plus narrower model catalog |

## Consequences

- One Region keeps IaC, IAM, and cost simple.
- Free allowances for DynamoDB are per Region, so a single Region uses them fully.

## Cost impact

$0 difference versus alternatives at this scale.

## Verified on

2026-11-02 (VER-03, VER-04): S3 Vectors is available in us-east-1; FOCUS 1.2 exports are hosted in us-east-1; the ADR-003 models are listed as GA with prompt caching available wherever the model is.
