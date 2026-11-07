"""Tenant-filtered retrieval (PLAN.md §6.2 Stage 5), vector-only or fused with BM25 (hybrid_retrieve).

Tenant isolation is enforced twice:
1. The query always carries a metadata filter: the tenant's own chunks plus shared policies
   (`tenant_id` in [tenant, "all"]). There is no unfiltered entry point.
2. Every returned hit is re-checked; a hit from another tenant raises TenantIsolationError (fail closed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .bm25 import BM25Index
from .corpus import ALL_TENANTS
from .embed import Embedder
from .store import VectorStore

_TENANT = re.compile(r"^bc-t\d{4}$")
MAX_TOP_K = 20


class TenantIsolationError(RuntimeError):
    """The store returned a chunk the tenant must not see."""


@dataclass(frozen=True)
class Hit:
    key: str
    score: float  # cosine similarity, 1 - distance
    doc_id: str
    tenant_id: str
    source_type: str
    clause_type: str
    heading: str
    text: str


def tenant_filter(tenant_id: str, clause_types: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(tenant_id, str) or not _TENANT.match(tenant_id):
        raise ValueError(f"retrieval needs a valid tenant_id like bc-t0001, got {tenant_id!r}")
    flt: dict[str, Any] = {"tenant_id": {"$in": [tenant_id, ALL_TENANTS]}}
    if clause_types:
        flt = {"$and": [flt, {"clause_type": {"$in": list(clause_types)}}]}
    return flt


def retrieve(query: str, *, tenant_id: str, embedder: Embedder, store: VectorStore,
             top_k: int = 5, clause_types: list[str] | None = None) -> list[Hit]:
    flt = tenant_filter(tenant_id, clause_types)  # validates tenant_id before any model call
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be in 1..{MAX_TOP_K}")
    allowed = {tenant_id, ALL_TENANTS}
    hits = []
    for r in store.query(embedder.embed(query), top_k, flt):
        m = r.metadata
        if m.get("tenant_id") not in allowed:
            raise TenantIsolationError(f"chunk {r.key} belongs to {m.get('tenant_id')!r}, not {tenant_id!r}")
        hits.append(Hit(r.key, 1.0 - r.distance, m.get("doc_id", ""), m["tenant_id"], m.get("source_type", ""),
                        m.get("clause_type", ""), m.get("heading", ""), m.get("text", "")))
    return hits


RRF_K = 60  # reciprocal rank fusion constant


def hybrid_retrieve(query: str, *, tenant_id: str, embedder: Embedder, store: VectorStore, bm25: BM25Index,
                    top_k: int = 5, clause_types: list[str] | None = None, pool: int = 20) -> list[Hit]:
    """Vector search fused with BM25 by reciprocal rank fusion. `score` is the fused RRF score.

    Both legs are tenant-filtered; the vector leg keeps its fail-closed re-check, and the BM25 leg only
    scores chunks visible to the tenant.
    """
    vec = retrieve(query, tenant_id=tenant_id, embedder=embedder, store=store,
                   top_k=min(max(pool, top_k), MAX_TOP_K), clause_types=clause_types)
    kw = bm25.search(query, tenant_id=tenant_id, top_k=pool, clause_types=clause_types)
    allowed = {tenant_id, ALL_TENANTS}
    fused: dict[str, float] = {}
    hits: dict[str, Hit] = {}
    for rank, h in enumerate(vec):
        fused[h.key] = fused.get(h.key, 0.0) + 1.0 / (RRF_K + rank + 1)
        hits[h.key] = h
    for rank, (c, _) in enumerate(kw):
        if c.tenant_id not in allowed:
            raise TenantIsolationError(f"chunk {c.key} belongs to {c.tenant_id!r}, not {tenant_id!r}")
        fused[c.key] = fused.get(c.key, 0.0) + 1.0 / (RRF_K + rank + 1)
        hits.setdefault(c.key, Hit(c.key, 0.0, c.doc_id, c.tenant_id, c.source_type, c.clause_type, c.heading, c.text))
    order = sorted(fused, key=lambda k: (-fused[k], k))[:top_k]
    return [Hit(k, fused[k], hits[k].doc_id, hits[k].tenant_id, hits[k].source_type, hits[k].clause_type,
                hits[k].heading, hits[k].text) for k in order]
