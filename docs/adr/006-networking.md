# ADR-006: Networking: no VPC for Lambdas

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §10.2, §11.2

## Context

VPC-attached Lambdas reaching AWS APIs need a NAT Gateway or interface endpoints, both of which cost money every hour.

## Decision

Lambdas run **outside any VPC**. Access control relies on IAM, CloudFront OAC, and resource policies. No resource requires a VPC.

## Alternatives

| Option | Why not |
| --- | --- |
| VPC + NAT Gateway | Hourly cost alone exceeds the budget; forbidden |
| VPC + interface endpoints | Hourly cost per endpoint; forbidden |

## Consequences

- No private networking; data stores are reached over AWS APIs with IAM.
- Function URLs inside a VPC can't stream responses (VER-07), another reason to stay out.

## Cost impact

$0 (avoids NAT and endpoint costs).

## Verified on

2026-11-02 (VER-07): AWS docs confirm function URLs don't support response streaming within a VPC.
