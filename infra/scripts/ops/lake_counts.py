"""Print parquet row counts under a synced lake copy (ops verify-backfill).

Usage: lake_counts.py <dir>  (dir holds gold/ and silver/ as synced from S3). Needs duckdb.
Compares the M2 telemetry table with the local seed-42 build (2.71M rows, AGENTS/progress notes).
"""
import sys
from pathlib import Path

import duckdb

EXPECTED = {"slv_m2_llm_usage_priced": 2_710_000}  # seed 42, window 2025-04-01..2026-10-31
TOLERANCE = 0.02


def main(root: str) -> int:
    con = duckdb.connect()
    bad = 0
    for path in sorted(Path(root).rglob("*.parquet")):
        n = con.execute("select count(*) from read_parquet(?)", [str(path)]).fetchone()[0]
        stem = path.stem
        note = ""
        if stem in EXPECTED:
            ok = abs(n - EXPECTED[stem]) <= EXPECTED[stem] * TOLERANCE
            note = f"  expected ~{EXPECTED[stem]:,}: {'OK' if ok else 'MISMATCH'}"
            bad += not ok
        print(f"{path.relative_to(root)}\t{n:,}{note}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
