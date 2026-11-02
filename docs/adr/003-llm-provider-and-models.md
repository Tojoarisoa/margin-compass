# ADR-003: LLM provider and models: Bedrock on-demand, tiered, behind an abstraction

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §8.7, §11.1, AGENTS.md rules 6–7, VER-05

## Context

The agent catalog (PLAN.md §8.3) uses two tiers: **Small** (AG-01 when rules are inconclusive, AG-02, AG-07, AG-08) and **Mid** (AG-03…AG-06, AG-10). The platform also needs an embedding model, prompt caching, and a single AWS bill. The LLM budget is ≤ $1.50/month online plus ≤ $0.50/month nightly, enforced in code (§11.1).

## Decision

- **Amazon Bedrock on-demand** behind a provider abstraction; **Ollama** locally; replayed fixtures in CI.
- **Small tier:** `amazon.nova-micro-v1:0` (fallback `amazon.nova-2-lite-v1:0`).
- **Mid tier:** `anthropic.claude-haiku-5-5` by default; its prompt-caching minimum is 512 tokens versus 4,096 for `anthropic.claude-haiku-4-5-20251001-v1:0`, so short schema cards and system prompts can be cached. **Selection rule:** once prices are recorded, run the M1-06 replay set on both and keep the model with the lower cost per question at equal or better EV scores.
- No frontier tier. A stronger model needs a new ADR with a cost estimate.
- **Embeddings:** `amazon.titan-embed-text-v2:0` at **512 dimensions**.
- **Prompt caching** on stable system prompts and schema cards; **batch** only for nightly jobs that don't rely on caching (the two can't be combined).

## Alternatives

| Option | Why not |
| --- | --- |
| Direct vendor APIs | Separate billing and keys; breaks single-bill dogfooding and IAM-only auth |
| Bedrock provisioned throughput | Always-on cost; forbidden (§11.2) |
| Frontier model (e.g., `anthropic.claude-sonnet-5-5`) for Mid | Not needed for the §8.3 roles; higher cost per question |

## Consequences

- Model IDs live in config, never in code paths.
- Changing a model requires re-recording CI fixtures (AGENTS.md rule 7).
- **Prices are not yet recorded** (see below). The code caps bound spend regardless.
- **Revisit if** a model's price changes, a cheaper model passes the same replay evaluations, or a model is deprecated.

## Cost impact

≤ $2.00/month LLM (online ≤ $1.50, nightly ≤ $0.50) + < $0.05 embeddings, capped in code (§11.1). No change.

## Verified on

2026-11-02 (VER-05): model IDs, caching minimums and TTLs, batch-vs-cache exclusion, and Titan V2 dimensions verified on AWS docs. **Open:** per-token prices. The official pricing tables weren't machine-readable; the owner must read them from the Bedrock console or AWS Pricing Calculator and add them here before M1-06.
