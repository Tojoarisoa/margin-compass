"""Scenario difference v1 (calc-spec/README.md, ADR-016): signed after-minus-before changes. Integer arithmetic only.

M4-05 step 3c-3i: AG-05 wrote differences it computed itself ("a gain of 26911 cents"), which the verifier withheld
(AGENTS.md rule 3). price_plan v4 now returns them from this function. Synthetic inputs only.
"""

from __future__ import annotations

from typing import Any

FIELDS = ("revenue_cents", "margin_cents", "margin_bps", "adj_revenue_cents", "adj_margin_cents")


def scenario_delta(inp: dict[str, Any]) -> dict[str, int | None]:
    """`<field>_change = after[field] - before[field]` for every FIELDS key both sides carry (null if either is null)."""
    before, after = inp["before"], inp["after"]
    out: dict[str, int | None] = {}
    for f in FIELDS:
        if (f in before) != (f in after):
            raise ValueError(f"{f} must be given on both sides or neither")
        if f not in before:
            continue
        b, a = before[f], after[f]
        for v in (b, a):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                raise ValueError(f"{f} must be an integer or null")
        if (b is None or a is None) and f != "margin_bps":
            raise ValueError(f"{f} must be an integer")
        out[f"{f}_change"] = None if b is None or a is None else a - b
    if not out:
        raise ValueError(f"no comparable fields; expected some of {list(FIELDS)}")
    return out
