# Kill-switch game day (M6-03)

Plan for a drill that proves the $5 kill switch (PLAN.md §11.3, item 4) stops model spend and pipeline starts, that the static dashboard stays up, and that lifting it restores service. Written 2026-11-11 by autopilot; **not run yet**.

## What exists today (read from `infra/`, 2026-11-11)

| Piece | State |
| --- | --- |
| Deny policy `mc-shared-foundation-kill-switch-deny` | Deployed. Denies `bedrock:*` and `states:StartExecution` on `*`. |
| Budgets action on `mc-shared-foundation-monthly-total` | Deployed. At $5 actual, `APPLY_IAM_POLICY`, `AUTOMATIC` approval, attaches the deny policy to `mc-dev-data-pipeline`, `mc-dev-web-api`, `mc-dev-data-nightly-scheduler`, `mc-shared-foundation-github-ops`; notifies the alert topic. |
| SNS-triggered Lambda (disable schedules, API concurrency 0, dashboard banner) | **Not built.** PLAN §11.3 lists it; no code in `infra/` or `dashboard/`. Gap G1. |
| API behaviour when Bedrock is denied | `run_job` catches the `AccessDeniedException` as a generic exception: the job ends `error` with "Something went wrong while answering." No "paused" message, and the `web-api-errors` alarm doesn't fire (handled error). Gap G2. |
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

- **G1 (recommended first):** build the SNS-triggered "kill switch on" Lambda from PLAN §11.3: on the budget action notification it sets the API's reserved concurrency to 0, disables the `mc-*` schedules, and writes a `kill_switch.json` flag the dashboard shows as a banner. Lambda + SNS subscription are within the free tier; needs scoped IAM (`lambda:PutFunctionConcurrency` and `scheduler:UpdateSchedule` on `mc-*` only).
- **G2:** map a Bedrock `AccessDeniedException` in the API to status `paused` with a plain message ("The analyst is paused for now."), with a unit test. Code only.
- **G3:** let the drill run unattended: either the owner attaches and detaches in the console (no IAM change), or an ops task that may attach and detach **only** the deny policy (`iam:PolicyARN` condition) **only** to `mc-shared-foundation-github-ops` itself, with detach in an `always()` step. The second option is an IAM change on the ops role; it grants no `*` action and stays inside `mc-*`, so §8.2 covers it, but it is the owner's call whether the ops role should hold any IAM write at all.

## Cost

$0: the drill makes denied calls only; the before/after checks are the existing ops tasks (online-eval at most $0.03 per run).
