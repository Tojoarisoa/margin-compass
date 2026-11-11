"""Evidence ledger and the deterministic numeric verifier (PLAN.md §8.6 ledger rule, EV-08).

Rule: if a number is not in the ledger, it cannot appear in the answer. Every money amount,
percentage, decimal, or thousands-separated figure in the answer must equal a value from a tool
result. Bare integers must also come from the ledger or the question. Dates, tenant IDs, and
evidence references are not figures and are removed before the check.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

_MONTHS = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_NOT_FIGURES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                          # ISO dates
    re.compile(r"\bbc-t\d{4}\b"),                                  # tenant IDs
    re.compile(r"\[E\d+\]"),                                       # evidence references
    re.compile(r"\bKPI-\d+\b|\bF\d\b|\bAG-\d+\b|\bEV-\d+\b"),       # catalog IDs
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?(?:,?\s+\d{{4}})?\b"),  # September 1(-30)(, 2025)
    re.compile(rf"\b{_MONTHS}\.?\s+\d{{4}}\b"),                    # September 2025
    re.compile(r"\b(?:Haiku|Sonnet|Nova)\s+\d+(?:\.\d+)?\b"),      # model names
]
_FIGURE = re.compile(r"-?\$?-?\d[\d,]*(?:\.\d+)?%?")
_MINUS = str.maketrans({"\u2212": "-"})  # Unicode minus sign: read as a sign, so the sign is checked too


def _norm(token: str) -> Decimal | None:
    t = token.replace("$", "").replace(",", "").replace("%", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _leaves(obj: Any):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)
    elif isinstance(obj, (int, float, str, Decimal)) and not isinstance(obj, bool):
        yield obj


@dataclass
class Evidence:
    id: str
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    sha: str


@dataclass
class Ledger:
    entries: list[Evidence] = field(default_factory=list)

    def add(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> Evidence:
        body = json.dumps({"tool": tool, "args": args, "result": result}, sort_keys=True, default=str)
        ev = Evidence(f"E{len(self.entries) + 1}", tool, args, result, hashlib.sha256(body.encode()).hexdigest()[:16])
        self.entries.append(ev)
        return ev

    def values(self) -> set[Decimal]:
        out: set[Decimal] = set()
        for e in self.entries:
            for leaf in list(_leaves(e.result)) + list(_leaves(e.args)):
                for tok in _FIGURE.findall(str(leaf).translate(_MINUS)):
                    if (d := _norm(tok)) is not None:
                        out.add(d)
        return out


@dataclass(frozen=True)
class Verification:
    ok: bool
    unsupported: list[str]
    checked: int
    cited: bool


def verify_answer(answer: str, ledger: Ledger, question: str) -> Verification:
    text = answer.translate(_MINUS)
    for pat in _NOT_FIGURES:
        text = pat.sub(" ", text)
    allowed = ledger.values()
    q_ints = {d for tok in _FIGURE.findall(question.translate(_MINUS)) if (d := _norm(tok)) is not None}
    unsupported, checked = [], 0
    for tok in _FIGURE.findall(text):
        d = _norm(tok)
        if d is None:
            continue
        checked += 1
        is_figure = any(c in tok for c in "$%,.")
        if d in allowed or (not is_figure and d in q_ints):
            continue
        unsupported.append(tok)
    cited = any(f"[{e.id}]" in answer for e in ledger.entries)
    return Verification(ok=not unsupported and (cited or not ledger.entries), unsupported=unsupported,
                        checked=checked, cited=cited)
