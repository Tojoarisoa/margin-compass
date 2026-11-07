"""EV-04 gate: recall@5 >= 0.85 on the golden set, no cross-tenant hits."""

import pytest

from mc_rag import BM25Index, HashingEmbedder, LocalVectorStore, index_corpus, load_corpus
from mc_rag.golden import evaluate, load_cases


@pytest.fixture
def result(knowledge_dir):
    s = LocalVectorStore(512)
    index_corpus(knowledge_dir, HashingEmbedder(), s)
    return evaluate(load_cases(), embedder=HashingEmbedder(), store=s, bm25=BM25Index(load_corpus(knowledge_dir)))


def test_ev04_passes(result):
    assert result["leaks"] == []
    assert result["passed"], result


def test_golden_set_is_covered_and_valid(knowledge_dir):
    keys = {c.key for c in load_corpus(knowledge_dir)}
    cases = load_cases()
    assert len(cases) >= 20
    assert all(set(c.expected) <= keys for c in cases)
    assert {c.tenant_id for c in cases} == {"bc-t0003", "bc-t0009", "bc-t0012"}
