"""Churn step of the M2 build: fit on the earlier renewals, judge EV-11 on the later ones, write `fct_churn_scores`."""

from __future__ import annotations

from pathlib import Path

from .train import read_events, train_and_score, write_scores

TEST_SHARE = 0.3
MIN_EVENTS = 50


def run_churn(events_path: Path, gold: Path, run_id: str) -> dict:
    """Time split (no seed leakage inside one landing tree): the latest `TEST_SHARE` of renewals is the held-out set."""
    rows = sorted(read_events(events_path), key=lambda r: (r["renewal_date"], r["tenant_id"]))
    if len(rows) < MIN_EVENTS:
        return {"skipped": f"only {len(rows)} renewal events"}
    cut = int(len(rows) * (1 - TEST_SHARE))
    model, gate = train_and_score(rows[:cut], rows[cut:])
    gate["scored"] = write_scores(gold / "fct_churn_scores.parquet", model, rows, run_id)
    gate["test_n"] = len(rows) - cut
    return {"ev11": gate}


__all__ = ["run_churn"]
