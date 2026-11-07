"""M4-01 step 1: BM25 and hybrid (RRF) retrieval keep tenant isolation."""

import pytest

from mc_rag import BM25Index, HashingEmbedder, LocalVectorStore, hybrid_retrieve, index_corpus, load_corpus
from mc_rag.retrieve import TenantIsolationError


@pytest.fixture
def parts(knowledge_dir):
    s = LocalVectorStore(512)
    index_corpus(knowledge_dir, HashingEmbedder(), s)
    return s, BM25Index(load_corpus(knowledge_dir))


def test_bm25_finds_exact_term_and_respects_tenant(parts):
    _, bm = parts
    res = bm.search("unlimited", tenant_id="bc-t0009", top_k=20)
    assert res and {c.tenant_id for c, _ in res} <= {"bc-t0009", "all"}
    assert all(s > 0 for _, s in res)
    own = bm.search("unlimited", tenant_id="bc-t0003", top_k=1)
    assert any(c.key == "contract-bc-t0003#3" for c, _ in own_all) if (own_all := bm.search(
        "unlimited", tenant_id="bc-t0003", top_k=20)) else False
    assert own


def test_bm25_clause_filter_and_no_match(parts):
    _, bm = parts
    res = bm.search("response", tenant_id="bc-t0012", top_k=20, clause_types=["sla"])
    assert res and {c.clause_type for c, _ in res} == {"sla"}
    assert bm.search("zzzqqq", tenant_id="bc-t0012", top_k=5) == []


def test_hybrid_ranks_own_clause_first_and_stays_isolated(parts):
    store, bm = parts
    hits = hybrid_retrieve("Is this tenant's AI usage unlimited this term?", tenant_id="bc-t0003",
                           embedder=HashingEmbedder(), store=store, bm25=bm, top_k=5)
    assert hits[0].key == "contract-bc-t0003#3"
    assert {h.tenant_id for h in hits} <= {"bc-t0003", "all"}
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_hybrid_validates_tenant_before_embedding(parts):
    store, bm = parts
    emb = HashingEmbedder()
    with pytest.raises(ValueError, match="tenant_id"):
        hybrid_retrieve("x", tenant_id="all", embedder=emb, store=store, bm25=bm)
    assert emb.budget.calls == 0


def test_hybrid_fails_closed_if_bm25_returns_foreign_chunk(parts, knowledge_dir):
    store, bm = parts
    foreign = next(c for c in load_corpus(knowledge_dir)
                   if c.tenant_id == "bc-t0012")

    class Leaky:
        def search(self, *a, **k):
            return [(foreign, 1.0)]

    with pytest.raises(TenantIsolationError):
        hybrid_retrieve("x", tenant_id="bc-t0003", embedder=HashingEmbedder(), store=store, bm25=Leaky())


def test_policy_questions_find_the_right_document(parts):
    store, bm = parts
    for q, doc in [("Who may approve a 20% discount?", "policy-discount-authority"),
                   ("Can safety screening move to a cheaper model if recall drops?", "policy-compliance"),
                   ("Is data residency processing restricted to the EU region for this tenant?", "policy-compliance")]:
        hits = hybrid_retrieve(q, tenant_id="bc-t0009", embedder=HashingEmbedder(), store=store, bm25=bm, top_k=3)
        assert doc in {h.doc_id for h in hits}, q


def test_playbook_schema_and_metric_cards_are_retrievable(knowledge_dir):
    s = LocalVectorStore(512)
    index_corpus(knowledge_dir, HashingEmbedder(), s)
    bm = BM25Index(load_corpus(knowledge_dir))
    for query, key in [("prompt caching saving cache hit", "playbook-cost-levers#2"),
                       ("fct_unit_cost grain day feature model", "schema-gold-tables#1"),
                       ("safety-event recall hard floor 99%", "metric-kpi-cards#4")]:
        hits = hybrid_retrieve(query, tenant_id="bc-t0003", embedder=HashingEmbedder(), store=s, bm25=bm, top_k=5)
        assert key in [h.key for h in hits], query
        assert {h.tenant_id for h in hits} <= {"bc-t0003", "all"}
