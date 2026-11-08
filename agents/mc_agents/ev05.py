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
