"""Agent API (M1-07): Lambda function URL behind CloudFront OAC (ADR-012), polling flow.

  POST /api/ask         {"question": "..."}  -> 202 {"job_id": ...}   (rate-limited, budget-checked)
  GET  /api/jobs/<id>                        -> {"status": "pending|running|answered|...", ...}
  GET  /api/health                           -> {"ok": true, ...}
  POST /api/approvals   (owner only, M5-03)  -> 201 {"recorded": ...}   see mc_agents.owner

The POST starts the job and invokes this same function asynchronously ({"mc_job": id}); the worker
runs the Cost-to-Serve Analyst and stores the result (TTL 1 day). Streaming is the M1-07 spike.

Environment: LAKE_BUCKET (gold source), STATE_TABLE (core table), MC_ENV, OWNER_POOL_ID, OWNER_CLIENT_ID.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import cache, owner
from .analyst import PROMPT_VERSION, answer_question
from .approvals import DynamoStore
from .budget import BudgetExceeded
from .config import DEFAULT_ANALYST_MODEL, MAX_USD_PER_QUESTION, MODELS
from .guard import RateLimited, RateLimiter, SpendGuard
from .llm import BedrockLLM

log = logging.getLogger("mc_agents")
GOLD_DIR = Path("/tmp/gold")
GOLD_FILES = ("fct_tenant_margin.parquet",)
MAX_QUESTION_CHARS = 300
MAX_BODY_BYTES = 2_048
CACHE_TTL_S = 3_600
_CACHED_KEYS = ("status", "answer", "cost_line", "model", "evidence", "verification", "degradation")
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_gold_etags: dict[str, str] = {}
_clients: dict[str, Any] = {}


def _client(name: str):
    if name not in _clients:
        import boto3

        _clients[name] = boto3.client(name) if name != "dynamodb" else boto3.resource("dynamodb")
    return _clients[name]


def _table():
    return _client("dynamodb").Table(os.environ["STATE_TABLE"])


def _resp(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=str)}


def sync_gold(bucket: str, dest: Path = GOLD_DIR) -> None:
    """Fetch the gold files the tools read; re-download only when the object changed."""
    s3 = _client("s3")
    dest.mkdir(parents=True, exist_ok=True)
    for name in GOLD_FILES:
        _sync_one(s3, bucket, name, dest)
    # M2 marts sit beside the M1 file once the backfill has built them; absent marts are skipped so the
    # analyst keeps the M1 tool set (the `kpi` tool needs every registry mart, see tools/m2.py).
    for name in _m2_files():
        try:
            _sync_one(s3, bucket, name, dest)
        except Exception as exc:  # noqa: BLE001 - a missing optional object must not fail the question
            if getattr(exc, "response", {}).get("Error", {}).get("Code") not in ("404", "403", "NoSuchKey", "NotFound", "AccessDenied"):
                raise
            (dest / name).unlink(missing_ok=True)
            _gold_etags.pop(f"gold/{name}", None)


def _sync_one(s3, bucket: str, name: str, dest: Path) -> None:
    key = f"gold/{name}"
    etag = s3.head_object(Bucket=bucket, Key=key)["ETag"]
    if _gold_etags.get(key) != etag or not (dest / name).exists():
        s3.download_file(bucket, key, str(dest / name))
        _gold_etags[key] = etag


def _m2_files() -> tuple[str, ...]:
    try:
        from mc_pipelines import metrics as registry
    except ImportError:
        return ()
    return tuple(sorted({f"{m['source']}.parquet" for m in registry.load().values()}))


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", errors="strict")
    if len(raw.encode()) > MAX_BODY_BYTES:
        raise ValueError("request body too large")
    data = json.loads(raw or "{}")
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def _clean_question(q: Any) -> str:
    if not isinstance(q, str):
        raise ValueError("question must be a string")
    q = _CONTROL.sub(" ", q).strip()
    if not q:
        raise ValueError("question is empty")
    if len(q) > MAX_QUESTION_CHARS:
        raise ValueError(f"question is longer than {MAX_QUESTION_CHARS} characters")
    return q


def _client_address(event: dict[str, Any]) -> str:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    viewer = headers.get("cloudfront-viewer-address", "")
    return viewer.rsplit(":", 1)[0] if viewer else event.get("requestContext", {}).get("http", {}).get("sourceIp", "")


def handle_ask(event: dict[str, Any], context: Any, *, table=None, invoke=None) -> dict[str, Any]:
    try:
        question = _clean_question(_parse_body(event).get("question"))
    except (ValueError, json.JSONDecodeError) as exc:
        return _resp(400, {"error": str(exc)})
    table = table or _table()
    spend = SpendGuard(table)
    if not spend.headroom(MAX_USD_PER_QUESTION):
        return _resp(503, {"error": "The analyst is unavailable right now. Please try again later.", "code": "budget"})
    try:
        RateLimiter(table).admit(_client_address(event))
    except RateLimited:
        return _resp(429, {"error": "Too many questions. Please wait a while.", "code": "rate_limited"})
    job_id = uuid.uuid4().hex
    table.put_item(Item={"PK": f"JOB#{job_id}", "SK": "JOB", "status": "pending", "question": question,
                         "created_at": int(time.time()), "ttl": int(time.time()) + 86_400})
    (invoke or _invoke_self)(context, job_id)
    log.info("job_started", extra={"fields": {"job_id": job_id}})
    return _resp(202, {"job_id": job_id, "poll": f"/api/jobs/{job_id}"})


def handle_approval(event: dict[str, Any], *, table=None, get_user=None, now: datetime | None = None) -> dict[str, Any]:
    """Owner-only: records one decision on a proposed action. Everyone else gets 401 and nothing is written."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    now = now or datetime.now(UTC)
    try:
        approver = owner.verify_owner(headers.get(owner.TOKEN_HEADER), **owner.config(),
                                      get_user=get_user or _cognito_get_user, now=now.timestamp())
    except owner.Unauthorized as exc:
        log.info("approval_refused", extra={"fields": {"reason": str(exc)}})
        return _resp(401, {"error": "Owner sign-in required.", "code": "unauthorized"})
    try:
        decision = owner.clean_decision(_parse_body(event))
    except (ValueError, json.JSONDecodeError) as exc:
        return _resp(400, {"error": str(exc)})
    item = owner.record(table or _table(), decision, approver, now)
    log.info("approval_recorded", extra={"fields": {"action_id": item["action_id"], "decision": item["decision"]}})
    return _resp(201, {"recorded": item})


