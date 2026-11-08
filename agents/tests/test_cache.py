from mc_agents.approvals import MemoryStore
from mc_agents.cache import cache_key, lookup, store_answer

OUT = {"status": "verified", "answer": "ok", "evidence": [{"id": "E1"}], "cost_line": "Cost of this answer: $0.01"}


def test_hit_is_labelled_and_free():
    s, t = MemoryStore(), [100.0]
    assert store_answer(s, "acme", "What is  margin?", "v1", OUT, clock=lambda: t[0])
    t[0] = 160
    hit = lookup(s, "acme", "what is margin?", "v1", clock=lambda: t[0])
    assert hit["degradation"] == "cached" and hit["cache_age_s"] == 60 and "no LLM call" in hit["cost_line"]
    assert hit["answer"] == "ok" and OUT["cost_line"].endswith("$0.01")


def test_isolated_by_tenant_version_and_expiry():
    s, t = MemoryStore(), [0.0]
    store_answer(s, "acme", "q", "v1", OUT, clock=lambda: t[0])
    assert lookup(s, "other", "q", "v1", clock=lambda: t[0]) is None
    assert lookup(s, "acme", "q", "v2", clock=lambda: t[0]) is None
    t[0] = 3601
    assert lookup(s, "acme", "q", "v1", clock=lambda: t[0]) is None
    assert cache_key("a", "q", "v") != cache_key("a", "q", "w")


def test_only_verified_cached():
    s = MemoryStore()
    for status in ("unverified", "blocked", "needs_approval", "pending"):
        assert not store_answer(s, "acme", "q", "v1", {**OUT, "status": status})
    assert lookup(s, "acme", "q", "v1") is None
