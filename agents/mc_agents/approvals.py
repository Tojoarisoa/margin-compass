"""AG-09 Human approval (M4-03 step 3, PLAN.md §8.3-8.4): a pending-approval store with role checks.

Agents only draft; a person with sufficient authority approves. `request` persists a pending item for the role
`graph.verify` chose, `decide` resumes it. A decision by a lower role fails closed. The store takes any
object with `get(key)` / `put(key, item)` (dict-like), so DynamoDB can back it later.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

ROLE_ORDER = ["account_manager", "revops_lead", "head_of_revenue", "finance_and_ceo"]


class Store(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...
    def put(self, key: str, item: dict[str, Any]) -> None: ...


@dataclass
class MemoryStore:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, key: str) -> dict[str, Any] | None:
        return self.items.get(key)

    def put(self, key: str, item: dict[str, Any]) -> None:
        self.items[key] = item


class NotAuthorized(PermissionError):
    pass


@dataclass(frozen=True)
class Approval:
    id: str
    question: str
    actions: list[dict[str, Any]]
    required_role: str
    status: str = "pending"  # pending | approved | rejected
    decided_by: str | None = None


def request(store: Store, approval_id: str, question: str, actions: list[dict[str, Any]], required_role: str) -> Approval:
    if required_role not in ROLE_ORDER:
        raise ValueError(f"unknown role: {required_role}")
    if not actions:
        raise ValueError("nothing to approve")
    if store.get(approval_id) is not None:
        raise ValueError("approval id already exists")
    ap = Approval(approval_id, question, actions, required_role)
    store.put(approval_id, asdict(ap))
    return ap


def decide(store: Store, approval_id: str, role: str, approve: bool) -> Approval:
    item = store.get(approval_id)
    if item is None:
        raise KeyError(approval_id)
    ap = Approval(**item)
    if ap.status != "pending":
        raise ValueError(f"already {ap.status}")
    if role not in ROLE_ORDER or ROLE_ORDER.index(role) < ROLE_ORDER.index(ap.required_role):
        raise NotAuthorized(f"{role} may not decide an item needing {ap.required_role}")
    done = Approval(ap.id, ap.question, ap.actions, ap.required_role, "approved" if approve else "rejected", role)
    store.put(approval_id, asdict(done))
    return done


class DynamoStore:
    """Store backed by the core state table (PK = key, SK = `item`); the item is kept as one JSON string.

    Items expire through the table's `ttl` attribute (default 30 days), so no cleanup job is needed.
    """

    def __init__(self, table: Any, ttl_seconds: int = 30 * 86400, now: Any = None) -> None:
        self.table, self.ttl_seconds = table, ttl_seconds
        self._now = now or time.time

    def get(self, key: str) -> dict[str, Any] | None:
        got = self.table.get_item(Key={"PK": key, "SK": "item"}, ConsistentRead=True).get("Item")
        return None if got is None else json.loads(got["data"])

    def put(self, key: str, item: dict[str, Any]) -> None:
        self.table.put_item(Item={"PK": key, "SK": "item", "data": json.dumps(item),
                                  "ttl": int(self._now()) + self.ttl_seconds})
