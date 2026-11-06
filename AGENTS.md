# AGENTS.md: Operating Manual for AI Coding Agents

This file tells any AI agent (Claude Code, Codex, Cursor, etc.) how to work in this repository. Humans are welcome to read it too.

## 1. Read order (mandatory before any task)

1. `PLAN.md` → **Plan at a Glance**: a one-screen summary of every decision.
2. `docs/adr/`: accepted decisions, once they exist. **An accepted ADR overrides the proposed choices in PLAN.md §18.**
3. The PLAN.md section relevant to your task. Use the ID index below so you don't have to read the whole plan.

| If your task touches… | Read |
| --- | --- |
| Business context, customer, pain points | §2, §3, §4 |
| Simulator (BoonCore), ingestion, dbt, contracts | §2.2, §6.2 (Stages 1–3), §7 |
| Models | §6.2 (Stage 4), §13 (EV-02, EV-03, EV-11) |
| RAG / embeddings | §6.2 (Stage 5), §13 (EV-04) |
| Agents, tools, prompts, actions | §8, §13 |
| Dashboard, pricing and lever simulators | §9, §7.5, §13 (EV-12) |
| AWS resources / IaC | §10, §11, §12 |
| CI/CD, environments | §15 |

## 2. Current project state

- **Milestone M1: Walking Skeleton** is closed (2026-11-05): M1-01…M1-08 merged; month-to-date cost $0.0373 (< $0.50).
- **Milestone M2: Cost-to-Serve Platform** is planned and approved (`docs/plans/m2-plan.md`). The owner allowed M2 work to start while the M1 cost check is pending (2026-11-04).
- Deployed (AWS dev, us-east-1): `mc-shared-foundation`, `mc-dev-state`, `mc-dev-data`, `mc-dev-web` (public URL: the `mc-dev-web` `Url` output). Merges to `main` deploy dev through GitHub Actions OIDC (`.github/workflows/ci.yml`). See `infra/` and `docs/runbooks/`.
- State for unattended runs: `docs/progress.md` (§8).
- Work milestones in order (PLAN.md §17). Don't start a milestone until the previous one's exit criteria are met, unless the owner says otherwise.

## 3. Non-negotiable rules

1. **Budget first.** Never add a resource from the forbidden list (PLAN.md §11.2) without an accepted ADR. Tag every resource (`project`, `env`, `stage`, `owner`, `cost-center`). State the cost delta in every PR.
2. **No always-on compute.** Everything must scale to zero. DynamoDB stays in provisioned mode within the free capacity.
3. **No LLM arithmetic.** Every user-visible number comes from a deterministic tool and is recorded in the evidence ledger (PLAN.md §8.6).
4. **Tool before agent.** Do not add a new LLM agent when a tool would do (PLAN.md §5, principle 7). Adding an agent requires an ADR.
5. **Read-only agents.** Tools never mutate any system. Actions (ACT-1 engineering, ACT-2 pricing, ACT-3 account) are simulated records approved by the role that has authority for them (PLAN.md §8.4).
6. **LLM budgets are enforced in code.** Never bypass the budget check, the per-question call cap (≤ 8), or the rate limits.
7. **No live LLM calls in CI.** CI uses replayed fixtures. Re-record them when you change a prompt, graph, or model.
8. **No secrets in the repo.** Use SSM Parameter Store and GitHub OIDC. Never create long-lived access keys.
9. **Quality gates are not optional.** Never weaken a test, evaluation threshold, or guardrail to make a build pass.
10. **Synthetic stays labeled.** Never present synthetic data or results as real.
11. **Verify, don't recall.** Free-tier limits, service availability, model IDs, and prices change. Check official documentation, and record what you verified (and the date) in the relevant ADR (PLAN.md §19.3).
12. **Local-first.** Every feature must run in the `local` environment before it is deployed.
13. **Margin is the north star.** Every feature must move or explain a margin KPI (PLAN.md §4.2). If it doesn't, raise it with the owner before building it.
14. **Quality-guarded savings.** Never recommend or count a cost lever without quality evidence that meets the guardrail (KPI-08).
15. **Dashboard = agents.** Pricing and lever math lives in the shared calculation spec (`calc-spec/`). Change it there and keep the parity tests (EV-12) green.
16. **No prompt or response content in telemetry.** Only metadata and token counts.

