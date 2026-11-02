# ADR-016: Shared calculation spec for pricing and lever math

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §9, AGENTS.md rule 15

## Context

The dashboard simulators and the agent tools must produce the same numbers.

## Decision

One **calculation spec** in `calc-spec/` defines pricing and lever math, with test vectors. It is implemented once for the browser and once for the agent tools; **parity tests (EV-12)** run both against the same vectors in CI.

## Alternatives

| Option | Why not |
| --- | --- |
| Server-side simulation only | Compute per interaction; slower UI |
| Two independent implementations | Silent disagreement between dashboard and agents |

## Consequences

- Any math change starts in `calc-spec/`.
- The browser implementation runs locally at $0.

## Cost impact

$0.

## Verified on

No VER item.
