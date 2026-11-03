"""Embedders and the per-run embedding budget.

- TitanEmbedder: Amazon Titan Text Embeddings V2 on Bedrock (ADR-003), 512 dims, normalized. AWS only.
- HashingEmbedder: deterministic feature hashing, no network. Used by tests and CI (AGENTS.md: no
  live model calls in CI) and by local runs without AWS credentials.

Every Bedrock call goes through EmbeddingBudget, which is checked *before* the call (AGENTS.md rule 6:
budgets are enforced in code). At the ADR-003 list price of $0.02 per 1M input tokens (Price List
API, 2026-11-04), the 100,000-token cap bounds a run at $0.002.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Protocol

import numpy as np

TITAN_V2_MODEL_ID = "amazon.titan-embed-text-v2:0"
DIMENSIONS = 512  # ADR-003
TITAN_V2_DIMENSIONS = (256, 512, 1024)
TITAN_V2_MAX_INPUT_TOKENS = 8_192
DEFAULT_MAX_CALLS_PER_RUN = 200
DEFAULT_MAX_TOKENS_PER_RUN = 100_000

_WORD = re.compile(r"[a-z0-9]+")


class BudgetExceeded(RuntimeError):
    """An embedding call would exceed the per-run cap. Nothing was sent."""


@dataclass
class EmbeddingBudget:
    max_calls: int = DEFAULT_MAX_CALLS_PER_RUN
    max_input_tokens: int = DEFAULT_MAX_TOKENS_PER_RUN
    calls: int = 0
    input_tokens: int = 0

    @staticmethod
    def estimate_tokens(text: str) -> int:
        # Conservative upper bound (~3 characters per token) so the pre-call check never under-counts much.
        return max(1, math.ceil(len(text) / 3))

    def reserve(self, text: str) -> None:
        estimate = self.estimate_tokens(text)
        if estimate > TITAN_V2_MAX_INPUT_TOKENS:
            raise BudgetExceeded(f"chunk of ~{estimate} tokens exceeds the model input limit")
        if self.calls + 1 > self.max_calls:
            raise BudgetExceeded(f"embedding call cap reached ({self.max_calls} per run)")
        if self.input_tokens + estimate > self.max_input_tokens:
            raise BudgetExceeded(f"embedding token cap reached ({self.max_input_tokens} per run)")

    def record(self, tokens: int) -> None:
        self.calls += 1
        self.input_tokens += tokens


class Embedder(Protocol):
    model_id: str
    dimensions: int

    def embed(self, text: str) -> np.ndarray: ...


@dataclass
class HashingEmbedder:
    """Signed feature hashing of word unigrams and bigrams, L2-normalized. Deterministic across runs."""

    dimensions: int = DIMENSIONS
    model_id: str = "local-hashing-v1"
    budget: EmbeddingBudget = field(default_factory=EmbeddingBudget)

    def embed(self, text: str) -> np.ndarray:
        self.budget.reserve(text)
        words = _WORD.findall(text.lower())
        features = words + [f"{a} {b}" for a, b in pairwise(words)]
        vec = np.zeros(self.dimensions, dtype=np.float32)
        for feat in features:
            h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
            vec[h % self.dimensions] += 1.0 if (h >> 63) & 1 else -1.0
        norm = float(np.linalg.norm(vec))
        self.budget.record(self.budget.estimate_tokens(text))
        return vec / norm if norm else vec


@dataclass
class TitanEmbedder:
    """Titan Text Embeddings V2 via bedrock-runtime InvokeModel (one text per call)."""

    dimensions: int = DIMENSIONS
    model_id: str = TITAN_V2_MODEL_ID
    budget: EmbeddingBudget = field(default_factory=EmbeddingBudget)
    client: object | None = None

    def __post_init__(self) -> None:
        if self.dimensions not in TITAN_V2_DIMENSIONS:
            raise ValueError(f"Titan v2 supports {TITAN_V2_DIMENSIONS} dimensions")
        if self.client is None:
            import boto3
            from botocore.config import Config

            self.client = boto3.client("bedrock-runtime", config=Config(retries={"mode": "standard", "max_attempts": 4}))

    def embed(self, text: str) -> np.ndarray:
        self.budget.reserve(text)
        response = self.client.invoke_model(
            modelId=self.model_id, contentType="application/json", accept="application/json",
            body=json.dumps({"inputText": text, "dimensions": self.dimensions, "normalize": True}),
        )
        payload = json.loads(response["body"].read())
        self.budget.record(int(payload["inputTextTokenCount"]))
        vec = np.asarray(payload["embedding"], dtype=np.float32)
        if vec.shape != (self.dimensions,):
            raise ValueError(f"expected {self.dimensions} dims, got {vec.shape}")
        return vec
