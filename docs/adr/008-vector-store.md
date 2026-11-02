# ADR-008: Vector store: S3 Vectors + in-Lambda BM25

- **Status:** Proposed
- **Date:** 2026-11-02
- **Related:** PLAN.md §6.2 Stage 5, VER-03

## Context

The corpus is small (policies, contracts, playbooks, cards). Retrieval needs tenant-filtered vector search plus keyword matching.

## Decision

**S3 Vectors** with metadata filters (`tenant_id`, `clause_type`, `effective_date`) for semantic search, fused with **BM25** over a small index file loaded in Lambda. LanceDB-on-S3 is the fallback.

## Alternatives

| Option | Why not |
| --- | --- |
| OpenSearch Serverless | Minimum capacity cost; forbidden |
| pgvector on RDS | Always-on database; forbidden |
| Bedrock Knowledge Bases | Backed by OpenSearch by default |

## Consequences

- Filterable metadata must stay under 2 KB per vector; contract text goes in non-filterable metadata or the chunk store.
- 512-dimension embeddings (ADR-003) keep storage tiny.

## Cost impact

< $0.10/month (§11.1). At thousands of 512-d vectors, storage is a fraction of a cent.

## Verified on

2026-11-02 (VER-03): availability in us-east-1, limits (1–4,096 dims, 2 KB filterable metadata, top-K 10,000), GA status, and pricing ($0.06/GB-month, $2.50 per million queries) verified.
