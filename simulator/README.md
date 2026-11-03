# simulator/: BoonCore synthetic data

Generates the fictional BoonCore company's data with labeled ground truth ([spec](../docs/booncore-spec.md)). **All output is synthetic.**

```bash
cd simulator
uv sync
uv run pytest -q                                              # 19 tests
uv run booncore-sim --profile m1 --out ../data/local/landing/booncore
```

- Profile `m1` (M1-01): 20 tenants, F1 only, `a-small` and `a-mid`, 2025-08-01 → 2025-10-29, pattern PT-01.
- Output format and guarantees: [data contract](../docs/data-contracts/booncore-landing-m1.md).
- Deterministic: same profile and seed, byte-identical files. Logs are JSON lines on stderr with a `run_id`.
- `data/` is git-ignored; generated files are never committed.
