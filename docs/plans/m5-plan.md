# M5 plan: Close the Loop (M5-03 and M5-04 split into PR-sized steps)

Written by autopilot run 89 (auto-decided under AGENTS.md §8.2). Cost target: $0 added (all code-only or free-tier).

## M5-03 Owner mode and simulator effects

Order: effects first (no AWS, testable offline), auth last (needs owner steps).

1. **Effect model (code only).** `simulator/booncore_sim/m5_effects.py`: pure functions that take approved actions
   (`action_id`, type, target, approved date) and return per-day multipliers on future telemetry cost (ACT-1), plan price
   or included usage (ACT-2) and tenant revenue/usage (ACT-3). Adoption lag, partial realization, quality delta and churn
   response are drawn from a seeded RNG and labelled `synthetic`. Unit tests: determinism, no effect before approval date,
   realization within bounds.
2. **Approvals input.** Read `approvals.jsonl` (action_id, decision, approver, rationale, decided_at) from the data root;
   missing file means no effects, so existing runs are unchanged. Wire into `m2_run` behind an opt-in flag.
3. **Counterfactual run.** Same seed with and without approvals, so M5-04 can compute realized margin by difference.
4. **Approval store (IaC).** DynamoDB table `mc-dev-state-approvals` (on-demand, PITR off, `mc-*` only, no `*` actions) and a write path in the web API restricted to the owner. Not RETAIN-deleting anything.
5. **Cognito owner sign-in (IaC).** User pool plus app client, self sign-up disabled. **Owner-only:** creating the owner user and setting a password is a console/secret step (AGENTS.md §8.3), so write it under "Waiting for owner" when this step is reached; do not create users from CI.
6. **Dashboard owner mode.** Sign-in link, approvals posted to the API instead of the browser sandbox; visitors keep the sandbox.

## M5-04 Realized margin

`fct_realized_margin` = counterfactual run minus approved run per action x day; KPI-01, -02, -09, -13 go live from it. Blocked on M5-03 steps 1-3.
