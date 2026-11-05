# M2 step 1: volume spike results (2026-11-04)

Method: `pipelines/spikes/volume_spike.py` writes M1-schema landing files at the M2 target volume
(400 tenants, 2025-05-01 to 2026-10-31, 13 feature × model combinations per tenant-day), then runs
`ingest` and `dbt build` (DuckDB, 1 thread) on a 4-vCPU, 15 GB sandbox. All data is synthetic.

| Measure | Result | Limit (PLAN.md §7.5) |
| --- | --- | --- |
| Telemetry rows | 2,854,800 | ≈ 2.8M |
| Generate landing files (load generator only) | ~5 s, 0.55 GB peak | n/a |
| `ingest` | < 1 s | n/a |
| `dbt build` (existing M1 models) | 10–14 s, 0.9–1.1 GB peak RSS (whole process) | ≤ 10 min, ≤ 6 GB |
| Gold Parquet | 63–69 MB | ≤ 300 MB |

Conclusion: at this volume the existing build is far inside the limits. A single dbt build over the
whole window fits one run, so monthly chunking is only needed for the simulator, not for memory.
Keep the chunked Map (D5) for determinism and for the heavier M2 marts, and re-measure after M2-02.

Caveats (not verified):

- The M1 models are light. M2-02 adds allocation, 7 marts and SCD2, so build time and memory will grow. Re-run the spike after M2-02.
- The M1 models hard-code F1. On F0–F4 data, `preservation_cost_allocated_plus_unallocated` fails even after a text patch, because the `fct_tenant_margin` grid is F1-only. This is expected and is M2-02 work; the timings above cover the build up to that point plus the skipped downstream nodes.
- Revenue was 14,400 invoice lines, not the ≈ 0.44M daily-ized rows. Revenue is small next to telemetry.
- Hourly Enterprise grain was not modeled (the landing schema has `usage_date` only); rows were matched to the target by count.
- The same build in the Lambda container at 4 GB was not run. The ops workflow can't dispatch it and AWS deploys need a separate step. Open item for step 5 (AWS).

> **Note (2026-11-06):** the owner later moved the window to 2025-04-01 → 2026-10-31 (19 months, fiscal-year aligned). The spike's conclusions hold: the measured M2 telemetry is 2.71M rows, below the 2.85M rows this spike tested.
