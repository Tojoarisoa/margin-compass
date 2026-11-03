"""LLM provider abstraction (ADR-003, ADR-014).

- BedrockLLM: Bedrock Converse API (live).
- RecordingLLM: wraps a live client and stores each request hash + response as a replay fixture.
- ReplayLLM: serves recorded responses; a request whose hash differs from the recording fails with
  FixtureDrift (re-record when a prompt, tool schema, graph, or model changes). CI uses only this.
- BudgetedLLM: the only way the graph reaches a model. It checks the per-question budget before each
  call and logs OTel GenAI attributes (ADR-015) without prompt or response content (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from .budget import QuestionBudget
from .config import MAX_OUTPUT_TOKENS_PER_CALL

log = logging.getLogger("mc_agents")


@dataclass(frozen=True)
class LLMRequest:
    model_id: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_tokens: int = MAX_OUTPUT_TOKENS_PER_CALL

    def to_converse(self) -> dict[str, Any]:
        req: dict[str, Any] = {
            "modelId": self.model_id,
            "system": [{"text": self.system}],
            "messages": self.messages,
            "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": 0},
        }
        if self.tools:
            req["toolConfig"] = {"tools": self.tools}
        return req

    def canonical(self) -> str:
        return json.dumps(self.to_converse(), sort_keys=True, separators=(",", ":"), default=str)

    def sha(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


@dataclass(frozen=True)
class LLMResponse:
    content: list[dict[str, Any]]  # Converse content blocks: {"text": ...} or {"toolUse": {...}}
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        return {"content": self.content, "stop_reason": self.stop_reason, "usage": {
            "inputTokens": self.input_tokens, "outputTokens": self.output_tokens,
            "cacheReadInputTokens": self.cache_read_tokens}}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> LLMResponse:
        u = d["usage"]
        return cls(d["content"], d["stop_reason"], int(u["inputTokens"]), int(u["outputTokens"]),
                   int(u.get("cacheReadInputTokens") or 0))


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class BedrockLLM:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client("bedrock-runtime", config=Config(retries={"mode": "standard", "max_attempts": 3},
                                                                   read_timeout=60))
        self.client = client

    def complete(self, request: LLMRequest) -> LLMResponse:
        resp = self.client.converse(**request.to_converse())
        usage = resp.get("usage", {})
        return LLMResponse(resp["output"]["message"]["content"], resp.get("stopReason", ""),
                           int(usage.get("inputTokens", 0)), int(usage.get("outputTokens", 0)),
                           int(usage.get("cacheReadInputTokens") or 0))


class FixtureDrift(RuntimeError):
    """The request differs from the recorded one: re-record the fixtures."""


@dataclass
class ReplayLLM:
    path: Path
    _calls: list[dict[str, Any]] = field(default_factory=list)
    _i: int = 0

    def __post_init__(self) -> None:
        if not Path(self.path).exists():
            raise FixtureDrift(f"no fixture at {self.path}; record it with: mc-agents eval --mode record")
        self._calls = json.loads(Path(self.path).read_text())["calls"]

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self._i >= len(self._calls):
            raise FixtureDrift(f"{self.path}: more calls than recorded ({len(self._calls)})")
        rec = self._calls[self._i]
        self._i += 1
        if rec["request_sha"] != request.sha():
            raise FixtureDrift(f"{self.path}: call {self._i} request changed since recording; re-record")
        return LLMResponse.from_json(rec["response"])


@dataclass
class RecordingLLM:
    inner: LLMClient
    path: Path
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, request: LLMRequest) -> LLMResponse:
        resp = self.inner.complete(request)
        self.calls.append({"request_sha": request.sha(), "response": resp.to_json()})
        return resp

    def save(self, meta: dict[str, Any]) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(json.dumps({**meta, "calls": self.calls}, indent=2, sort_keys=True) + "\n")


class SpendGuard(Protocol):
    """Shared daily/monthly $ caps (the DynamoDB counter in AWS, PLAN.md §11.3 guardrail 1)."""

    def reserve(self, worst_usd: Decimal) -> None: ...
    def record(self, usd: Decimal) -> None: ...


@dataclass
class BudgetedLLM:
    inner: LLMClient
    budget: QuestionBudget
    spend: SpendGuard | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        worst = self.budget.reserve(request.canonical())  # raises BudgetExceeded before any call
        if self.spend is not None:
            self.spend.reserve(worst)  # shared caps, also before the call
        start = time.monotonic()
        resp = self.inner.complete(request)
        cost = self.budget.record(resp.input_tokens, resp.output_tokens, resp.cache_read_tokens)
        if self.spend is not None:
            self.spend.record(cost)
        log.info("gen_ai_call", extra={"fields": {  # OTel GenAI attribute names (ADR-015); no content
            "gen_ai.operation.name": "chat", "gen_ai.provider.name": "aws.bedrock",
            "gen_ai.request.model": request.model_id, "gen_ai.request.max_tokens": request.max_tokens,
            "gen_ai.usage.input_tokens": resp.input_tokens, "gen_ai.usage.output_tokens": resp.output_tokens,
            "gen_ai.response.finish_reasons": [resp.stop_reason], "mc.cost_usd": str(cost),
            "mc.latency_ms": int((time.monotonic() - start) * 1000)}})
        return resp
