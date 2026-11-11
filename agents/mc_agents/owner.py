"""Owner-only approval write path (M5-03 step 4, PLAN.md §8.4, §9.3).

  POST /api/approvals   header x-mc-owner-token: <Cognito access token>
                        {"action_id": "act-…", "action_type": "ACT-1|ACT-2|ACT-3", "target": "…",
                         "decision": "approved|rejected", "rationale": "…"}  -> 201 {"recorded": …}

Visitors keep the browser sandbox; only a signed-in member of the pool's `owner` group may write. The token is
checked by Cognito itself (`GetUser` validates signature, expiry and revocation; no extra crypto dependency), then
its claims must name this pool, this app client and the `owner` group. Cheap claim checks run first, so a missing or
foreign token is refused without a Cognito call or a table write. The Authorization header is taken by the
CloudFront OAC signature, hence the custom header.

Each decision is one item in the core table (ADR-011, no new table): PK `APPROVAL#<action_id>`, SK `DECIDED#<iso>`,
no TTL. The latest decision per action wins, which matches `booncore_sim.m5_effects.load_approvals`.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

OWNER_GROUP = "owner"
TOKEN_HEADER = "x-mc-owner-token"
ACTION_TYPES = ("ACT-1", "ACT-2", "ACT-3")
DECISIONS = ("approved", "rejected")
MAX_RATIONALE_CHARS = 500
_ACTION_ID = re.compile(r"^act-[0-9a-f]{12}$")
_SEG = r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}"
_TARGET = re.compile(rf"^{_SEG}(/{_SEG})?$")  # tenant, tenant/renewal, feature/metric, plan/x
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class Unauthorized(PermissionError):
    pass


def _claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise Unauthorized("malformed token")
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise Unauthorized("malformed token") from exc
    if not isinstance(claims, dict):
        raise Unauthorized("malformed token")
    return claims


def verify_owner(token: str | None, *, pool_id: str, client_id: str, region: str,
                 get_user: Callable[[str], dict[str, Any]], now: float) -> str:
    """Returns the owner's username, or raises Unauthorized."""
    if not token or not pool_id or not client_id:
        raise Unauthorized("owner sign-in required")
    c = _claims(token)
    if c.get("token_use") != "access":
        raise Unauthorized("access token required")
    if c.get("iss") != f"https://cognito-idp.{region}.amazonaws.com/{pool_id}" or c.get("client_id") != client_id:
        raise Unauthorized("token from another pool or client")
    if not isinstance(c.get("exp"), int | float) or c["exp"] <= now:
        raise Unauthorized("token expired")
    if OWNER_GROUP not in (c.get("cognito:groups") or []):
        raise Unauthorized("not an owner")
    try:
        user = get_user(token)  # Cognito validates signature, expiry and revocation
    except Exception as exc:  # noqa: BLE001 - any Cognito refusal is a 401
        raise Unauthorized("token rejected") from exc
    username = user.get("Username")
    if not username or username != c.get("username"):
        raise Unauthorized("token rejected")
    return username


def clean_decision(body: dict[str, Any]) -> dict[str, str]:
    action_id, action_type, target = body.get("action_id"), body.get("action_type"), body.get("target")
    decision, rationale = body.get("decision"), body.get("rationale", "")
    if not isinstance(action_id, str) or not _ACTION_ID.match(action_id):
        raise ValueError("action_id must look like act-<12 hex>")
    if action_type not in ACTION_TYPES:
        raise ValueError(f"action_type must be one of {', '.join(ACTION_TYPES)}")
    if not isinstance(target, str) or not _TARGET.match(target):
        raise ValueError("target is missing or invalid")
    if decision not in DECISIONS:
        raise ValueError("decision must be approved or rejected")
    if not isinstance(rationale, str):
        raise ValueError("rationale must be a string")
    rationale = _CONTROL.sub(" ", rationale).strip()
    if len(rationale) > MAX_RATIONALE_CHARS:
        raise ValueError(f"rationale is longer than {MAX_RATIONALE_CHARS} characters")
    return {"action_id": action_id, "action_type": action_type, "target": target, "decision": decision,
            "rationale": rationale}


def record(table: Any, decision: dict[str, str], approver: str, now: datetime) -> dict[str, str]:
    decided_at = now.astimezone(UTC).isoformat(timespec="seconds")
    item = {**decision, "approver": approver, "decided_at": decided_at}
    table.put_item(Item={"PK": f"APPROVAL#{decision['action_id']}", "SK": f"DECIDED#{decided_at}", **item})
    return item


def config() -> dict[str, str]:
    return {"pool_id": os.environ.get("OWNER_POOL_ID", ""), "client_id": os.environ.get("OWNER_CLIENT_ID", ""),
            "region": os.environ.get("AWS_REGION", "us-east-1")}


def export_approvals(table: Any) -> list[dict[str, str]]:
    """Recorded decisions in `booncore_sim.m5_effects.load_approvals` format, latest per action, sorted by action id.

    One paginated Scan filtered on the `APPROVAL#` prefix (the core table holds a few hundred items; no index needed).
    """
    from boto3.dynamodb.conditions import Attr

    latest: dict[str, dict[str, Any]] = {}
    kwargs: dict[str, Any] = {"FilterExpression": Attr("PK").begins_with("APPROVAL#")}
    while True:
        page = table.scan(**kwargs)
        for item in page.get("Items", []):
            cur = latest.get(item["action_id"])
            if cur is None or item["SK"] > cur["SK"]:
                latest[item["action_id"]] = item
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    keys = ("action_id", "action_type", "target", "decision", "approver", "rationale", "decided_at")
    return [{k: str(latest[a].get(k, "")) for k in keys} for a in sorted(latest)]


def to_jsonl(rows: list[dict[str, str]]) -> str:
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
