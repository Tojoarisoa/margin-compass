"""M1-05 exit test: tenant-filtered retrieval over the fair-use policy and three contracts."""

import pytest

from mc_rag import HashingEmbedder, LocalVectorStore, index_corpus, retrieve
from mc_rag.retrieve import TenantIsolationError
from mc_rag.store import QueryResult

TENANTS = ("bc-t0003", "bc-t0009", "bc-t0012")


@pytest.fixture
def store(knowledge_dir):
    s = LocalVectorStore(512)
    index_corpus(knowledge_dir, HashingEmbedder(), s)
    return s


@pytest.mark.parametrize("tenant", TENANTS)
def test_tenant_filter_returns_only_own_contract_and_shared_policy(store, tenant):
    hits = retrieve("What does the contract say about AI usage, pricing and the SLA?", tenant_id=tenant,
                    embedder=HashingEmbedder(), store=store, top_k=20)
    assert hits, "expected results"
    assert {h.tenant_id for h in hits} <= {tenant, "all"}
    assert any(h.tenant_id == tenant for h in hits)
    others = set(TENANTS) - {tenant}
    assert not any(o in h.text for h in hits for o in others), "another tenant's text leaked"


def test_unlimited_clause_ranks_first_for_its_tenant(store):
    hits = retrieve("Is this tenant's AI usage unlimited this term?", tenant_id="bc-t0003",
                    embedder=HashingEmbedder(), store=store, top_k=5)
    assert hits[0].key == "contract-bc-t0003#3" and hits[0].clause_type == "unlimited_ai"


def test_standard_tenant_never_sees_another_tenants_unlimited_clause(store):
    hits = retrieve("Is this tenant's AI usage unlimited this term?", tenant_id="bc-t0009",
                    embedder=HashingEmbedder(), store=store, top_k=20)
    unlimited = [h for h in hits if h.clause_type == "unlimited_ai"]
    assert unlimited and all(h.tenant_id == "all" for h in unlimited)  # only the policy's legacy-clause section


def test_clause_type_filter(store):
    hits = retrieve("response times", tenant_id="bc-t0012", embedder=HashingEmbedder(), store=store,
                    top_k=20, clause_types=["sla", "data_residency"])
    assert {h.key for h in hits} == {"contract-bc-t0012#4", "contract-bc-t0012#5", "policy-compliance#4"}  # + shared policy


def test_unknown_tenant_gets_policy_only(store):
    hits = retrieve("unlimited AI", tenant_id="bc-t0999", embedder=HashingEmbedder(), store=store, top_k=20)
    assert hits and {h.tenant_id for h in hits} == {"all"}


@pytest.mark.parametrize("bad", [None, "", "all", "bc-t0003 OR 1=1", "*"])
def test_tenant_is_required_and_validated_before_embedding(store, bad):
    emb = HashingEmbedder()
    with pytest.raises(ValueError, match="tenant_id"):
        retrieve("x", tenant_id=bad, embedder=emb, store=store)
    assert emb.budget.calls == 0


def test_cross_tenant_hit_from_the_store_fails_closed():
    class LeakyStore:
        def query(self, vector, top_k, flt):
            return [QueryResult("contract-bc-t0012#3", 0.1, {"tenant_id": "bc-t0012"})]

    with pytest.raises(TenantIsolationError):
        retrieve("x", tenant_id="bc-t0003", embedder=HashingEmbedder(), store=LeakyStore())


def test_reindex_skips_unchanged_and_prunes_stale(knowledge_dir, tmp_path):
    s = LocalVectorStore(512)
    first = index_corpus(knowledge_dir, HashingEmbedder(), s)
    assert first["embedded"] == first["chunks"] and first["deleted"] == 0
    second_emb = HashingEmbedder()
    second = index_corpus(knowledge_dir, second_emb, s)
    assert second["embedded"] == 0 and second["unchanged"] == first["chunks"] and second_emb.budget.calls == 0

    import shutil
    copy = tmp_path / "k"
    shutil.copytree(knowledge_dir, copy)
    (copy / "contracts" / "bc-t0009-order-form.md").unlink()
    p = copy / "policies" / "fair-use-policy.md"
    p.write_text(p.read_text().replace("60 days'", "90 days'"))
    third = index_corpus(copy, HashingEmbedder(), s)
    assert third["embedded"] == 1 and third["deleted"] == 5
    assert not any(k.startswith("contract-bc-t0009") for k in s.keys())
