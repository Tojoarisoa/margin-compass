# DRAFT for the owner: AGENTS.md autopilot section

> Not in effect. This is a proposal. It takes effect only when the owner copies it into AGENTS.md
> (a new §8, plus the one-line note under §7). Edit it as you like first.

**Add under "## 7. When to stop and ask the owner" (first line):**

> In autopilot mode (§8), the standing approval in §8.2 answers these, except the hard stops in §8.3.

**Append as a new section:**

## 8. Autopilot mode (unattended runs)

The owner pre-approved unattended work on <date> (this section). It applies when a run is started without the owner present, for example by the cloud scheduled task in `docs/autopilot/scheduled-task-prompt.md`. In an interactive session with the owner, §7 applies as usual.

### 8.1 Loop

1. Read §1's files, then `docs/progress.md`. Take the first open item there, otherwise the next unticked task in PLAN.md §17.
2. Work on a branch `auto/<task-id>-<slug>`. One task per run; split a large task into PR-sized steps and log the remainder.
3. Run the affected tests and `uvx ruff@0.17.3 check .` locally. Open a PR with `gh api` (the cloud GitHub proxy rejects `gh pr`).
4. Wait for **every** CI check on the PR's head commit to succeed (`gh api repos/{owner}/{repo}/commits/{sha}/check-runs`). Never merge with a failing, pending, or missing check. If CI fails, fix it; after 3 failed attempts, stop (§8.3).
5. Merge by fast-forwarding `main` to the PR head (`git push origin <sha>:main`), which deploys dev through CI. Wait for the `deploy to dev` job and its smoke test to pass.
6. For AWS checks or live model calls, use the ops workflow (`.github/workflows/ops.yml`, dispatched with `gh api …/actions/workflows/ops.yml/dispatches`). Never use or ask for AWS access keys.
7. Tick PLAN.md §17 and add the Change Log entry, marking decisions **auto-decided under AGENTS.md §8.2**. Append a dated entry to `docs/progress.md` (done, decisions, open items, cost), then end the run.

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
