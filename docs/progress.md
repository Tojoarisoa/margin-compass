# Progress log

Dated entries, newest first. Unattended runs read this file first and append to it (see `docs/autopilot/`).

## Waiting for owner

- **Claude Haiku 5.5 access** (support case): when granted, record its M1-06 fixtures (`task: record-fixtures`, model `haiku-5-5`) and apply the ADR-003 selection rule.

- **Haiku 5.5 access:** only the owner can follow up on the support case; autopilot re-probes it with the ops workflow (`record-fixtures`, `haiku-5-5`) at most once a day.
- **Haiku 5.5, 2026-11-05 (owner session):** the owner accepted AWS's public offer (`offer-u3aih6zr7uw5u`, usage-based: $0.10/$0.50 per 1M input/output, global). The agreement is **AVAILABLE** (authorization, entitlement, and region also available), but Converse via `us.anthropic.claude-haiku-5-5` still returns `AccessDeniedException` "not available for this account … contact AWS Sales" after 4 tries over 4 minutes. Per AWS docs this is the separate account-level access that only AWS Sales grants. Owner action: contact AWS Sales. Keep the daily re-probe.

## Owner decision 2026-11-06

- **Window:** BoonCore's fiscal year starts April 1. The simulation window is now **2025-04-01 → 2026-10-31** (19 months, 579 days), set in `simulator/booncore_sim/m2_tenants.py` (`WINDOW_START`, `MONTHS`, `fiscal_year()`). Build the remaining M2 steps (backfill: 19 monthly chunks) on this window. Measured at seed 42: telemetry 2.71M rows, sample 0.44M, outcomes 0.68M, shared infrastructure 16.5% of AI COGS.

## Next

1. M2-01: Step Functions backfill over 19 monthly chunks calling `booncore-sim --profile m2 --mode month --month N` (infra change: check the cost gate first), then tick M2-01.
2. M2-02: FOCUS ingestion, allocation rules, cost-to-serve marts (`docs/plans/m2-plan.md` §2).

## 2026-11-05 (autopilot run 10, task 1)

- **Task:** M2-01 step 11, CLI `--profile m2` with `--mode month --month N` (one backfill chunk), `--mode static`, or `all`. Chunk and static modes write their manifest under `_manifests/`; `all` writes `manifest.json`. M1 profile unchanged. 1 new test.
- **Decisions (§8.2):** none needed. Default seed 42 for m2. Cost $0.
- **PR / CI / deploy:** see below.
- **Next:** Step Functions backfill (infra change, cost gate first).

## 2026-11-05 (autopilot run 9, task 3)

- **Task:** M2-01 step 10, Parquet landing: `simulator/booncore_sim/m2_writer.py`. `write_month` writes one month's telemetry, raw sample and outcomes (daily and tickets) under `month=YYYY-MM/`; `write_static` writes tenants, price catalog, pattern labels and renewal events; `write_manifest` lists sha256 per file. Synthetic-data metadata, byte-identical for the same seed. 2 new tests. Not wired into the CLI, so M1 output is unchanged.
- **Decisions (§8.2):** none needed. Column types are inferred from the dataclasses (no hand-written schemas yet); the dbt/ingest side will pin them when it reads these files.
- **PR / CI / deploy:** PR #38, all checks green on the head commit. Fast-forwarded to `main`; `deploy to dev` green. Cost $0.
- **Next:** CLI `--profile m2` (month chunk and static modes), then the Step Functions backfill (needs an infra change, so check the cost gate first). Run ended at the 3-task limit.

## 2026-11-05 (autopilot run 9, task 2)

- **Task:** M2-01 step 9, composed run: `simulator/booncore_sim/m2_run.py`. `patterned_month` is the backfill chunk (baseline telemetry plus PT-01...PT-07 and PT-10); `generate_patterned` is the full run with all 14 labels (PT-12 from `m2_focus`; PT-08/09/11 priced on baseline rows) and PT-14 events. Tests: 14 labels in order, row budget 1.5-3M, and a month generated alone equals the same month in the full run (chunk determinism). Not wired into the CLI, so M1 output is unchanged.
- **Decisions (§8.2):** none needed. Cost $0.
- **PR / CI / deploy:** PR #37, all checks green on the head commit (rebased once more onto a docs-only main commit and re-ran CI). Fast-forwarded to `main`; `deploy to dev` green.
- **Next:** M2 landing writer (parquet for the new tables) and CLI profile, then the Step Functions backfill.

