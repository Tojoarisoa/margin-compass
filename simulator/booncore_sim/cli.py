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
from datetime import UTC, datetime
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
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
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


def run_m2(seed: int | None, out_dir: Path, mode: str, month: int | None) -> dict:
    """M2 profile. `month` writes one chunk, `static` the month-independent tables, `all` everything."""
    from . import m2_writer
    from .m2_run import generate_patterned
    from .m2_tenants import MONTHS, generate_m2_tenants

    seed = 42 if seed is None else seed
    log.info("simulation_started", extra={"fields": {"profile": "m2", "seed": seed, "mode": mode, "out": str(out_dir)}})
    files: list[dict] = []
    manifest_dir = out_dir

    def whole_window(tenants: list) -> list[dict]:  # month-independent sources: FOCUS, invoices, dimensions
        history = generate_m2_tenants(seed)[1]
        return (m2_writer.write_focus(out_dir, seed, tenants) + m2_writer.write_revenue(out_dir, seed, tenants, history)
                + m2_writer.write_dimensions(out_dir, seed, history))

    if mode == "month":
        if month is None or not 0 <= month < MONTHS:
            raise SystemExit(f"--month must be 0..{MONTHS - 1} in month mode")
        files += m2_writer.write_month(out_dir, seed, generate_m2_tenants(seed)[0], month)
        manifest_dir = out_dir / "_manifests" / f"month-{month:02d}"
    elif mode == "static":
        static = generate_patterned(seed)
        files += m2_writer.write_static(out_dir, seed, static) + whole_window(static.tenants)
        manifest_dir = out_dir / "_manifests" / "static"
    else:
        run_all = generate_patterned(seed)
        files += m2_writer.write_static(out_dir, seed, run_all) + whole_window(run_all.tenants)
        for i in range(MONTHS):
            files += m2_writer.write_month(out_dir, seed, run_all.tenants, i)
    manifest = m2_writer.write_manifest(manifest_dir, seed, files)
    for f in manifest["files"]:
        log.info("file_written", extra={"fields": {"path": f["path"], "rows": f["rows"]}})
    log.info("simulation_finished", extra={"fields": {"files": len(files), "synthetic": True}})
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic BoonCore data (all output is synthetic).")
    parser.add_argument("--profile", default="m1", choices=[*sorted(PROFILES), "m2"])
    parser.add_argument("--mode", default="all", choices=["all", "month", "static"], help="m2 only")
    parser.add_argument("--month", type=int, default=None, help="m2 month mode: window month index, 0-based")
    parser.add_argument("--seed", type=int, default=None, help="override the profile's seed")
    parser.add_argument("--out", type=Path, default=Path("../data/local/landing/booncore"))
    args = parser.parse_args(argv)

    run_id = str(uuid.uuid4())
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(run_id))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False

    if args.profile == "m2":
        run_m2(args.seed, args.out, args.mode, args.month)
        return 0
    run(args.profile, args.seed, args.out, run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
