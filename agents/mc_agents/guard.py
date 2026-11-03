"""Public-API guardrails in DynamoDB (PLAN.md §11.3 guardrails 1-2), on the existing core table.

- SpendGuard: shared online LLM $ caps per UTC day and month, checked before every LLM call and
  incremented after it (atomic ADD). Amounts are stored in micro-dollars (integers).
- RateLimiter: per-client and global question quotas, atomic conditional increments.
Client addresses are never stored: only a salted SHA-256 prefix (the salt rotates daily).

Items (PK / SK): BUDGET#online / DAY#2026-11-04 | MONTH#2026-11; RATE#client#<hash> / HOUR#...;
RATE#global / DAY#...; JOB#<id> / JOB. All carry a `ttl`.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .budget import BudgetExceeded

MICRO = Decimal(1_000_000)


@dataclass(frozen=True)
class Caps:
    daily_usd: Decimal = Decimal("0.10")
    monthly_usd: Decimal = Decimal("1.50")      # PLAN.md §11.1: online LLM ≤ $1.50/month
    per_client_per_hour: int = 5
    per_client_per_day: int = 20
    global_per_day: int = 25


class RateLimited(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl(days: int) -> int:
    return int(time.time()) + days * 86_400


def _micros(usd: Decimal) -> int:
    return int((usd * MICRO).to_integral_value(rounding="ROUND_CEILING"))


class SpendGuard:
    def __init__(self, table: Any, caps: Caps = Caps(), pk: str = "BUDGET#online") -> None:
        self.table, self.caps, self.pk = table, caps, pk

    def _keys(self) -> list[tuple[str, Decimal]]:
        now = _now()
        return [(f"DAY#{now:%Y-%m-%d}", self.caps.daily_usd), (f"MONTH#{now:%Y-%m}", self.caps.monthly_usd)]

    def spent(self) -> dict[str, Decimal]:
        out = {}
        for sk, _ in self._keys():
            item = self.table.get_item(Key={"PK": self.pk, "SK": sk}, ConsistentRead=True).get("Item") or {}
            out[sk] = Decimal(int(item.get("usd_micros", 0))) / MICRO
        return out

    def reserve(self, worst_usd: Decimal) -> None:
        spent = self.spent()
        for sk, cap in self._keys():
            if spent[sk] + worst_usd > cap:
                raise BudgetExceeded(f"online LLM budget for {sk.split('#')[0].lower()} reached (${cap})")

    def headroom(self, needed: Decimal) -> bool:
        try:
            self.reserve(needed)
            return True
        except BudgetExceeded:
            return False

    def record(self, usd: Decimal) -> None:
        for sk, _ in self._keys():
            self.table.update_item(
                Key={"PK": self.pk, "SK": sk},
                UpdateExpression="ADD usd_micros :u, calls :one SET #ttl = if_not_exists(#ttl, :ttl)",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={":u": _micros(usd), ":one": 1, ":ttl": _ttl(400)},
            )


class RateLimiter:
    def __init__(self, table: Any, caps: Caps = Caps()) -> None:
        self.table, self.caps = table, caps

    @staticmethod
    def client_key(address: str) -> str:
        salt = f"{_now():%Y-%m-%d}"
        return hashlib.sha256(f"{salt}|{address}".encode()).hexdigest()[:20]

    def _hit(self, pk: str, sk: str, limit: int, ttl_days: int) -> None:
        from botocore.exceptions import ClientError

        try:
            self.table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="ADD n :one SET #ttl = if_not_exists(#ttl, :ttl)",
                ConditionExpression="attribute_not_exists(n) OR n < :limit",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={":one": 1, ":limit": limit, ":ttl": _ttl(ttl_days)},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise RateLimited(f"limit of {limit} reached") from None
            raise

    def admit(self, address: str) -> None:
        now, client = _now(), self.client_key(address or "unknown")
        self._hit("RATE#global", f"DAY#{now:%Y-%m-%d}", self.caps.global_per_day, 2)
        self._hit(f"RATE#client#{client}", f"DAY#{now:%Y-%m-%d}", self.caps.per_client_per_day, 2)
        self._hit(f"RATE#client#{client}", f"HOUR#{now:%Y-%m-%dT%H}", self.caps.per_client_per_hour, 1)
