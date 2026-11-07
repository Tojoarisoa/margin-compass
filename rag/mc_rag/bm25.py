"""In-process BM25 keyword index over chunks (PLAN.md §6.2 Stage 5; S3 Vectors has no keyword search).

The index is built from the parsed corpus, so it holds the same chunks as the vector store. Tenant
visibility is applied before scoring: a chunk of another tenant is never scored or returned.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .corpus import ALL_TENANTS, Chunk

_TOKEN = re.compile(r"[a-z0-9]+")
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = list(chunks)
        self._tf = [Counter(tokenize(c.text)) for c in self._chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        self._df: Counter[str] = Counter()
        for tf in self._tf:
            self._df.update(tf.keys())

    def __len__(self) -> int:
        return len(self._chunks)

    def search(self, query: str, *, tenant_id: str, top_k: int,
               clause_types: list[str] | None = None) -> list[tuple[Chunk, float]]:
        """Top chunks by BM25 among those visible to `tenant_id` (own chunks plus shared policies)."""
        allowed = {tenant_id, ALL_TENANTS}
        terms = tokenize(query)
        n = len(self._chunks)
        scored: list[tuple[Chunk, float]] = []
        for i, chunk in enumerate(self._chunks):
            if chunk.tenant_id not in allowed:
                continue
            if clause_types and chunk.clause_type not in clause_types:
                continue
            score = 0.0
            for t in terms:
                f = self._tf[i].get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                denom = f + K1 * (1 - B + B * self._len[i] / (self._avg or 1.0))
                score += idf * f * (K1 + 1) / denom
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda cs: (-cs[1], cs[0].key))
        return scored[:top_k]
