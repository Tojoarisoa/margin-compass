"""AG-01 Intake & Guardrails, deterministic part (M4-03 step 1, PLAN.md §8.3, ADR-013, EV-09).

`screen` decides, with rules only (no LLM call), whether a question is in scope and free of injection,
and extracts entities (tenant ids, months, ISO dates). `inconclusive` means the supervisor may spend one
Small-tier call to classify; the rules never let a blocked question through. Rules only ever tighten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_QUESTION_CHARS = 1000
_TENANT = re.compile(r"\bbc-t\d{4}\b", re.I)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH = re.compile(r"\b\d{4}-(?:0[1-9]|1[0-2])\b(?!-)")

_INJECTION = re.compile(
    r"ignore (?:all |any |the |your )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)"
    r"|disregard (?:all |any |the |your )?(?:previous|prior|above|earlier|system)"
    r"|(?:reveal|print|show|repeat|leak) (?:me )?(?:your |the )?(?:system|hidden|developer) (?:prompt|instructions|message)"
    r"|you are now |act as (?:an? )?(?:admin|root|developer)|developer mode|jailbreak"
    r"|override (?:the )?(?:guardrails?|safety|budget|limits?|approval)",
    re.I,
)
_AUTHORITY_BYPASS = re.compile(
    r"(?:skip|bypass|without|no need for|waive) (?:the )?(?:human )?(?:approval|authority|sign-?off|guardrails?)"
    r"|approve (?:it |this )?(?:yourself|automatically)|pre-?approved by",
    re.I,
)
_SQL_ATTACK = re.compile(r"\b(?:drop|delete|truncate|alter|insert|update)\s+(?:table|from|into)\b|;\s*--|\bunion\s+select\b", re.I)
_SECRETS = re.compile(r"\b(?:api[ _-]?key|access[ _-]?key|secret|password|credentials?|token)s?\b", re.I)
_DOMAIN = re.compile(
    r"margin|cost|price|pricing|plan|revenue|tenant|churn|discount|contract|clause|renewal|policy|model|token|cache|"
    r"routing|lever|quality|roi|payback|forecast|leak|feature|usage|outcome|resolution|cogs|spend|bill|sla|baa|residency",
    re.I,
)


@dataclass(frozen=True)
class Intake:
    verdict: str  # "allow" | "block" | "inconclusive"
    category: str  # "ok" | "injection" | "authority_bypass" | "sql_attack" | "secrets" | "too_long" | "empty" | "out_of_scope"
    tenants: list[str] = field(default_factory=list)
    months: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


def screen(question: object) -> Intake:
    if not isinstance(question, str) or not question.strip():
        return Intake("block", "empty")
    if len(question) > MAX_QUESTION_CHARS:
        return Intake("block", "too_long")
    for rx, cat in ((_INJECTION, "injection"), (_AUTHORITY_BYPASS, "authority_bypass"),
                    (_SQL_ATTACK, "sql_attack"), (_SECRETS, "secrets")):
        if rx.search(question):
            return Intake("block", cat)
    tenants = sorted({t.lower() for t in _TENANT.findall(question)})
    dates = sorted(set(_ISO_DATE.findall(question)))
    months = sorted(set(_MONTH.findall(question)))
    if not (_DOMAIN.search(question) or tenants):
        return Intake("inconclusive", "out_of_scope", tenants, months, dates)
    return Intake("allow", "ok", tenants, months, dates)
