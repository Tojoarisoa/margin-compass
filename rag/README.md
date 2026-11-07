# rag/: parsing, chunking, embedding, and tenant-filtered retrieval

PLAN.md §6.2 Stage 5. M1-05 indexes the fair-use policy and three contracts from `knowledge/`
(all synthetic) and proves tenant-filtered retrieval. Hybrid BM25 fusion (`hybrid_retrieve`, reciprocal rank fusion) is in; the full EV-04
gate (M4) come later.

```bash
cd rag
uv sync
uv run pytest -q                                   # corpus, embedders, stores, tenant-filtered retrieval
uv run mc-rag index                                # knowledge/ -> data/local/rag/index.json (hashing, no network)
uv run mc-rag query --tenant bc-t0003 "Is AI usage unlimited?"
```

The pipeline (`mc-pipeline run`, and the AWS Lambda) runs this as Stage 5 after training.

| Piece | Code | Local / CI | AWS (dev) |
| --- | --- | --- | --- |
| Parse + chunk | `mc_rag/corpus.py` | one chunk per `##` section; strict front matter | same |
| Embed | `mc_rag/embed.py` | `HashingEmbedder` (deterministic, no network) | `TitanEmbedder`: `amazon.titan-embed-text-v2:0`, 512 dims, normalized |
| Store | `mc_rag/store.py` | `LocalVectorStore`, `data/local/rag/index.json` | `S3VectorsStore`: bucket `mc-dev-knowledge-<account>`, index `kb-titan-v2-512` (cosine) |
| Index | `mc_rag/index.py` | skip unchanged chunks by content hash, prune stale keys | same |
| Retrieve | `mc_rag/retrieve.py` | filter `tenant_id in [tenant, "all"]`, re-checked per hit | same |

## Vector metadata

| Key | Filterable | Example |
| --- | --- | --- |
| `doc_id` | yes | `contract-bc-t0003` |
| `source_type` | yes | `policy`, `contract` |
| `tenant_id` | yes | `bc-t0003`, or `all` for policies |
| `clause_type` | yes | `unlimited_ai`, `sla`, `data_residency` |
| `effective_date` | yes | `2025-04-29` |
| `content_sha` | yes | sha256 of the embedded text |
| `heading`, `text` | **no** (declared on the index) | section heading and chunk text |

Vector keys are `<doc_id>#<section>[.<part>]`, e.g. `contract-bc-t0003#3`.

## Guardrails

- **Tenant isolation, fail closed:** `retrieve()` has no unfiltered path. It validates `tenant_id`
  before any embedding call, always sends the tenant filter, and raises `TenantIsolationError` if
  the store returns another tenant's chunk.
- **Budget in code (AGENTS.md rule 6):** `EmbeddingBudget` caps each run at 200 calls and 100,000
  input tokens, checked *before* each Bedrock call. Unchanged chunks are never re-embedded, so a
  nightly re-run makes no Bedrock calls. At the ADR-003 price ($0.02 per 1M tokens) a run costs at
  most $0.002.
- **No live model calls in CI:** tests use `HashingEmbedder` and a stubbed Bedrock client.
- **Kill switch:** the pipeline role `mc-dev-data-pipeline` is a kill-switch target, so the budget
  action denies `bedrock:*` to it at the $5 ceiling.
