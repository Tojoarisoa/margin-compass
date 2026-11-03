"""Margin Compass retrieval (PLAN.md §6.2 Stage 5): parse -> chunk -> embed -> upsert -> filtered search."""

from .corpus import Chunk, Document, load_corpus
from .embed import BudgetExceeded, EmbeddingBudget, HashingEmbedder, TitanEmbedder
from .index import index_corpus
from .retrieve import Hit, retrieve, tenant_filter
from .store import LocalVectorStore, S3VectorsStore

__all__ = [
    "BudgetExceeded", "Chunk", "Document", "EmbeddingBudget", "HashingEmbedder", "Hit", "LocalVectorStore",
    "S3VectorsStore", "TitanEmbedder", "index_corpus", "load_corpus", "retrieve", "tenant_filter",
]
