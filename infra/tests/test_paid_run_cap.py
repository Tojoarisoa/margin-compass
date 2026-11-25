"""Monthly cap on paid ops model runs (owner decision 2026-11-26): counting rules and the stop."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "paid_run_cap.py"
spec = importlib.util.spec_from_file_location("paid_run_cap", SCRIPT)
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)


def _run(i, task, conclusion="success"):
    return {"id": i, "display_title": f"ops {task}", "conclusion": conclusion}


def test_counts_paid_tasks_only_and_not_the_current_run():
    runs = [_run(1, "record-fixtures"), _run(2, "status"), _run(3, "cost-report"), _run(4, "online-eval"),
            _run(5, "red-team", "failure"), _run(6, "live-eval", None), _run(7, "rag-eval")]
    assert cap.count_paid(runs, current_run_id=7) == 4  # 1, 4, 5 (failed may have spent), 6 (in progress)


def test_cancelled_or_skipped_runs_do_not_count():
    runs = [_run(1, "nightly-insight", "cancelled"), _run(2, "nightly-insight", "skipped"), _run(3, "nightly-insight")]
    assert cap.count_paid(runs, current_run_id=99) == 1


def test_untitled_runs_do_not_count():
    assert cap.count_paid([{"id": 1, "display_title": "ops", "conclusion": "success"}], current_run_id=2) == 0


def test_month_start_is_utc_calendar_month():
    assert cap.month_start(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == "2026-12-01"


@pytest.mark.parametrize(("used", "code"), [(11, 0), (12, 1), (13, 1)])
def test_stops_at_the_cap(monkeypatch, used, code):
    monkeypatch.setenv("TASK", "record-fixtures")
    monkeypatch.setenv("MC_PAID_RUNS_PER_MONTH", "12")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "1000")
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(cap, "_runs", lambda *a: [_run(i, "live-eval") for i in range(used)])
    assert cap.main() == code


def test_free_tasks_are_never_capped(monkeypatch):
    monkeypatch.setenv("TASK", "cost-report")
    monkeypatch.setenv("MC_PAID_RUNS_PER_MONTH", "0")
    monkeypatch.setattr(cap, "_runs", lambda *a: pytest.fail("no API call for a free task"))
    assert cap.main() == 0


def test_paid_tasks_match_ops_workflow_options():
    ops = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ops.yml").read_text()
    for t in cap.PAID_TASKS:
        assert t in ops
    assert "run-name: ops " in ops and "paid_run_cap.py" in ops
