# ADR-003: LLM provider and models: Bedrock on-demand, tiered, behind an abstraction

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §8.7, §11.1, AGENTS.md rules 6–7, VER-05

## Context

Agents need a small fast tier and a stronger reasoning tier, an embedding model, prompt caching, and a single AWS bill. The LLM budget is ≤ $2/month, enforced in code.

## Decision

- **Amazon Bedrock on-demand** behind a provider abstraction; **Ollama** locally; replayed fixtures in CI.
- **Tiers (proposed):**
  - Small / fast path: `amazon.nova-micro-v1:0` (fallback `amazon.nova-2-lite-v1:0`).
  - Specialists: `anthropic.claude-haiku-5-5`, chosen over Haiku 4.5 because its caching minimum is 512 tokens instead of 4,096, which suits short schema cards.
  - Hard cases (rare, capped): `anthropic.claude-sonnet-5-5`.
- **Embeddings:** `amazon.titan-embed-text-v2:0` at **512 dimensions**.
- **Prompt caching** on stable system prompts and schema cards; **batch** only for nightly jobs that don't rely on caching (the two can't be combined).

## Alternatives

| Option | Why not |
| --- | --- |
| Direct vendor APIs | Separate billing and keys; breaks single-bill dogfooding and IAM-only auth |
| Bedrock provisioned throughput | Always-on cost; forbidden (§11.2) |
| Frontier model everywhere | Breaks the $2 LLM budget |

## Consequences

- Model IDs live in config, never in code paths.
- Changing a model requires re-recording CI fixtures (AGENTS.md rule 7).
- **Prices are not yet recorded** (see below). The code caps bound spend regardless.

## Cost impact

≤ $2.00/month LLM + < $0.05 embeddings, capped in code (§11.1). No change.

## Verified on

2026-11-02 (VER-05): model IDs, caching minimums and TTLs, batch-vs-cache exclusion, and Titan V2 dimensions verified on AWS docs. **Open:** per-token prices. The official pricing tables weren't machine-readable; the owner must read them from the Bedrock console or AWS Pricing Calculator and add them here before M1-06.
