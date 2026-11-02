# ADR-001: Business problem: AI cost-to-serve and gross-margin intelligence

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §1–§4, ADR-017, VER-14

## Context

Generic cloud FinOps is well covered by existing tools, and practitioners report the easy infrastructure waste is largely captured. AI features have added a real marginal cost per interaction to products priced for near-zero marginal cost.

## Decision

Margin Compass targets **AI cost-to-serve and gross margin for AI-enabled B2B SaaS**: daily cost and margin per tenant × feature × model, margin-leak detection, pricing and lever simulation, and human-approved actions scored in margin dollars and quality.

## Alternatives

| Option | Why not |
| --- | --- |
| Generic cloud FinOps | Crowded; easy waste already captured |
| Supply-chain analytics | No link to AI unit economics |
| Churn prediction only | One model, not a decision system |

## Consequences

- Every feature must move or explain a margin KPI (AGENTS.md rule 13).
- Needs joined data (telemetry + billing + revenue + outcomes), supplied by the BoonCore simulator (ADR-017).
- **Revisit if** primary industry sources (ICONIQ, Harness; before M6-04) contradict the margin-pressure premise.

## Cost impact

$0. Framing decision.

## Verified on

2026-11-02 (VER-14, see `docs/verification/2026-11-02-m0-05.md`). State of FinOps 2026 verified on the primary source: 98% of respondents manage AI spend (63% in 2025, 31% in 2024), and FinOps for AI is the top forward-looking priority. ICONIQ figures are secondary; one claim (inference as a share of revenue) is reworded to a share of total spend.
