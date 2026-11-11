# Alarms runbook

All alarms e-mail the `mc-shared-foundation-alerts` topic (foundation stack). PLAN.md §14 allows at most 10 CloudWatch alarms; the cost gate fails the build above that (`infra/scripts/cost_gate.py`). Missing data never alarms: dev schedules are off, so a quiet function is healthy.

| Alarm | Fires when | First look |
| --- | --- | --- |
| `mc-<env>-data-nightly-failed` | A nightly state-machine run failed, timed out, or was aborted (1 h window). | Step Functions console: the failed execution and the step that failed. |
| `mc-<env>-data-pipeline-errors` | The pipeline Lambda returned an error, timed out, or crashed at least once in an hour (nightly steps, the telemetry export schedule, or an ops run). | Log group `/aws/lambda/mc-<env>-data-pipeline`, filter on `"level": "ERROR"`; every line carries `run_id`. |
| `mc-<env>-web-api-errors` | The agent API Lambda crashed or timed out 3+ times in an hour. Handled answers (4xx, budget refusals, fail-closed answers) are not Lambda errors and don't count. | Log group `/aws/lambda/mc-<env>-web-api`; check for timeouts (60 s) and image start failures. |
| Budget `mc-shared-foundation-monthly-total` | Actual spend reached $3, or $5 actual/forecast (the $5 action attaches the kill-switch deny policy). | Cost Explorer by service; see `m0-07-aws-account-setup.md` for the kill switch. |

## Steps

1. Find the `run_id` in the failing log line, then every line with that `run_id` (no prompt or response content is logged, rule 16).
2. If a deploy caused it, re-run the previous green `main` commit's `ci` workflow (one-step rollback, PLAN.md §15).
3. Fix on a branch with a test that reproduces the failure; never silence an alarm by raising its threshold without an owner decision.
4. Unattended runs (AGENTS.md §8): a fired alarm on the budget is a hard stop (§8.3); a pipeline or API alarm is a normal fix task.

## Telemetry lake (PLAN.md §14)

The daily `telemetry` schedule (`mc-<env>-data-telemetry`, 00:30 UTC, off in dev by default) compacts the previous UTC day into the lake:

- `telemetry/dogfood.parquet`: the agent API's `gen_ai_call` events by day and model (tokens, cost, latency; no content).
- `telemetry/pipeline_runs.parquet`: one row per pipeline `run_id` and day (first/last event time, duration, final status, event and error counts).

Both are idempotent per day. To backfill a day by hand, invoke the pipeline function with `{"profile": "telemetry", "day": "YYYY-MM-DD"}` (via the ops workflow, AGENTS.md §8.1). Log groups keep 7 days, so a day older than that can't be rebuilt.
