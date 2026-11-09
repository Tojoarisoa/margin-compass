"""Print the daily llm_cost_usd of one feature from a synced gold copy (ops verify-backfill).

Usage: dump_series.py <lake dir> <feature_id>. One `date,cost` line per day (M2 gold fct_unit_cost). Needs duckdb.
"""
import sys

import duckdb


def main(root: str, feature: str) -> int:
    rows = duckdb.connect().execute(
        "select cost_date, round(sum(llm_cost_usd), 6) from read_parquet(?) where feature_id = ? group by 1 order by 1",
        [f"{root}/gold/fct_unit_cost.parquet", feature],
    ).fetchall()
    for d, c in rows:
        print(f"{d},{c}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
