"""Index the knowledge corpus: chunk -> skip unchanged (content hash) -> embed -> upsert -> prune stale."""

from __future__ import annotations

import logging
from pathlib import Path

from .corpus import load_corpus
from .embed import Embedder
from .store import VectorRecord, VectorStore

log = logging.getLogger("mc_rag")


def index_corpus(knowledge_dir: Path, embedder: Embedder, store: VectorStore) -> dict:
    """Idempotent: a second run with an unchanged corpus makes no embedding calls and no writes.

    The content hash covers the embedded text; the embedding model and dimensions are fixed per index
    (a new model means a new index, ADR-003), so they are not part of the hash.
    """
    chunks = load_corpus(knowledge_dir)
    existing = store.get_hashes([c.key for c in chunks])
    changed = [c for c in chunks if existing.get(c.key) != c.content_sha]

    records = []
    for c in changed:
        meta = {**c.filterable_metadata(), "heading": c.heading, "text": c.text}
        records.append(VectorRecord(c.key, embedder.embed(c.text), meta))
    if records:
        store.put(records)

    current = {c.key for c in chunks}
    stale = [k for k in store.keys() if k not in current]
    if stale:
        store.delete(stale)

    stats = {
        "chunks": len(chunks), "embedded": len(records), "unchanged": len(chunks) - len(records),
        "deleted": len(stale), "documents": len({c.doc_id for c in chunks}),
        "tenants": sorted({c.tenant_id for c in chunks}), "embedding_model": embedder.model_id,
        "embedding_calls": embedder.budget.calls, "embedding_input_tokens": embedder.budget.input_tokens,
    }
    log.info("rag_index_finished", extra={"fields": stats})
    return stats
