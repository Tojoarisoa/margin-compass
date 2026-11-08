from pathlib import Path

import pytest

from mc_agents.ledger import Ledger
from mc_agents.tools.metrics import ToolError
from mc_agents.tools.registry import TOOLS, call, search_knowledge_spec
from mc_rag import BM25Index, HashingEmbedder, LocalVectorStore, index_corpus, load_corpus

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"


@pytest.fixture(scope="module")
def extra():
    store = LocalVectorStore(512)
    emb = HashingEmbedder()
    index_corpus(KNOWLEDGE, emb, store)
    spec = search_knowledge_spec(embedder=emb, store=store, bm25=BM25Index(load_corpus(KNOWLEDGE)))
    return {spec.name: spec}


def test_returns_tenant_and_shared_hits_only(extra):
    led = Ledger()
    ev = call("search_knowledge", {"query": "data residency policy", "tenant_id": "bc-t0001"}, led, extra)
    assert ev.tool == "search_knowledge@1" and led.entries == [ev]
    assert ev.result["hits"] and len(ev.result["hits"]) <= 5
    assert {h["key"].split("#")[0] for h in ev.result["hits"]}  # keys present
    allowed = {"bc-t0001", "all"}
    chunks = {c.key: c.tenant_id for c in load_corpus(KNOWLEDGE)}
    assert all(chunks[h["key"]] in allowed for h in ev.result["hits"])


def test_bad_input_leaves_no_evidence(extra):
    led = Ledger()
    for args in ({"query": "x"}, {"query": "", "tenant_id": "bc-t0001"}, {"query": "x", "tenant_id": "other"},
                 {"query": "x", "tenant_id": "bc-t0001", "top_k": 0}, {"query": "x", "tenant_id": "bc-t0001", "top_k": True}):
        with pytest.raises(ToolError):
            call("search_knowledge", args, led, extra)
    assert led.entries == []


def test_not_in_static_registry_and_unavailable_without_extra():
    assert "search_knowledge" not in TOOLS
    with pytest.raises(ToolError):
        call("search_knowledge", {"query": "x", "tenant_id": "bc-t0001"}, Ledger())
