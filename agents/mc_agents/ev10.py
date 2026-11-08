"""EV-10 efficiency score (PLAN.md §9): mean dollars per answered query <= $0.01 and p95 latency <= 20 s.

Input is one sample per query (cost in USD, wall-clock seconds), for example from a recorded run's
cost lines. An empty sample set fails closed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

MAX_COST_USD = 0.01
MAX_P95_SECONDS = 20.0


def p95(values: Sequence[float]) -> float:
    """Nearest-rank 95th percentile."""
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def score(samples: Sequence[tuple[float, float]]) -> dict[str, Any]:
    if not samples:
        return {"n": 0, "passed": False, "reason": "no samples"}
    costs = [c for c, _ in samples]
    lat = [t for _, t in samples]
    mean_cost = sum(costs) / len(costs)
    p95_latency = p95(lat)
    return {
        "n": len(samples),
        "mean_cost_usd": round(mean_cost, 6),
        "p95_latency_s": round(p95_latency, 3),
        "passed": mean_cost <= MAX_COST_USD and p95_latency <= MAX_P95_SECONDS,
    }