## 2026-11-05 (autopilot run 9)

- **Task:** M2-01 step 8, patterns PT-08...PT-14 in `simulator/booncore_sim/m2_patterns_b.py`. PT-08 (b-mid blocked by provider/EU clauses), PT-09 (F0 to small tier proposal, recall 97.5% < 99%), PT-11 (b-mid cut not adopted) are label-only with computed savings; PT-10 scales 12 unlimited-AI tenants x3; PT-13 is a zero-impact seasonality label; PT-14 draws renewal churn/downgrade events with true probabilities (logistic, assumed coefficients). PT-12 already in `m2_focus`. 7 new tests; not wired into the CLI, so M1 output is unchanged.
- **Decisions (§8.2):** none needed. Labeled assumptions: PT-09 proposal date 2026-09-01; PT-10 3x applies to each tenant's own baseline; PT-08 prices only b-mid (c-small has no cache pricing); PT-14 coefficients and renewal price uplift 0-8%.
- **PR / CI / deploy:** PR #35, all checks green on the head commit (attribution failed once on the proxy footer, passed after editing the body via the GitHub MCP tool; rebased once onto a docs-only main commit and re-ran CI). Fast-forwarded to `main`; `deploy to dev` green. Cost $0.
- **Next:** wire the patterns into the generator and add the chunked backfill (M2-01 remainder).

## 2026-11-05 (autopilot run 8)

- **Task:** M2-01 step 7, patterns PT-05...PT-07 in `simulator/booncore_sim/m2_patterns.py`: F3 re-index storm (x30, 2026-02-10 for 3 days), F2 fleet update surge (x6, 5 days from 2026-06-02), F2 integration flood (uncached input x3, 7 days from 2026-08-18). 3 new tests; not wired into the CLI, so M1 output is unchanged.
- **Impacts (seed 42, $/day):** PT-05 4.4, PT-06 25.2 (tenant `bc-t0059`), PT-07 428 (`bc-t0001`...`bc-t0003`).
- **Decisions (§8.2):** none needed. Labeled assumptions: PT-06 targets the last imaging tenant by id (differs from PT-02); PT-07 triples only uncached input tokens; PT-05 scales all F3 tenants.
- **PR / CI / deploy:** PR #31, all checks green on the head commit (attribution failed once on the proxy footer, passed after removing it via the GitHub MCP tool). Fast-forwarded to `main`; `deploy to dev` green.
- **Next:** PT-08...PT-14. Cost $0.

## 2026-11-05 (autopilot run 7)

- **Task:** M1 cost check and close. Ops `cost-report` (run 42025060616): month to date $0.0373 (< $0.50), budget actual $0.0 of $5, FOCUS export delivering. M1 exit criterion met; PLAN.md §17 and AGENTS.md §2 updated.
- **PR / CI / deploy:** PR #30, all checks green on the head commit (attribution failed once on the proxy footer, passed after removing it via the GitHub MCP tool). Fast-forwarded to `main`; `deploy to dev` green.
- **Decisions (§8.2):** none needed. Cost $0.
- **Next:** M2-01 patterns PT-05...PT-14.

## 2026-11-05 (owner-requested follow-up run)

