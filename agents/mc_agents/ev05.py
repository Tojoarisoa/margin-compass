"""EV-05 SQL generation score (PLAN.md §9): golden questions compared by execution result, gate >= 90%.

A candidate query passes when the rows it returns through the guarded `query_gold` tool equal the
reference rows: same values (numbers within a small tolerance), column names and, unless the question
is `ordered`, row order ignored. A candidate the guard rejects or that fails to run counts as a miss.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mc_agents.tools.metrics import ToolError

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "ev05.json"
GATE = 0.90
TOL = 1e-6


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text())["questions"]


def _norm(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    return str(v)


def rows_match(a: list[list[Any]], b: list[list[Any]], *, ordered: bool) -> bool:
    if len(a) != len(b):
        return False
    ra, rb = [[_norm(v) for v in r] for r in a], [[_norm(v) for v in r] for r in b]
    if not ordered:
        ra, rb = sorted(ra, key=repr), sorted(rb, key=repr)
    for x, y in zip(ra, rb, strict=True):
        if len(x) != len(y):
            return False
        for p, q in zip(x, y, strict=True):
            if isinstance(p, float) and isinstance(q, float):
                if not math.isclose(p, q, rel_tol=TOL, abs_tol=TOL):
                    return False
            elif p != q:
                return False
    return True


def score_one(query: Callable[[dict[str, Any]], dict[str, Any]], q: dict[str, Any], candidate_sql: str) -> bool:
    want = query({"sql": q["reference_sql"]})
    try:
        got = query({"sql": candidate_sql})
    except ToolError:
        return False
    return not got["truncated"] and rows_match(got["rows"], want["rows"], ordered=bool(q.get("ordered")))


def score(query: Callable[[dict[str, Any]], dict[str, Any]], generate: Callable[[str], str],
          questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`generate(question)` returns SQL (the model in production, a stub in tests)."""
    qs = questions if questions is not None else load_golden()
    results = {q["id"]: score_one(query, q, generate(q["question"])) for q in qs}
    rate = sum(results.values()) / len(results) if results else 0.0
    return {"ev05": rate, "passed": rate >= GATE, "results": results}


class _SqlCapture:
    """Wraps an LLM client and keeps the SQL of every `query_gold` call the model asks for."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.sql = inner, []

    def complete(self, request: Any) -> Any:
        resp = self.inner.complete(request)
        self.sql += [b["toolUse"].get("input", {}).get("sql", "") for b in resp.content
                     if "toolUse" in b and b["toolUse"]["name"] == "query_gold"]
        return resp


def specialist_generator(make_client: Callable[[str], Any], gold_dir: Path,
                         model_key: str = "haiku-4-5") -> Callable[[str], str]:
    """Live-model EV-05 generator: runs the AG-03 Cost-to-Serve specialist on the question with a recorded,
    replayed or scripted client and returns the SQL of its last `query_gold` call ("" when it made none,
    which scores as a miss). Budget and tool-round caps apply as in production."""
    from .budget import BudgetExceeded, QuestionBudget
    from .config import MODELS
    from .graph import GraphState
    from .llm import BudgetedLLM
    from .specialists import run_specialist
    from .tools import registry

    extra = {"query_gold": registry.query_gold_spec(gold_dir)}

    def generate(question: str) -> str:
        cap = _SqlCapture(make_client(question))
        state = GraphState(question, route="cost_to_serve")
        try:
            spec = MODELS[model_key]
            run_specialist(state, BudgetedLLM(cap, QuestionBudget(spec)), spec.target, extra)
        except BudgetExceeded:  # a capped run scores what it generated so far; fixture drift still raises
            pass
        return cap.sql[-1] if cap.sql else ""

    return generate


FIXTURES = GOLDEN.parent / "ev05_fixtures"


def run_model(gold_dir: Path, model_key: str, mode: str = "replay", fixtures_dir: Path = FIXTURES,
              live_client: Any = None, questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """EV-05 over the model's own SQL. replay: recorded fixtures ($0, CI); record: live Bedrock, writes
    one fixture per question; live: live Bedrock, nothing written."""
    from .config import MODELS
    from .llm import BedrockLLM, RecordingLLM, ReplayLLM
    from .specialists import PROMPT_VERSION
    from .tools.sql_guard import make_query_gold

    spec = MODELS[model_key]
    qs = questions if questions is not None else load_golden()
    ids = {q["question"]: q["id"] for q in qs}
    recorders: list[tuple[str, Any]] = []

    def make_client(question: str) -> Any:
        path = fixtures_dir / model_key / f"{ids[question]}.json"
        if mode == "replay":
            return ReplayLLM(path)
        if mode == "record":
            rec = RecordingLLM(live_client or BedrockLLM(), path)
            recorders.append((ids[question], rec))
            return rec
        return live_client or BedrockLLM()

    out = score(make_query_gold(gold_dir), specialist_generator(make_client, gold_dir, model_key), qs)
    for qid, rec in recorders:
        rec.save({"question_id": qid, "model_id": spec.target, "prompt_version": PROMPT_VERSION})
    return {**out, "model": spec.target, "mode": mode}
