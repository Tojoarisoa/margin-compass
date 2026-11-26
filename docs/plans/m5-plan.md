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

### M5-04 remaining steps (autopilot run 181, auto-decided under AGENTS.md §8.2)

KPI-01 and KPI-02 are live (realized card, `realized.json`). Left:

4a. **KPI-13 owner record.** The M2 build writes `gold/_quality/roi.json` (private lake, not published): synthetic
    realized margin vs the real AWS bill to date (FOCUS export, before credits), ROI in bps. Owner 2026-11-12: kept off
    the public card. Options: budget cap as cost (rejected: the owner asked for the real bill), latest month only
    (rejected: the realized total spans the window, so the bill to date is the fairer denominator).
4b. **Ops `verify-backfill` prints `roi.json`**, so the owner sees KPI-13 in the job summary.
4c. **KPI-09 backtest (local, free).** In ops `realized-check`, approve one ACT-2 plan change, compare the calc-spec
    pricing prediction (revenue, margin, churn) with the observed counterfactual difference; report the error against
    the 10% target. Then tick M5-04.

#### Step 4c split: KPI-09 pricing simulator accuracy (autopilot run 181, auto-decided under AGENTS.md §8.2)

Found: the nightly review drafts ACT-2 with target `plan/<plan>`, but the simulator's ACT-2 effect reads
`<feature_id>/price` (`m5_effects.apply_act2_act3`). An approved nightly ACT-2 therefore changes nothing, and the
realized revenue side treats every plan as a flat add-on. KPI-09 needs a plan change that moves revenue.

- **4c-1 Simulator: ACT-2 on `plan/<plan>`.** For tenants on that plan: price uplift on the AI add-on (fixed
  assumption), demand response on volume, seeded churn; all labelled synthetic. Keep `<feature_id>/price` working.
- **4c-2 Revenue side.** `m5_realized` / `fct_realized_margin`: ACT-2 revenue delta = uplift on surviving tenants
  minus lost ARR of churned ones (same basis as ACT-3).
- **4c-3 Prediction.** At approval time, price the plan before/after with the calc-spec `price_plan` tool and its
  churn assumption (not the simulator's hidden response parameters), per month.
  Done (run 182): `agents/mc_agents/kpi09.py` `predict_plan_change`: each tenant as a calc-spec plan (non-add-on
  ARR as one seat, add-on as `addon_cents`), churn 200 bps/month (AG-05's default assumption), monthly series =
  differences of the tool's churn-adjusted delta over k months; predicted cost change 0 (the calc-spec has no demand
  response), so margin moves with revenue.
- **4c-4 KPI-09.** In ops `realized-check` (local, free): approve one ACT-2, compare predicted vs observed revenue
  and margin; error = |predicted - observed| / |observed|, target <= 10%; report it, then tick M5-04.
  Built (run 182): ops `realized-check` approves `plan/growth` (+10% add-on, id `act-kpi09-growth`) next to the
  ACT-1/ACT-3 picks and prints `kpi09` (`mc_agents.kpi09.backtest_plan_change`); observed = the action's summed
  `revenue_delta_usd` and `saved_usd + revenue_delta_usd` over all its days. Local result (seed 42, 150 tenants,
  2026-09-01..10-31): revenue predicted $46,890.96 vs observed $38,151.13, **error 22.9% (misses 10%)**; margin
  $46,890.96 vs $46,623.12, error 0.6%. Cause: the prediction starts at approval, the simulated price takes effect
  after the adoption lag (2026-09-18); October alone is within 4%. The margin match is partly luck (the demand cut's
  cost saving offsets the lag). Not tuned: using the simulator's lag would make the backtest circular. Churn is not
  compared: the simulator has no ACT-2 churn response yet (4c-1 left it out).

- **4c-5 Explicit effective date (run 185, auto-decided under AGENTS.md §8.2).** An ACT-2 approval carries
  `notice_days` (record field, default 0); its effective date = approval + notice (`m5_effects.effective_on`). The plan
  price applies on invoices from that day with no adoption lag (a price change is dated, not adopted); demand responses
  ramp in from it plus the lag. The KPI-09 prediction starts on the same date, so both sides price the same days. Not
  circular: the date is a declared field of the action, known at approval; the hidden lag, realization and demand
  parameters stay out of the prediction. Expected (local, seed 42, growth, 2026-09-01..10-31): predicted $46,890.96 vs
  about $47,494 observed, error about 1.3% (the prediction's 200 bps/month churn; the simulator has no ACT-2 churn).
  Options: (a) predict from approval plus the simulator's lag (rejected: circular); (b) score only full-effect months
  (rejected: hides the start-up gap instead of fixing the dates); (c) explicit effective date (recommended).

- **4c-6 Declared demand response (run 186, auto-decided under AGENTS.md §8.2).** After 4c-5 the margin error was
  16.2%: the observed margin includes the demand cut's LLM cost saving, the prediction had none. Now the ACT-2 declares
  an expected usage drop (`volume_change_bps`; realized-check: 1000 = unit price elasticity on the 10% uplift, an
  assumption) and the prediction prices each plan tenant's LLM cost of the calendar month before the effective date
  (base run, known at approval) at (1 - drop) through the same `price_plan` tool (`after.cost_cents`), churn-adjusted.
  Local (seed 42, growth, 2026-09-01..10-31, synthetic): revenue $46,890.96 vs $47,494.27, **error 1.3%**; margin
  $59,018.64 vs $55,966.26, **error 5.5%, passes**. The prediction overshoots because it applies the full drop from
  day one; the simulator ramps it in. Options: (a) score margin net of the cost side (rejected: weakens KPI-09 to the
  revenue error); (b) predict with the simulator's 12% and lag (rejected: circular); (c) a declared, independent
  demand assumption on the pre-period cost (recommended).

Options considered: (a) backtest on the existing feature-level ACT-2 (rejected: no revenue moves, so the revenue
error is undefined); (b) predict with the simulator's own parameters (rejected: circular, the error would be ~0);
(c) the steps above (recommended: independent prediction, closed-loop observation, no cost).
