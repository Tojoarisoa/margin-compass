import io
import json

import numpy as np
import pytest

from mc_rag.embed import BudgetExceeded, EmbeddingBudget, HashingEmbedder, TitanEmbedder


def test_hashing_embedder_is_deterministic_and_normalized():
    a, b = HashingEmbedder().embed("Unlimited AI usage"), HashingEmbedder().embed("Unlimited AI usage")
    assert a.shape == (512,) and np.allclose(a, b)
    assert np.isclose(np.linalg.norm(a), 1.0, atol=1e-6)


def test_budget_blocks_before_the_call():
    emb = HashingEmbedder(budget=EmbeddingBudget(max_calls=2))
    emb.embed("one")
    emb.embed("two")
    with pytest.raises(BudgetExceeded, match="call cap"):
        emb.embed("three")
    assert emb.budget.calls == 2


def test_token_cap():
    emb = HashingEmbedder(budget=EmbeddingBudget(max_input_tokens=10))
    with pytest.raises(BudgetExceeded, match="token cap"):
        emb.embed("x" * 60)


class _FakeBedrock:
    def __init__(self):
        self.calls = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        body = json.loads(kwargs["body"])
        vec = [0.0] * body["dimensions"]
        vec[0] = 1.0
        return {"body": io.BytesIO(json.dumps({"embedding": vec, "inputTextTokenCount": 7}).encode())}


def test_titan_request_shape_and_token_accounting():
    fake = _FakeBedrock()
    emb = TitanEmbedder(client=fake)
    vec = emb.embed("hello")
    call = fake.calls[0]
    assert call["modelId"] == "amazon.titan-embed-text-v2:0"
    assert json.loads(call["body"]) == {"inputText": "hello", "dimensions": 512, "normalize": True}
    assert vec.shape == (512,) and emb.budget.input_tokens == 7 and emb.budget.calls == 1


def test_titan_never_called_once_budget_is_spent():
    fake = _FakeBedrock()
    emb = TitanEmbedder(client=fake, budget=EmbeddingBudget(max_calls=0))
    with pytest.raises(BudgetExceeded):
        emb.embed("hello")
    assert fake.calls == []
