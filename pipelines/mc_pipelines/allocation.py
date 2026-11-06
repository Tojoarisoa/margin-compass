"""Loads and checks `reference/allocation_rules.yml` for the M2 allocation model (m2-plan.md M2-02.2)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

RULES_PATH = Path(os.environ["MC_REFERENCE_DIR"]) / "allocation_rules.yml" if os.environ.get("MC_REFERENCE_DIR") else Path(__file__).resolve().parents[2] / "reference" / "allocation_rules.yml"
DRIVERS = ("requests", "tokens", "cumulative_input_tokens")


def load_rules(path: Path = RULES_PATH) -> dict:
    """Rules as a dbt var. Dates are kept as ISO strings."""
    raw = yaml.safe_load(path.read_text())
    seen: set[tuple[str, str, str]] = set()
    for r in raw["rules"]:
        if r["driver"] not in DRIVERS:
            raise ValueError(f"{r['rule_id']}: unknown driver {r['driver']!r}")
        r["effective_from"] = str(r["effective_from"])
        r["effective_to"] = str(r["effective_to"]) if r.get("effective_to") else None
        key = (r["match"]["service_name"], r["match"]["env"], r["effective_from"])
        if key in seen:
            raise ValueError(f"{r['rule_id']}: duplicate rule version for {key}")
        seen.add(key)
    return raw
