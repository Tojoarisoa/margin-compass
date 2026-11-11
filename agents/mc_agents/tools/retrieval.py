"""`search_knowledge` tool (M4-02, PLAN.md §6.2 Stage 5, §8.6).

Read-only, tenant-filtered hybrid retrieval over the knowledge corpus. The tenant filter and the
fail-closed re-check live in `mc_rag.retrieve`; this wrapper only validates arguments and shapes the
result for the evidence ledger. Hits carry text, never numbers computed by the model.

v2 (M4-05 3c-3f): `tenant_id` is optional. Without it the search sees shared documents only (policies,
playbooks, schema cards): it runs under a tenant ID no tenant has, and every hit is re-checked to be shared
(fail closed). AG-07 used to call the tool with no `tenant_id` and got an error every time.

M6-03 step 2 (EV-09 contract-borne injection): a hit whose text reads like an instruction to the agent
(`intake.instruction_like`) is never passed to the model. Its text is replaced by `WITHHELD` and it is marked
`withheld`; the result then carries a `withheld` count. Results with no such hit keep their exact shape.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mc_agents.intake import instruction_like
from mc_rag import BM25Index, hybrid_retrieve
from mc_rag.corpus import ALL_TENANTS
from mc_rag.embed import Embedder
from mc_rag.retrieve import MAX_TOP_K, TenantIsolationError
from mc_rag.store import VectorStore

_NO_TENANT = "bc-t0000"  # never a real tenant (IDs start at bc-t0001): sees shared documents only
WITHHELD = "[withheld: this passage contains instruction-like text and is not shown to the agent]"


def _hit(rank: int, h: Any) -> dict[str, Any]:
    out = {"rank": rank, "key": h.key, "doc_id": h.doc_id, "source_type": h.source_type,
           "clause_type": h.clause_type, "heading": h.heading, "text": h.text}
    if instruction_like(h.text) or instruction_like(h.heading or ""):
        out.update(heading="", text=WITHHELD, withheld=True)
    return out


def make_search_knowledge(*, embedder: Embedder, store: VectorStore, bm25: BM25Index) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def search_knowledge(args: dict[str, Any]) -> dict[str, Any]:
        query = args["query"]
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        top_k = args.get("top_k", 5)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be an integer in 1..{MAX_TOP_K}")
        clause_types = args.get("clause_types")
        if clause_types is not None and not (isinstance(clause_types, list) and all(isinstance(c, str) for c in clause_types)):
            raise ValueError("clause_types must be a list of strings")
        tenant_id = args.get("tenant_id")
        if tenant_id is None:
            hits = hybrid_retrieve(query, tenant_id=_NO_TENANT, embedder=embedder, store=store, bm25=bm25,
                                   top_k=top_k, clause_types=clause_types)
            if any(h.tenant_id != ALL_TENANTS for h in hits):
                raise TenantIsolationError("a search without tenant_id returned a tenant's chunk")
        else:
            if tenant_id == _NO_TENANT:
                raise ValueError(f"tenant_id {_NO_TENANT} is reserved")
            hits = hybrid_retrieve(query, tenant_id=tenant_id, embedder=embedder, store=store, bm25=bm25,
                                   top_k=top_k, clause_types=clause_types)
        shaped = [_hit(i + 1, h) for i, h in enumerate(hits)]
        out = {"tenant_id": tenant_id or ALL_TENANTS, "query": query, "hits": shaped}
        withheld = sum(1 for h in shaped if h.get("withheld"))
        if withheld:
            out["withheld"] = withheld
        return out
    return search_knowledge
