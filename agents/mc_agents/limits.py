"""Tiering, rate limits, and shared $ caps (PLAN.md §8.7 levers 2 and 6). Pure code, no AWS."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from .budget import BudgetExceeded
from .config import MODELS, ModelSpec


def pick_model(tier: str, preferred: str | None = None) -> ModelSpec:
    """Cheapest model of the requested tier; `preferred` wins when it is of that tier."""
    if preferred and preferred in MODELS and MODELS[preferred].tier == tier:
        return MODELS[preferred]
    candidates = [m for m in MODELS.values() if m.tier == tier]
    if not candidates:
        raise ValueError(f"no model in tier {tier!r}")
    return min(candidates, key=lambda m: m.output_per_m)


class RateLimited(RuntimeError):
    """Too many calls in the window. Nothing was sent."""


@dataclass
class RateLimiter:
    """Sliding-window call limiter."""
    max_calls: int
    window_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _hits: list[float] = field(default_factory=list)

    def acquire(self) -> None:
        now = self.clock()
        self._hits = [t for t in self._hits if now - t < self.window_s]
        if len(self._hits) >= self.max_calls:
            raise RateLimited(f"rate limit of {self.max_calls} calls per {self.window_s:g}s reached")
        self._hits.append(now)


@dataclass
class SpendCaps:
    """In-process SpendGuard: a hard $ cap that includes in-flight worst cases."""
    max_usd: Decimal
    spent: Decimal = field(default_factory=lambda: Decimal(0))
    reserved: Decimal = field(default_factory=lambda: Decimal(0))

    def reserve(self, worst_usd: Decimal) -> None:
        if self.spent + self.reserved + worst_usd > self.max_usd:
            raise BudgetExceeded(f"spend cap reached (${self.max_usd})")
        self.reserved += worst_usd
        self._last = worst_usd

    def record(self, usd: Decimal) -> None:
        self.reserved = max(Decimal(0), self.reserved - getattr(self, "_last", Decimal(0)))
        self.spent += usd
