# Lessons learned (M6-04)

Internal record, written 2026-11-11 from `docs/progress.md` (runs 1-125), the ADRs, and `docs/security-review.md`. Synthetic data throughout: these are lessons about building the platform, not results for a real customer. Plain names are used where this text may be quoted on a public surface later (AGENTS.md §6).

## Cost and budget

- **Code-level caps did the work; billing alarms only confirm it.** Every model call checks a DynamoDB budget counter first (rule 6), so month-to-date spend stayed in cents (M1 closed at $0.0373). AWS billing data lags by hours, so Budgets and the kill switch are the backstop, not the guard.
- **Price the worst case in CI, not the expected case.** The cost gate sums a worst-case monthly estimate per resource type and fails the PR when the baseline is stale or over $3. It turned "is this free?" into a reviewable diff on every infrastructure change.
- **A kill switch needs an app side.** The Budgets action only attaches a deny policy. Reading the IaC for the game day showed nothing paused the API, turned schedules off, or told visitors why, and a denied model call looked like a generic error. Plan the user-visible degraded state together with the IAM control.
- **Reconcile from state, not from messages.** The kill-switch Lambda checks whether the deny policy is attached instead of parsing the alert e-mail text, so a $3 alert or an anomaly notice cannot trip it and running it twice is harmless.

## Evaluation

- **Replayed fixtures make CI free and deterministic, but they freeze prompts.** Every prompt, graph, or model change needs a re-record through the ops workflow, and fixtures recorded with prompt caching off drift when replayed with it on (and the reverse). Record with the same settings CI replays with.
- **Exact replay is the wrong gate for a multi-agent graph.** Eleven runs of prompt tweaks moved the graph replay between 10 and 18 of 27 scenarios without converging: each fix regressed another scenario. Stop such loops early; gate on fewer scenarios per change or on a rubric judge (the judge agreed with the recorded verdicts 92.3% of the time).
- **Golden answers must use only their own evidence.** The first live judge scored 9/13 because four golden answers cited figures the scenario's tools never returned. Fixing the golden set, not the agent, raised it to 13/13.
- **Give the model the schema.** The first evaluation of the SQL tool scored 0/8: the tool had no input schema, so the model invented argument names and tables. Tool descriptions are part of the contract.
- **Prompt length is a cost guardrail.** One retry path costs $0.009965 against a $0.01 per-question cap in its test; a longer prompt would fail it. Keep cost tests close to the cap so they catch prompt bloat.

## Safety and security

- **Every public entry point needs the same intake.** The security review found the public ask path skipped the intake screen that the agent graph ran. A red-team set (30 cases, 22 critical) run in the normal test suite now pins this, and it found one more phrasing that passed intake.
- **Retrieved documents are input, not instructions.** Passages that read like instructions to the agent are withheld (and counted) rather than dropped, so the answer can still say the clause exists.
- **Broad keyword rules have false positives that matter.** A "secrets" rule matching the bare word "token" blocks ordinary cost questions (tokens are the core cost unit). Narrowing it would loosen a guardrail, so it waits for the owner; the public path skips that one rule meanwhile.
- **Telemetry carries metadata only.** Logging token counts and IDs but never prompt or response text made the telemetry lake, the drift checks, and visitor feedback safe to store and share.

## Working unattended

- **Small PRs, every check green on the head commit, fast-forward merges.** One task per PR kept reverts cheap. A green check-run list was not enough: runs that never started don't appear there, so the merge guard also reads the workflow run's jobs.
- **Never move `main` past an open PR.** Two writers (owner and autopilot) on one branch caused repeated "behind main" churn; replaying commits onto a fresh `-r2` branch, never force-pushing, kept history safe at the cost of extra CI runs.
- **CI capacity is a dependency.** Actions minutes ran out once and the runner queue stalled for 40+ minutes another time. The fallback (full local suites, no infra changes until CI returns) kept work moving without merging unverified deploys.
- **Write the "waiting for owner" list as decisions, with options.** Questions phrased as options with a recommendation were answered quickly; open-ended ones waited.
- **Some steps only the owner can do.** Model access forms, console user creation, and billing changes were the long poles; plan around them early and keep the default path working without them (Haiku 4.5 stayed the default while 5.5 access was pending).
