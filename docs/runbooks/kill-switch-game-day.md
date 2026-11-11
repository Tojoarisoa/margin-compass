# Kill-switch game day (M6-03)

Plan for a drill that proves the $5 kill switch (PLAN.md §11.3, item 4) stops model spend and pipeline starts, that the static dashboard stays up, and that lifting it restores service. Written 2026-11-11 by autopilot; **not run yet**.

## What exists today (read from `infra/`, 2026-11-11)

| Piece | State |
| --- | --- |
| Deny policy `mc-shared-foundation-kill-switch-deny` | Deployed. Denies `bedrock:*` and `states:StartExecution` on `*`. |
| Budgets action on `mc-shared-foundation-monthly-total` | Deployed. At $5 actual, `APPLY_IAM_POLICY`, `AUTOMATIC` approval, attaches the deny policy to `mc-dev-data-pipeline`, `mc-dev-web-api`, `mc-dev-data-nightly-scheduler`, `mc-shared-foundation-github-ops`; notifies the alert topic. |
| SNS-triggered Lambda (disable schedules, API concurrency 0, dashboard banner) | `mc-dev-web-kill-switch` (G1 step 2, 2026-11-11), subscribed to the alert topic. On any message it checks whether the deny policy is attached to `mc-dev-web-api` (no message parsing; a $3 alert or an anomaly mail changes nothing). Attached: API reserved concurrency 0, enabled `mc-dev-data-nightly`/`-telemetry` schedules disabled, `publish/latest/kill_switch.json` written (private record of what it changed: `kill_switch/state.json`). Detached and engaged: restores exactly that and removes both keys. To lift: detach the policy (reset the budget action), then run ops `kill-switch-sync` (the ops role may invoke only this function; the deny policy does not block it). A deploy while engaged resets the API concurrency to 5 (CloudFormation owns it); invoke the function again after such a deploy. |
| API behaviour when Bedrock is denied | Before the G2 fix, `run_job` caught the `AccessDeniedException` as a generic exception: the job ends `error` with "Something went wrong while answering." No "paused" message, and the `web-api-errors` alarm doesn't fire (handled error). Gap G2. |
| Who can attach the policy outside a real budget breach | Only Budgets (its execution role) or the owner in the console. The ops role has no IAM write. Gap G3. |

## Drill (one target role at a time, shortest first)

Target order: `mc-shared-foundation-github-ops` (only affects the drill itself), then `mc-dev-web-api` (public ask is down while attached: pick a quiet hour, at most 15 min).

1. **Before:** ops `status` (stacks, `/`, `/publish/latest/pg1.json`, `/api/health` all 200). Note the time.
2. **Attach** `mc-shared-foundation-kill-switch-deny` to the target role. Wait 60 s (IAM is eventually consistent).
3. **Expect, ops role:** ops `online-eval` fails with `AccessDeniedException` on the first Converse call; ops `start-nightly` fails on `StartExecution`. No tokens billed.
4. **Expect, API role:** `POST /api/ask` job ends without an answer and without spend (CloudWatch: no `gen_ai_call` event for the job); `/` and `/publish/latest/*` still 200.
5. **Detach** the policy. Wait 60 s. Re-run step 3 or 4: it works again.
6. **Record** in `docs/progress.md`: times attached/detached, each check's result, gaps seen.

Abort: if anything outside the target role breaks, detach at once (step 5). The drill never deletes or replaces a resource and never changes the budget.

## Gaps and proposed fixes (one PR each, after the drill or before it)

- **G1 (step 2 done: `mc-dev-web-kill-switch`, see the table; step 3 done: ops task `kill-switch-sync` lifts it; step 1 done: the dashboard shows "The analyst is paused for now" while `publish/latest/kill_switch.json` has `"active": true`):** build the SNS-triggered "kill switch on" Lambda from PLAN §11.3: on the budget action notification it sets the API's reserved concurrency to 0, disables the `mc-*` schedules, and writes the `publish/latest/kill_switch.json` flag the dashboard shows as a notice (and deletes it when lifted; check that the publish step doesn't sync-delete it). Lambda + SNS subscription are within the free tier; needs scoped IAM (`lambda:PutFunctionConcurrency` and `scheduler:UpdateSchedule` on `mc-*` only).
- **G2 (fixed, PR after #288):** the API maps a Bedrock `AccessDeniedException` to the existing `budget_exceeded` status with the plain "unavailable right now" answer and `error: access_denied` (logged as `job_denied`, a warning), so the dashboard shows "Unavailable right now". Other model errors stay `error`. Step 4 of the drill expects this.
- **G3:** let the drill run unattended: either the owner attaches and detaches in the console (no IAM change), or an ops task that may attach and detach **only** the deny policy (`iam:PolicyARN` condition) **only** to `mc-shared-foundation-github-ops` itself, with detach in an `always()` step. The second option is an IAM change on the ops role; it grants no `*` action and stays inside `mc-*`, so §8.2 covers it, but it is the owner's call whether the ops role should hold any IAM write at all.

## Cost

$0: the drill makes denied calls only; the before/after checks are the existing ops tasks (online-eval at most $0.03 per run).
