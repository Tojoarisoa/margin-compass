"""M6-02 step 2: online evaluation sampling (PLAN.md §13.2, "Online (nightly)": sampled, live, within budget).

Each day a small, deterministic sample of the golden graph scenarios (the ones with recorded graph fixtures) runs
live through the real graph, and is compared with the recorded replay of the same scenarios. A scenario whose live
status differs from its recording is listed under `changed`: the model or the data moved since the fixtures were
recorded, so they are stale (PLAN.md risk register: "replay fixtures drift from live behavior").

The sample is a pure function of the day, so a re-run of the same day picks the same scenarios. Budget caps apply
per scenario exactly as in production (`QuestionBudget` inside `ev06_graph.graph_runner`); the per-day spend is at
most `k` question caps. Only ids, routes, statuses and tool names are reported, never question or answer text
(AGENTS.md rule 16). Live runs happen only through the ops workflow; CI uses replay.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from .ev06_graph import FIXTURES, default_scenarios, run_graph

SAMPLE_SIZE = 3


def daily_sample(day: date, k: int = SAMPLE_SIZE, scenarios: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """`k` scenarios ranked by sha256(day|id): same day, same sample; different days rotate through the set."""
    scs = scenarios if scenarios is not None else default_scenarios()
    rank = sorted(scs, key=lambda s: hashlib.sha256(f"{day.isoformat()}|{s['id']}".encode()).hexdigest())
    return rank[:max(0, k)]


def online_eval(gold_dir: Path, model_key: str, day: date, k: int = SAMPLE_SIZE, live_client: Any = None,
                fixtures_dir: Path = FIXTURES, scenarios: list[dict[str, Any]] | None = None,
                live: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Live run of the day's sample vs the recorded replay. `live` overrides the live runner (tests)."""
    sample = daily_sample(day, k, scenarios)
    if not sample:
        raise ValueError("online evaluation sample is empty")
    run_live = live or (lambda scs: run_graph(gold_dir, model_key, "live", fixtures_dir, live_client=live_client, scenarios=scs))
    now = run_live(sample)
    recorded = run_graph(gold_dir, model_key, "replay", fixtures_dir, scenarios=sample)
    changed = sorted(sid for sid, r in now["runs"].items()
                     if recorded["runs"].get(sid, {}).get("status") != r["status"]
                     or recorded["runs"].get(sid, {}).get("route") != r["route"])
    return {
        "synthetic": True, "day": day.isoformat(), "model": now["model"], "sample": [s["id"] for s in sample],
        "live": {"ev06": now["ev06"], "failed": now["failed"], "runs": now["runs"]},
        "recorded": {"ev06": recorded["ev06"], "failed": recorded["failed"], "drifted": recorded["drifted"]},
        "changed": changed, "stale_fixtures": bool(changed),
    }