## 4. Workflow for a task

1. Take the next unchecked task ID in the current milestone (e.g., `M1-03`), or the one the owner assigns.
2. Check its inputs and outputs against the PLAN.md section it relates to. If something is ambiguous or conflicting, ask the owner.
3. Create a branch: `m<n>/<task-id>-<short-description>` (e.g., `m1/m1-03-revenue-preservation-check`).
4. Deliver code, tests, and docs together (see the Definition of Done).
5. Open a PR that states the task ID, what changed, the cost impact, and test or evaluation results.
6. After merge, tick the task in PLAN.md §17. Add a Change Log entry (§20.3) if scope or architecture changed.

## 5. Definition of Done

- [ ] Implements the task as specified, or the deviation is recorded in an ADR
- [ ] Runs in `local`; unit, data, and replay-evaluation tests pass locally and in CI
- [ ] Infrastructure changes are in IaC only; nothing is created by hand in the console
- [ ] Cost delta estimated, within budget; resources tagged
- [ ] Emits structured logs with `run_id` (PLAN.md §14)
- [ ] Respects the data volume limits (PLAN.md §7.5)
- [ ] Docs updated (README, runbook, data contract, or ADR as relevant)

## 6. Conventions

- **Commits:** Conventional Commits, with the task ID in the scope, e.g. `feat(m1-02): add bronze ingest`.
- **Commit identity:** author and committer are `tojoarisoa <47354538+Tojoarisoa@users.noreply.github.com>` everywhere, including cloud sessions (`.claude/settings.json` sets it at session start). No AI attribution in commits or PRs: no `Co-Authored-By` or `Claude-Session` trailers, no "Generated with/by Claude Code" footers, no session links. The `attribution` CI check enforces this; if a tool adds a footer to a PR description, edit the description to remove it (the check re-runs on edit).
- **AWS resource names:** `mc-<env>-<stage>-<name>` (e.g., `mc-prod-ingest-telemetry`).
- **Data:** snake_case columns; marts are prefixed `fct_`, `dim_`, `agg_`.
- **IDs:** use the plan's IDs in code comments, test names, and PRs where helpful (`AG-03`, `EV-05`, `KPI-04`).
- **Prompts:** versioned files under `agents/prompts/`.
- **ADRs:** `docs/adr/NNN-title.md` with Context, Decision, Alternatives, Consequences, Cost impact, and Verified on (date).

## 7. When to stop and ask the owner

In autopilot mode (§8), the standing approval in §8.2 answers these, except the hard stops in §8.3.

- Any change that could raise monthly cost above $3
- Any open question in PLAN.md §19.4
- Changes to KPI definitions, evaluation thresholds, gold-mart schemas, or the agent topology
- Anything that publishes data externally beyond the existing dashboard

## 8. Autopilot mode (unattended runs)

The owner pre-approved unattended work on 2026-11-04 (this section). It applies when a run is started without the owner present, for example by the cloud scheduled task in `docs/autopilot/scheduled-task-prompt.md`. In an interactive session with the owner, §7 applies as usual.

### 8.1 Loop

