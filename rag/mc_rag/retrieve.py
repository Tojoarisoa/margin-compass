"""Tenant-filtered retrieval (PLAN.md §6.2 Stage 5). Hybrid BM25 fusion arrives in M4-01.

Tenant isolation is enforced twice:
1. The query always carries a metadata filter: the tenant's own chunks plus shared policies
   (`tenant_id` in [tenant, "all"]). There is no unfiltered entry point.
2. Every returned hit is re-checked; a hit from another tenant raises TenantIsolationError (fail closed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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
