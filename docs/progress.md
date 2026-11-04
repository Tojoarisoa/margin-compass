# Progress log

Dated entries, newest first. Unattended runs read this file first and append to it (see `docs/autopilot/`).

## Waiting for owner

- **M1 exit, cost criterion:** Cost Explorer had no data on 2026-11-04 (enabled that day). Re-check with the ops workflow (`task: cost-report`) after 2026-11-05 10:00 UTC; close M1 if month-to-date < $0.50.
- **Claude Haiku 5.5 access** (support case): when granted, record its M1-06 fixtures (`task: record-fixtures`, model `haiku-5-5`) and apply the ADR-003 selection rule.

## Next

1. M1 cost check (above), then close M1 (PLAN.md §17, AGENTS.md §2).
2. M2-01 continued: features and models (F0–F4, tiers, effective-dated catalog), then telemetry grain, outcomes, FOCUS, patterns (`docs/plans/m2-plan.md` §2). Tenants and contracts are done.

## 2026-11-04

- M1-01…M1-08 merged; dev deployed; CI deploys on merge through OIDC (immutable subject).
- M2 plan approved (D1, D3, D4, D7 by the owner; D2, D5, D6 by recommendation).

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