def _cognito_get_user(token: str) -> dict[str, Any]:
    return _client("cognito-idp").get_user(AccessToken=token)


def _invoke_self(context: Any, job_id: str) -> None:
    _client("lambda").invoke(FunctionName=context.invoked_function_arn, InvocationType="Event",
                             Payload=json.dumps({"mc_job": job_id}).encode())


def handle_job(path: str, *, table=None) -> dict[str, Any]:
    job_id = path.rsplit("/", 1)[-1]
    if not _JOB_ID.match(job_id):
        return _resp(404, {"error": "not found"})
    item = (table or _table()).get_item(Key={"PK": f"JOB#{job_id}", "SK": "JOB"}).get("Item")
    if not item:
        return _resp(404, {"error": "not found"})
    # Public response: cost, call count and model stay in the job record (ledger), not on the public API.
    keys = ("status", "question", "answer", "evidence", "verification", "degradation", "trail", "approver")
    return _resp(200, {"job_id": job_id, **{k: item[k] for k in keys if k in item}})


_GRAPH_STATUS = {"verified": "answered", "needs_approval": "needs_approval", "unverified": "unverified", "blocked": "blocked"}


def _graph_enabled() -> bool:
    return os.environ.get("MC_GRAPH", "") == "1"  # default off: the one-node analyst serves the API


def _answer_graph(job_id: str, question: str, table, gold_dir: Path, client) -> dict[str, Any]:
    """Serves one question through the M4-03 graph (`run.ask`); fail-closed statuses map to job statuses."""
    from . import run as graph_run
    from .budget import QuestionBudget
    from .llm import BudgetedLLM
    from .responder import cost_line
    from .tools import registry

    model_key = os.environ.get("MC_MODEL", DEFAULT_ANALYST_MODEL)
    spec, budget = MODELS[model_key], QuestionBudget(MODELS[model_key])
    llm = BudgetedLLM(client, budget, SpendGuard(table))
    store = DynamoStore(table, 86_400)
    extra = {"query_gold": registry.query_gold_spec(gold_dir)}
    out = graph_run.ask(question, llm, spec.target, run_id=job_id, approval_store=store, checkpoints=store, extra=extra)
    trail = (store.get(f"run#{job_id}") or {}).get("trail", [])
    evidence = [{"id": e["id"], "tool": e["tool"], "version": e["version"], "args": e["args"]} for e in out["evidence"]]
    update = {"status": _GRAPH_STATUS.get(out["status"], "error"), "answer": out["answer"],
              "cost_line": cost_line(budget.usd, budget.calls, spec.label), "llm_calls": budget.calls,
              "model": spec.label, "cost_usd": str(budget.usd),
              "evidence": json.loads(json.dumps(evidence, default=str)),
              "trail": [{"node": t["node"], "status": t["status"]} for t in trail]}  # node and status only
    if out["status"] == "needs_approval" or "approval_id" in out:
        update["approver"] = out.get("approver") or ""
    return update


