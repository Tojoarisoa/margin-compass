"""Builds synthetic gold once per session with the real simulator and pipeline (no network)."""

from pathlib import Path

import pytest

INGEST_DATE = "2026-11-04"


@pytest.fixture(scope="session")
def gold(tmp_path_factory) -> Path:
    from booncore_sim.cli import run as simulate
    from mc_pipelines.cli import main as pipeline_main

    root = tmp_path_factory.mktemp("mc")
    landing = root / "landing" / "booncore"
    simulate("m1", 42, landing, run_id="agents-test")
    assert pipeline_main(["run", "--landing", str(landing), "--data-root", str(root / "data"), "--ingest-date", INGEST_DATE]) == 0
    return root / "data" / "gold"


@pytest.fixture(autouse=True)
def _prompt_caching_on(monkeypatch):
    """Recorded fixtures carry cache points (M4-04), so request hashes match only with caching on."""
    monkeypatch.setenv("MC_CACHE_PROMPT", "1")
