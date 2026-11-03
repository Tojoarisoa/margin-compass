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

- **Milestone M1: Walking Skeleton** (started 2026-11-03; M0 exit criteria met that day).
- Deployed: the account-wide foundation stack `mc-shared-foundation` (budgets, kill-switch policy, anomaly alerts, FOCUS 1.2 export, GitHub OIDC deploy role). See `infra/` and `docs/runbooks/m0-07-aws-account-setup.md`.
- Application code starts with M1-01 (`simulator/`).
- Work milestones in order (PLAN.md §17). Don't start a milestone until the previous one's exit criteria are met, unless the owner says otherwise.
- **M1 is a walking skeleton:** keep every stage thin. Do not deepen a single stage during M1.

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
- **AWS resource names:** `mc-<env>-<stage>-<name>` (e.g., `mc-prod-ingest-telemetry`).
- **Data:** snake_case columns; marts are prefixed `fct_`, `dim_`, `agg_`.
- **IDs:** use the plan's IDs in code comments, test names, and PRs where helpful (`AG-03`, `EV-05`, `KPI-04`).
- **Prompts:** versioned files under `agents/prompts/`.
- **ADRs:** `docs/adr/NNN-title.md` with Context, Decision, Alternatives, Consequences, Cost impact, and Verified on (date).

## 7. When to stop and ask the owner

- Any change that could raise monthly cost above $3
- Any open question in PLAN.md §19.4
- Changes to KPI definitions, evaluation thresholds, gold-mart schemas, or the agent topology
- Anything that publishes data externally beyond the existing dashboard
