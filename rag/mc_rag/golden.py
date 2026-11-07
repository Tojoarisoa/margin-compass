"""EV-04: retrieval golden set. Recall@k = share of questions whose top-k hits contain an expected chunk.

Each case: question, tenant, and the chunk keys that answer it (any one counts). Contract questions are
asked as the owning tenant. A hit from another tenant fails the whole evaluation (isolation, not recall).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .retrieve import hybrid_retrieve

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "golden" / "ev04.json"
RECALL_GATE = 0.85


@dataclass(frozen=True)
class Case:
    question: str
    tenant_id: str
    expected: tuple[str, ...]


def load_cases(path: Path = GOLDEN_PATH) -> list[Case]:
    return [Case(c["question"], c["tenant_id"], tuple(c["expected"])) for c in json.loads(path.read_text())]


def evaluate(cases: list[Case], *, embedder, store, bm25, top_k: int = 5) -> dict:
    misses, leaks = [], []
    for c in cases:
        hits = hybrid_retrieve(c.question, tenant_id=c.tenant_id, embedder=embedder, store=store, bm25=bm25, top_k=top_k)
        leaks += [h.key for h in hits if h.tenant_id not in (c.tenant_id, "all")]
        if not set(c.expected) & {h.key for h in hits}:
            misses.append(c.question)
    recall = 1 - len(misses) / len(cases)
    return {"recall_at_k": round(recall, 4), "k": top_k, "n": len(cases), "misses": misses,
            "leaks": leaks, "passed": recall >= RECALL_GATE and not leaks}
