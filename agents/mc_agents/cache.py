"""Exact answer cache (M4-04, PLAN.md §8).

Only `verified` answers are cached (a withheld, blocked or approval-gated result never is). The key is
tenant + normalised question + data version, so a new gold build or another tenant never hits an old entry.
A hit is labelled `cached` with its age, so the console shows the answer is not freshly computed. Entries
expire after `ttl_s`. The store is dict-like (DynamoDB core table with ttl later); no prompt text is logged.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from typing import Any

from .approvals import Store


def cache_key(tenant: str, question: str, data_version: str) -> str:
    q = re.sub(r"\s+", " ", question.strip().lower())
    return "ans#" + hashlib.sha256(f"{tenant}\x1f{data_version}\x1f{q}".encode()).hexdigest()


def lookup(store: Store, tenant: str, question: str, data_version: str, *, ttl_s: float = 3600,
           clock: Callable[[], float] = time.time) -> dict[str, Any] | None:
    rec = store.get(cache_key(tenant, question, data_version))
    if not rec:
        return None
    age = clock() - float(rec["at"])
    if age < 0 or age > ttl_s:
        return None
    return {**rec["out"], "degradation": "cached", "cache_age_s": int(age),
            "cost_line": "Cost of this answer: $0.0000 (served from cache, no LLM call)."}


def store_answer(store: Store, tenant: str, question: str, data_version: str, out: dict[str, Any], *,
                 clock: Callable[[], float] = time.time) -> bool:
    if out.get("status") != "verified":
        return False
    store.put(cache_key(tenant, question, data_version), {"at": clock(), "out": dict(out)})
    return True
