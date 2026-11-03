"""Command line: `uv run booncore-sim --profile m1 --seed 42 --out ../data/local/landing/booncore`.

Logs are structured JSON lines on stderr with a shared run_id (PLAN.md §14). They contain metadata
only, never data content.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .config import PROFILES
from .revenue import generate_invoices
from .telemetry import generate_f1_telemetry, pt01_label
from .tenants import generate_tenants
from .writer import write_landing

log = logging.getLogger("booncore_sim")


class JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": self.run_id,
            "component": "simulator",
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, sort_keys=True)


def run(profile: str, seed: int | None, out_dir: Path, run_id: str) -> dict:
    cfg = PROFILES[profile]
    if seed is not None:
        cfg = dataclasses.replace(cfg, seed=seed)
    log.info("simulation_started", extra={"fields": {"profile": cfg.profile, "seed": cfg.seed, "out": str(out_dir)}})
    rng = np.random.default_rng(cfg.seed)
    tenants = generate_tenants(cfg, rng)
    usage = generate_f1_telemetry(cfg, tenants, rng)
    invoices = generate_invoices(cfg, tenants)
    labels = [pt01_label(cfg, usage)] if "PT-01" in cfg.patterns else []
    manifest = write_landing(out_dir, cfg, tenants, usage, invoices, labels)
    for f in manifest["files"]:
        log.info("file_written", extra={"fields": {"path": f["path"], "rows": f["rows"]}})
    log.info("simulation_finished", extra={"fields": {"files": len(manifest["files"]), "synthetic": True}})
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic BoonCore data (all output is synthetic).")
    parser.add_argument("--profile", default="m1", choices=sorted(PROFILES))
    parser.add_argument("--seed", type=int, default=None, help="override the profile's seed")
    parser.add_argument("--out", type=Path, default=Path("../data/local/landing/booncore"))
    args = parser.parse_args(argv)

    run_id = str(uuid.uuid4())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(run_id))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False

    run(args.profile, args.seed, args.out, run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