1. Read §1's files, then `docs/progress.md`. Take the first open item there, otherwise the next unticked task in PLAN.md §17.
2. Work on a branch `auto/<task-id>-<slug>`. One task per PR; split a large task into PR-sized steps and log the remainder.
3. Run the affected tests and `uvx ruff@0.17.3 check .` locally. Open a PR with `gh api` (the cloud GitHub proxy rejects `gh pr`).
4. Wait for **every** CI check on the PR's head commit to succeed (`gh api repos/{owner}/{repo}/commits/{sha}/check-runs`). Never merge with a failing, pending, or missing check. If CI fails, fix it; after 3 failed attempts, stop (§8.3).
5. Merge by fast-forwarding `main` to the PR head (`git push origin <sha>:main`), which deploys dev through CI. The owner authorized this on 2026-11-04: once CI is green, autopilot merges without asking. "Green" means the latest run of every check on the head commit succeeded; an earlier run of the same check that a re-run superseded (for example `attribution` before a PR-description edit) doesn't count. Wait for the `deploy to dev` job and its smoke test to pass.
6. For AWS checks or live model calls, use the ops workflow (`.github/workflows/ops.yml`, dispatched with `gh api …/actions/workflows/ops.yml/dispatches`). Never use or ask for AWS access keys.
7. Tick PLAN.md §17 and add the Change Log entry, marking decisions **auto-decided under AGENTS.md §8.2**. Append a dated entry to `docs/progress.md` (done, decisions, open items, cost) and rewrite its **Next** section so it lists what is actually next. A commit that changes only `docs/progress.md` may be pushed straight to `main` without a PR (owner, 2026-11-05); everything else goes through a PR.
8. Repeat from step 1 for the next task. **Time budget (owner, 2026-11-06):** don't start a new task once **2 h 15 min** have passed since the run started, and do at most **8 tasks per run**, so a run finishes before the next scheduled run (every 3 h) and two runs never push to `main` at once. End the run earlier at the first hard stop (§8.3), unfixed CI failure, failed deploy or smoke test, or when no unblocked task is left. A large next task is not a reason to stop: split it into PR-sized steps, do the first step as this run's next task, and log the remaining steps under **Next** in `docs/progress.md` (owner, 2026-11-06). A task that seems to need the owner is not a reason to end the run either: if it isn't a §8.3 hard stop, §8.2 decides it ("owner approval" in PLAN.md or `docs/plans/` means §8.2 in autopilot); if it is, write it under **Waiting for owner** and continue with the next task that doesn't depend on it, following the sequencing in `docs/plans/` (owner, 2026-11-06).

**Actions minutes exhausted (owner, 2026-11-06):** the repository is private and the account's GitHub Actions minutes can run out (jobs then fail in 2 s with "recent account payments have failed or your spending limit needs to be increased"). This is **not** a hard stop. Keep working through the loop with these changes: (a) run the whole affected local suite instead of waiting for CI (`uv run pytest -q` in every touched project, `uvx ruff@0.17.3 check .`, plus the cost gate script when `infra/` changes) and merge when it passes; (b) no deploy or smoke test is possible, so don't change anything that needs a deploy to be verified (infra, Lambda image) until minutes are back, and take code-only tasks first; (c) log "CI unavailable (Actions minutes)" and the local results in `docs/progress.md`, and list the unverified merge SHAs under **Waiting for owner** so the next run with working CI re-runs the `ci` workflow on `main` and checks them. The owner plans to make the repository public (unlimited minutes), which ends this case. Every other hard stop still applies.

### 8.2 Standing approval

Where §7 or PLAN.md asks for an owner decision, choose the option you would mark *(Recommended)*, provided it:

- keeps the cost gate's worst-case monthly estimate at or below **$3.00**;
- keeps every evaluation gate and guardrail at least as strict (never weaken tests or guardrails);
- follows PLAN.md, the accepted ADRs, and `docs/plans/` for the milestone.

Record each such decision in the Change Log and in `docs/progress.md`, with the options considered and the reason. The owner may reverse it later.

### 8.3 Hard stops

For each of these, end the task, write the question to `docs/progress.md` under **Waiting for owner**, and don't continue that task. Other independent tasks may continue.

- The cost gate's worst case would exceed $3.00/month, a budget or anomaly alert fired, or the kill switch is active.
- Making the repository public, the M6 launch, or publishing anything beyond what the dashboard already shows and what plan items approved under §8.2 add.
- Deleting or replacing a data store (S3 bucket, DynamoDB table, vector index) or anything with `RemovalPolicy.RETAIN`.
- IAM changes that grant `*` actions, cross-account access, or access outside `mc-*` resources; any change to OIDC trust conditions.
- Anything only the owner can do: AWS console steps, support cases, model-access forms, billing, GitHub plan or settings, secrets.
- Accepting, superseding, or contradicting an ADR, or a choice with no recommended option.
- The same CI or deploy failure after 3 fix attempts, or an AWS deploy that fails or rolls back.
