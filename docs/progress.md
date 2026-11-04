# Progress log

Dated entries, newest first. Unattended runs read this file first and append to it (see `docs/autopilot/`).

## Waiting for owner

- **M1 exit, cost criterion:** Cost Explorer had no data on 2026-11-04 (enabled that day). Re-check with the ops workflow (`task: cost-report`) after 2026-11-05 10:00 UTC; close M1 if month-to-date < $0.50.
- **Claude Haiku 5.5 access** (support case): when granted, record its M1-06 fixtures (`task: record-fixtures`, model `haiku-5-5`) and apply the ADR-003 selection rule.

## Next

1. M1 cost check (above), then close M1 (PLAN.md §17, AGENTS.md §2).
2. M2 step 1: the volume spike (`docs/plans/m2-plan.md` §3).

## 2026-11-04

- M1-01…M1-08 merged; dev deployed; CI deploys on merge through OIDC (immutable subject).
- M2 plan approved (D1, D3, D4, D7 by the owner; D2, D5, D6 by recommendation).
