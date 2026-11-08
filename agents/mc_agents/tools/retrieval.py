"""`search_knowledge` tool (M4-02, PLAN.md §6.2 Stage 5, §8.6).

Read-only, tenant-filtered hybrid retrieval over the knowledge corpus. The tenant filter and the
fail-closed re-check live in `mc_rag.retrieve`; this wrapper only validates arguments and shapes the
result for the evidence ledger. Hits carry text, never numbers computed by the model.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mc_rag import BM25Index, hybrid_retrieve
from mc_rag.embed import Embedder
from mc_rag.retrieve import MAX_TOP_K
from mc_rag.store import VectorStore


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
        hits = hybrid_retrieve(query, tenant_id=args["tenant_id"], embedder=embedder, store=store, bm25=bm25,
                               top_k=top_k, clause_types=clause_types)
        return {"tenant_id": args["tenant_id"], "query": query, "hits": [
            {"rank": i + 1, "key": h.key, "doc_id": h.doc_id, "source_type": h.source_type,
             "clause_type": h.clause_type, "heading": h.heading, "text": h.text} for i, h in enumerate(hits)]}
    return search_knowledge
