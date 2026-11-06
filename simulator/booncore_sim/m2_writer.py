"""M2-01 step 10: Parquet landing for the M2 tables, one chunk per window month (m2-plan.md M2-01 items 7-8).

Each monthly chunk writes only that month's telemetry, raw sample and outcomes, so a backfill Lambda can run one
month at a time; `write_static` writes the tables that don't depend on the month. Files carry synthetic-data
metadata, nothing time-dependent is written, and a manifest lists every file with its sha256 (same seed gives
byte-identical output). Column types come from the dataclasses. Not wired into the CLI. All output is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import GENERATOR, __version__, m2_focus, m2_outcomes, m2_revenue
from .m2_catalog import PRICE_CATALOG_V2
from .m2_run import PatternedRun, patterned_month
from .m2_telemetry import month_days
from .m2_tenants import WINDOW_END, WINDOW_START, M2Tenant, TenantVersion


def _table(rows: list, seed: int, kind: str) -> pa.Table:
    if not rows:
        raise ValueError(f"no {kind} rows to write")
    if not is_dataclass(rows[0]):
        raise TypeError("rows must be dataclass instances")
    meta = {b"synthetic": b"true", b"generator": GENERATOR.encode(), b"generator_version": __version__.encode(),
            b"profile": b"m2", b"seed": str(seed).encode()}
    table = pa.Table.from_pylist([asdict(r) for r in rows])
    return table.replace_schema_metadata(meta)


def _write(out_dir: Path, rel: str, rows: list, seed: int, kind: str) -> dict:
    table = _table(rows, seed, kind)
    path = out_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return {"path": rel, "rows": table.num_rows, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_month(out_dir: Path, seed: int, tenants: list[M2Tenant], month_index: int) -> list[dict]:
    """One backfill chunk: patterned telemetry, 1% raw sample and outcomes for the month. Returns manifest entries."""
    key = month_days(month_index)[0].strftime("%Y-%m")
    rows, raw = patterned_month(seed, tenants, month_index)
    daily, tickets = m2_outcomes.generate_month(seed, tenants, month_index)
    return [
        _write(out_dir, f"s1_llm_telemetry/month={key}/telemetry.parquet", rows, seed, "telemetry"),
        _write(out_dir, f"s1_llm_telemetry/month={key}/raw_requests.parquet", raw, seed, "raw requests"),
        _write(out_dir, f"s4_outcomes/month={key}/daily.parquet", daily, seed, "daily outcomes"),
        _write(out_dir, f"s4_outcomes/month={key}/tickets.parquet", tickets, seed, "ticket outcomes"),
    ]


def write_static(out_dir: Path, seed: int, run: PatternedRun) -> list[dict]:
    """Tables that don't depend on the month: tenants, price catalog, pattern labels, renewal events."""
    return [
        _write(out_dir, "tenants/tenants.parquet", run.tenants, seed, "tenants"),
        _write(out_dir, "s5_price_catalog/price_catalog.parquet", list(PRICE_CATALOG_V2), seed, "price catalog"),
        _write(out_dir, "labels/patterns.parquet", run.labels, seed, "pattern labels"),
        _write(out_dir, "labels/renewal_events.parquet", run.renewal_events, seed, "renewal events"),
    ]


def write_focus(out_dir: Path, seed: int, tenants: list[M2Tenant]) -> list[dict]:
    """S2: the shared-infrastructure FOCUS 1.2 export for the whole window (about 4.5k daily rows, so one file)."""
    return [_write(out_dir, "s2_focus/focus.parquet", m2_focus.generate_all(seed, tenants), seed, "focus rows")]


def write_revenue(out_dir: Path, seed: int, tenants: list[M2Tenant], history: list[TenantVersion]) -> list[dict]:
    """S3: monthly invoice lines (subscription, AI add-on, discount) for the whole window."""
    invoices = m2_revenue.generate_invoices(tenants, history)
    return [_write(out_dir, "s3_revenue/invoices.parquet", invoices, seed, "invoice lines")]


def write_manifest(out_dir: Path, seed: int, files: list[dict]) -> dict:
    manifest = {
        "generator": GENERATOR, "generator_version": __version__, "synthetic": True, "profile": "m2", "seed": seed,
        "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
        "files": sorted(files, key=lambda f: f["path"]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


__all__ = ["write_month", "write_static", "write_focus", "write_revenue", "write_manifest"]
