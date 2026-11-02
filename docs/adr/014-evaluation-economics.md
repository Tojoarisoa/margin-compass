# ADR-014: Evaluation economics: replay in CI, live only at pre-release and nightly samples

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §13, AGENTS.md rule 7

## Context

Live LLM calls on every PR would cost money and make CI non-deterministic.

## Decision

CI runs **replayed fixtures** only. **Live** evaluations run at pre-release and on small nightly samples, inside the LLM budget. Fixtures are re-recorded when a prompt, graph, or model changes.

## Alternatives

| Option | Why not |
| --- | --- |
| Live evaluation on every PR | Cost; flaky results |

## Consequences

- Reproducible CI at ≈ $0.
- Fixture drift is caught by the nightly live sample.

## Cost impact

≈ $0 in CI; nightly sample inside the ≤ $0.50 nightly LLM cap.

## Verified on

No VER item.
