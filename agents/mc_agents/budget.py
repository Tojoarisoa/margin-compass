"""Per-question LLM budget, checked *before* every call (AGENTS.md rule 6)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from .config import (MAX_INPUT_TOKENS_PER_CALL, MAX_LLM_CALLS_PER_QUESTION, MAX_OUTPUT_TOKENS_PER_CALL,
                     MAX_USD_PER_QUESTION, ModelSpec)

MILLION = Decimal(1_000_000)


class BudgetExceeded(RuntimeError):
    """The next call could break a cap. Nothing was sent."""


def call_cost(spec: ModelSpec, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> Decimal:
    return (Decimal(input_tokens) * spec.input_per_m + Decimal(output_tokens) * spec.output_per_m
            + Decimal(cache_read_tokens) * spec.cache_read_per_m) / MILLION


@dataclass
class QuestionBudget:
    spec: ModelSpec
    max_calls: int = MAX_LLM_CALLS_PER_QUESTION
    max_usd: Decimal = MAX_USD_PER_QUESTION
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    usd: Decimal = field(default_factory=lambda: Decimal(0))

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, math.ceil(len(text) / 3))  # conservative: ~3 characters per token

    def reserve(self, request_text: str) -> Decimal:
        """Raise BudgetExceeded if the next call could break a cap; return its worst-case cost."""
        est_in = self.estimate_tokens(request_text)
        if est_in > MAX_INPUT_TOKENS_PER_CALL:
            raise BudgetExceeded(f"request of ~{est_in} tokens exceeds the {MAX_INPUT_TOKENS_PER_CALL}-token ceiling")
        if self.calls + 1 > self.max_calls:
            raise BudgetExceeded(f"LLM call cap reached ({self.max_calls} per question)")
        worst = call_cost(self.spec, est_in, MAX_OUTPUT_TOKENS_PER_CALL)
        if self.usd + worst > self.max_usd:
            raise BudgetExceeded(f"question cost cap reached (${self.max_usd})")
        return worst

    def record(self, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> Decimal:
        cost = call_cost(self.spec, input_tokens, output_tokens, cache_read_tokens)
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read_tokens
        self.usd += cost
        return cost
