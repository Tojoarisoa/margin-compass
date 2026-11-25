#!/usr/bin/env python3
"""Monthly cap on paid ops model runs (owner decision 2026-11-26), checked before any AWS call.

Counts this UTC month's ops workflow runs whose title names a paid task (`run-name: ops <task>` in
ops.yml), excluding the current run and runs cancelled or skipped before they could spend. Counts failed
and in-progress runs: they may already have spent. Exits 1 when the count has reached the cap.

Env: GITHUB_API_URL, GITHUB_REPOSITORY, GITHUB_RUN_ID, GH_TOKEN, MC_PAID_RUNS_PER_MONTH, TASK.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from typing import Any

PAID_TASKS = ("record-fixtures", "live-eval", "online-eval", "red-team", "rag-eval", "nightly-insight")
NOT_SPENT = ("cancelled", "skipped")


def title(task: str) -> str:
    return f"ops {task}"


def count_paid(runs: list[dict[str, Any]], current_run_id: int) -> int:
    titles = {title(t) for t in PAID_TASKS}
    return sum(1 for r in runs
               if r["id"] != current_run_id and r.get("display_title") in titles and r.get("conclusion") not in NOT_SPENT)


def month_start(now: datetime) -> str:
    return now.strftime("%Y-%m-01")


def _runs(api: str, repo: str, token: str, since: str) -> list[dict[str, Any]]:
    out, page = [], 1
    while True:
        url = f"{api}/repos/{repo}/actions/workflows/ops.yml/runs?created=%3E%3D{since}&per_page=100&page={page}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - GitHub API URL from the runner
            body = json.loads(resp.read())
        out += body["workflow_runs"]
        if len(out) >= body["total_count"] or not body["workflow_runs"]:
            return out
        page += 1


def main() -> int:
    task, cap = os.environ["TASK"], int(os.environ["MC_PAID_RUNS_PER_MONTH"])
    if task not in PAID_TASKS:
        print(f"{task}: not a paid model run, no cap")
        return 0
    since = month_start(datetime.now(UTC))
    runs = _runs(os.environ.get("GITHUB_API_URL", "https://api.github.com"), os.environ["GITHUB_REPOSITORY"],
                 os.environ["GH_TOKEN"], since)
    used = count_paid(runs, int(os.environ["GITHUB_RUN_ID"]))
    print(f"## Paid ops model runs since {since}: {used} of {cap}")
    if used >= cap:
        print(f"Monthly cap reached: {task} not started (AGENTS.md §8.3, owner decision 2026-11-26).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
