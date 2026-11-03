# ADR-003: LLM provider and models: Bedrock on-demand, tiered, behind an abstraction

- **Status:** Accepted (2026-11-03, by the owner)
- **Date:** 2026-11-02
- **Related:** PLAN.md §8.7, §11.1, AGENTS.md rules 6–7, VER-05

## Context

The agent catalog (PLAN.md §8.3) uses two tiers: **Small** (AG-01 when rules are inconclusive, AG-02, AG-07, AG-08) and **Mid** (AG-03…AG-06, AG-10). The platform also needs an embedding model, prompt caching, and a single AWS bill. The LLM budget is ≤ $1.50/month online plus ≤ $0.50/month nightly, enforced in code (§11.1).

## Decision

- **Amazon Bedrock on-demand** behind a provider abstraction; **Ollama** locally; replayed fixtures in CI.
- **Small tier:** `amazon.nova-micro-v1:0` (fallback `amazon.nova-2-lite-v1:0`).
- **Mid tier:** `anthropic.claude-haiku-5-5` by default (**interim: `anthropic.claude-haiku-4-5-20251001-v1:0`**, see below); its prompt-caching minimum is 512 tokens versus 4,096 for `anthropic.claude-haiku-4-5-20251001-v1:0`, so short schema cards and system prompts can be cached. **Selection rule:** once prices are recorded, run the M1-06 replay set on both and keep the model with the lower cost per question at equal or better EV scores.
- **Interim Mid default (owner, 2026-11-04):** Claude Haiku 4.5. After the Anthropic use-case form, Haiku 4.5 calls succeed but Haiku 5.5 is still denied ("not available for this account"). Haiku 4.5 passed the M1-06 replay set 5/5 at $0.0043 per question (2 calls), inside EV-10's $0.01. Switch back to Haiku 5.5 when the account gets access and it passes the same set; until then the online budget buys about 10× fewer tokens per dollar.
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
- **Invocation goes through the `us.` cross-region inference profiles** (`us.anthropic.claude-haiku-5-5`, `us.anthropic.claude-haiku-4-5-20251001-v1:0`, `us.amazon.nova-micro-v1:0`). Verified 2026-11-04: Bedrock rejects on-demand calls to the in-region Claude Haiku 4.5 ID ("on-demand throughput isn't supported"); the `us.` profiles are ACTIVE. Requests stay in US Regions; caps use the in-region price.
- **Anthropic models need a one-time model-access agreement** in the Bedrock console. On 2026-11-04 `get-foundation-model-availability` reported `agreementAvailability: NOT_AVAILABLE` for both Claude Haiku models, and calls were denied until the owner completed it; Nova Micro needed no agreement.
- Changing a model requires re-recording CI fixtures (AGENTS.md rule 7).
- **Prices are recorded** below (2026-11-04). The code caps bound spend regardless.
- At list price, Claude Haiku 5.5 costs one tenth of Haiku 4.5 per token (input and output), so Haiku 5.5 stays the Mid default; the M1-06 replay comparison still runs, as the selection rule requires.
- The in-region rate is 10% above the global cross-region rate. We use **in-region** prices for caps (the higher figure), and in-region calls keep data in us-east-1.
- **Revisit if** a model's price changes, a cheaper model passes the same replay evaluations, or a model is deprecated.

## Prices (us-east-1, on-demand, USD per 1M tokens)

| Model ID | Input | Output | Cache read | Cache write (5 min) | Cache write (1 h) | Batch input | Batch output |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `amazon.nova-micro-v1:0` | 0.035 | 0.14 | 0.00875 | 0.00 | — | 0.0175 | 0.07 |
| `anthropic.claude-haiku-5-5` (in-region) | 0.11 | 0.55 | 0.011 | 0.1375 | 0.22 | not listed | not listed |
| `anthropic.claude-haiku-5-5` (global) | 0.10 | 0.50 | 0.010 | 0.125 | 0.20 | not listed | not listed |
| `anthropic.claude-haiku-4-5-20251001-v1:0` (in-region) | 1.10 | 5.50 | 0.11 | 1.375 | 2.20 | 0.55 | 2.75 |
| `anthropic.claude-haiku-4-5-20251001-v1:0` (global) | 1.00 | 5.00 | 0.10 | 1.25 | 2.00 | 0.50 | 2.50 |
| `amazon.titan-embed-text-v2:0` | 0.02 | — | — | — | — | 0.01 | — |

Source: AWS Price List API (`aws pricing get-products`, region code `us-east-1`, on-demand terms), read 2026-11-04. Price lists `AmazonBedrock` 20261102165015 (Nova, Titan) and `AmazonBedrockFoundationModels` 20261012084008 (Claude). USD per 1M tokens; Nova and Titan are listed per 1K tokens and were multiplied by 1,000 in a script. Long-context Claude rates (5× standard) are not shown: our prompts stay well below the long-context threshold.

## Cost impact

≤ $2.00/month LLM (online ≤ $1.50, nightly ≤ $0.50) + < $0.05 embeddings, capped in code (§11.1). No change.

## Verified on

2026-11-02 (VER-05): model IDs, caching minimums and TTLs, batch-vs-cache exclusion, and Titan V2 dimensions verified on AWS docs. 2026-11-04: per-token prices read from the AWS Price List API (table above), closing the VER-05 open item.