def run_job(job_id: str, *, table=None, gold_dir: Path = GOLD_DIR, client=None, sync=True) -> str:
    table = table or _table()
    key = {"PK": f"JOB#{job_id}", "SK": "JOB"}
    item = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not item or item.get("status") != "pending":
        return "skipped"  # async retries or duplicates never re-spend
    table.update_item(Key=key, UpdateExpression="SET #s = :r", ConditionExpression="#s = :p",
                      ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":r": "running", ":p": "pending"})
    try:
        if sync:
            sync_gold(os.environ["LAKE_BUCKET"], gold_dir)
        store, version = DynamoStore(table, CACHE_TTL_S), "|".join(f"{k}={v}" for k, v in sorted(_gold_etags.items()))
        if _graph_enabled():
            return _finish(table, key, job_id, _answer_graph(job_id, item["question"], table, gold_dir, client or BedrockLLM()))
        hit = cache.lookup(store, "public", item["question"], version, ttl_s=CACHE_TTL_S)
        if hit is not None:  # an identical verified answer on the same gold data: no model call, no spend
            update = {k: hit[k] for k in _CACHED_KEYS if k in hit} | {"llm_calls": 0, "cost_usd": "0"}
            return _finish(table, key, job_id, update)
        res = answer_question(item["question"], gold_dir=gold_dir, client=client or BedrockLLM(),
                              model_key=os.environ.get("MC_MODEL", DEFAULT_ANALYST_MODEL), spend=SpendGuard(table))
        evidence = [{"id": e["id"], "tool": e["tool"], "args": e["args"], "result": e["result"]} for e in res.evidence]
        update = {"status": res.status, "answer": res.answer, "cost_line": res.cost_line, "llm_calls": res.llm_calls,
                  "model": MODELS[os.environ.get("MC_MODEL", DEFAULT_ANALYST_MODEL)].label,
                  "evidence": json.loads(json.dumps(evidence, default=str)), "cost_usd": str(res.cost_usd),
                  "verification": json.loads(json.dumps(res.verification, default=str))}
        cache.store_answer(store, "public", item["question"], version, update)
    except BudgetExceeded as exc:
        update = {"status": "budget_exceeded", "answer": "The analyst is unavailable right now. Please try again later.", "error": str(exc)[:200]}
    except Exception as exc:  # noqa: BLE001 - the job must end in a terminal state
        log.error("job_failed", extra={"fields": {"job_id": job_id, "error": type(exc).__name__}})
        update = {"status": "error", "answer": "Something went wrong while answering.", "error": type(exc).__name__}
    return _finish(table, key, job_id, update)


def _finish(table, key: dict[str, str], job_id: str, update: dict[str, Any]) -> str:
    names = {f"#{k}": k for k in update}
    table.update_item(Key=key, UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in update),
                      ExpressionAttributeNames=names, ExpressionAttributeValues={f":{k}": v for k, v in update.items()})
    log.info("job_finished", extra={"fields": {"job_id": job_id, "status": update["status"], "prompt_version": PROMPT_VERSION}})
    return update["status"]


def _configure_logging() -> None:
    class Json(logging.Formatter):
        def format(self, record):
            return json.dumps({"level": record.levelname, "event": record.getMessage(), **getattr(record, "fields", {})}, default=str)

    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(Json())
    log.handlers[:] = [h]
    log.setLevel(logging.INFO)
    log.propagate = False


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    _configure_logging()
    if "mc_job" in event:
        return {"status": run_job(str(event["mc_job"]))}
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", ""), event.get("rawPath", "")
    if method == "POST" and path == "/api/ask":
        return handle_ask(event, context)
    if method == "GET" and path.startswith("/api/jobs/"):
        return handle_job(path)
    if method == "POST" and path == "/api/approvals":
        return handle_approval(event)
    if method == "GET" and path == "/api/health":
        return _resp(200, {"ok": True})  # no model, caps or environment on the public API
    return _resp(404, {"error": "not found"})