- **Task:** M2-01 step 6, patterns PT-01...PT-04: `simulator/booncore_sim/m2_patterns.py`. Post-hoc transforms of baseline telemetry, so the baseline is unchanged. Each returns a `PatternLabel` with a computed `expected_impact_usd_per_day`. 5 new tests; not wired into the CLI, so M1 output is unchanged.
- **Impacts (seed 42, $/day, averaged over each pattern's days):** PT-01 37, PT-02 5 (tenant `bc-t0002`), PT-03 489, PT-04 43. PT-02 is small because the spec's "retries x4" on a 2% retry base only adds about 6% extra requests (assumption: each added retry re-sends an average request).
- **Decisions (§8.2):** none needed. PT-03: the baseline already routes F4 to frontier, so earlier F4 rows are moved to `a-mid` before 2025-11-03. Labels are marginal in order PT-01 to PT-04 (PT-04 impact includes PT-01's token growth on the same F1 rows).
- **PR / CI / deploy:** PR #29, all checks green on the head commit (attribution failed once on the proxy footer, passed after removing it). Fast-forwarded to `main`; `deploy to dev` green. Cost $0.
- **Next:** PT-05...PT-07 (F3 re-index storm, F2 fleet update surge, integration flood), then PT-08...PT-14. M1 cost check still pending (after 10:00 UTC).

## 2026-11-05 (autopilot run 6)

- **Task:** M2-01 step 5, FOCUS shared infra: `simulator/booncore_sim/m2_focus.py`. FOCUS 1.2 daily rows (4,482) for compute, vector storage and queries, egress, observability, third-party APIs and staging, tagged `x-feature` and `x-env`. PT-12 is in: idle staging GPU 2025-12-01..2026-02-28 ($96/day) and an oversized vector tier throughout ($38/day), with `pt12_waste_usd_per_day` as ground truth. 7 new tests; not wired into the CLI, so M1 output is unchanged.
- **Calibration (D3):** seed 42 LLM cost is $3.43M over 18 months; shared infra is $0.675M, 16.4% of AI COGS (target about 15%; test band 12-18%). Labeled assumptions: per-tenant-day cost lines, 3% metering noise, weekend factor 0.6.
- **Decisions (§8.2):** none needed. Cost $0.
- **PR / CI / deploy:** PR #28, all checks green on the head commit (attribution failed once on the proxy footer, passed after removing it via the GitHub MCP tool). Fast-forwarded to `main`; `deploy to dev` green. Simulator code only.
- **M1 cost check:** not run; it was about 09:10 UTC, Cost Explorer data is expected after 10:00 UTC.
- **Next:** M2-01 patterns PT-01...PT-14 (start with PT-01...PT-04 and `labels/patterns`).

## 2026-11-05 (autopilot run 5)

- **Task:** M2-01 step 4, outcomes: `simulator/booncore_sim/m2_outcomes.py`. Every ticket is drawn individually, then stored as tenant x day aggregates (171k rows) plus per-ticket rows for a 10% sample and every labeled safety event (485k rows). Total 0.66M, under the 1M budget. F0 flags follow the F0 tier's recall (seed 42: recall 99.3%, remote resolution 40%). 7 new tests; not wired into the CLI, so M1 output is unchanged.
- **Decisions (§8.2):** none needed. Labeled assumptions: false-flag rate 0.5%, field visit 60% after unresolved F2 and 15% otherwise, escalation 30/10/3% by severity, CSAT and eval_score distributions. Outcome ticket counts share the telemetry mean but use their own RNG stream, so they track request volume statistically, not ticket for ticket.
- **M1 cost check:** not run; it was about 00:10 UTC, Cost Explorer data is expected after 10:00 UTC today.
- **PR / CI / deploy:** PR #25, all checks green on the head commit (attribution failed once on the proxy footer, passed after removing it via the GitHub MCP tool). Fast-forwarded to `main`; `deploy to dev` and smoke test green. Simulator code only, no infra change. Cost $0.
- **Next:** M2-01 FOCUS shared-infra export, then patterns PT-01...PT-14.

## 2026-11-04

- M1-01…M1-08 merged; dev deployed; CI deploys on merge through OIDC (immutable subject).
- M2 plan approved (D1, D3, D4, D7 by the owner; D2, D5, D6 by recommendation).

## 2026-11-04 (owner session)

- Owner: autopilot merges once CI is green (AGENTS.md §8.1 step 5 updated; `.claude/settings.json` allows `git push origin *:main`). PR #23 merged by fast-forward. Dev deploy green. Haiku 5.5 probe (ops run 41917944197): still `AccessDeniedException`, "not available for this account".

## 2026-11-04 (autopilot run 4)

- **Task:** M2-01 step 3, telemetry grain: `simulator/booncore_sim/m2_telemetry.py`. Enterprise hourly, other plans daily, 1% raw request sample with trace IDs, weekly/respiratory/fiscal-year seasonality (PT-13 baseline, no injected patterns yet). One RNG stream per (seed, month, tenant), so any month regenerates identically alone. 11 new tests; not wired into the CLI, so M1 output is unchanged.
- **Result (seed 42, 18 months):** 2.59M telemetry rows (budget 1.5-3M), 0.42M sampled requests (< 0.63M), 41.8M requests. A full run takes about 65 s in plain Python, fine for the monthly Lambda chunks.
- **Decisions (§8.2):** F3 and F4 get daily rows for every tenant (labeled assumption). With them hourly the Enterprise grain gave 3.05M rows, over the 3M budget. Alternative: hourly for all features and lower volume; rejected because it changes the spec volumes. Other labeled assumptions: peak hours 08-17 UTC, F1 cache hit 70%, F2 50%, retry rate 2%.
- **Calibration note:** 41.8M requests is below the spec's ~115k/weekday x 18 months estimate; AI margin calibration (~50%) is still to do before the patterns step.
- **PR / CI / deploy:** PR #23, all checks green on the head commit (the first two attribution runs failed on the proxy's footer; the re-run after removing it via the GitHub MCP tool passed). Not merged: the fast-forward to `main` was denied last run and needs your OK, so #23 awaits merge. Simulator code only, no infra change. Cost $0.
- **Next:** M2-01 outcomes (tenant x day aggregates, 10% ticket sample, safety events). M1 cost check still waits for 2026-11-05 10:00 UTC.

## 2026-11-04 (autopilot run 3)

- **Task:** M2-01 step 2, features and models: `simulator/booncore_sim/m2_catalog.py` (F0-F4 with token medians, 6 models incl. `emb-1`, effective-dated catalog with the `b-mid` -40% cut on 2026-03-01, cached and batch pricing, tier quality table, token draws). 9 new tests; not wired into the CLI, so M1 output is unchanged.
- **PR / CI / deploy:** PR #21, all checks green (the attribution check failed twice because the cloud GitHub proxy appends a "Generated by Claude Code" footer on `gh api` body writes; editing the body through the GitHub MCP tool removed it). The unattended fast-forward to `main` was denied by the session's permission classifier ("CI Bypass"); merged later the same day at the owner's request. Cost $0.
- **Decisions (§8.2):** none needed. Labeled assumptions: F2 cacheable prefix 3,000 tokens, token sigma 0.4 (as M1).
- **Next:** M2-01 telemetry grain (Enterprise hourly, others daily, 1% raw sample). M1 cost check still waits for 2026-11-05 10:00 UTC.

## 2026-11-04 (autopilot run 2)

- **Task:** M2-01 step 1, tenants and contracts: `simulator/booncore_sim/m2_tenants.py` (400 tenants, ARR exact to $24.0M by plan, contract clauses at the spec §5 counts, SCD2 plan history, +2%/month onboarding with Jan/Sep waves). 10 new tests; not wired into the CLI yet, so M1 output is unchanged.
- **PR / CI / deploy:** see the PR; simulator code only, no infra change. Cost $0.
- **Decisions (§8.2):** none needed. Labeled assumptions: log-normal sigma 0.5, 6% of tenants upgrade a plan in the window, wave months onboard 2× a normal month, 80% of fiscal years end Jun 30.
- **Next:** M2-01 features and models. M1 cost check still waits for 2026-11-05 10:00 UTC.

## 2026-11-04 (autopilot run 1)

- **Task:** M2 step 1, volume spike. **PR:** auto/m2-spike-volume (see merge below).
- **Result:** 2.85M telemetry rows; ingest < 1 s; M1 `dbt build` 10-14 s, <= 1.1 GB peak; gold 69 MB. Limits are 10 min, 6 GB, 300 MB, so there is plenty of headroom. Details and caveats: `docs/plans/m2-spike-results.md`.
- **Not done:** the Lambda 4 GB run (needs a deploy; do it at M2 step 5). M1 cost check skipped: Cost Explorer has no data before 2026-11-05 10:00 UTC.
- **Decisions (§8.2):** none needed. No infra change, cost $0.
- **Next:** M2-01 simulator, starting with tenants and contracts.
