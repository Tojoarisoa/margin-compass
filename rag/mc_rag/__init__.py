"""Margin Compass retrieval (PLAN.md §6.2 Stage 5): parse -> chunk -> embed -> upsert -> filtered search."""

from .bm25 import BM25Index
from .corpus import Chunk, Document, load_corpus
from .embed import BudgetExceeded, EmbeddingBudget, HashingEmbedder, TitanEmbedder
from .index import index_corpus
from .retrieve import Hit, hybrid_retrieve, retrieve, tenant_filter
from .store import LocalVectorStore, S3VectorsStore

__all__ = [
    "BM25Index", "BudgetExceeded", "Chunk", "Document", "EmbeddingBudget", "HashingEmbedder", "Hit", "LocalVectorStore",
    "S3VectorsStore", "hybrid_retrieve", "TitanEmbedder", "index_corpus", "load_corpus", "retrieve", "tenant_filter",
]
