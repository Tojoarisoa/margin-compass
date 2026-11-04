# Scheduled-task prompt (paste into claude.ai/code/routines)

Repository: `Tojoarisoa/margin-compass` · Schedule: every 3 hours (for example `7 */3 * * *`, UTC) · Connectors: none.

```text
You are running Margin Compass in autopilot mode, unattended.

1. Read AGENTS.md. If it has no "## 8. Autopilot mode" section, stop and append to docs/progress.md
   (on a branch, via PR) that autopilot is not enabled. Do nothing else.
2. Follow AGENTS.md §8 exactly: one task per run, PR via `gh api` (not `gh pr`), merge only when every
   CI check on the head commit has succeeded, AWS only through .github/workflows/ops.yml, standing
   approval §8.2, hard stops §8.3.
3. Before starting work, check docs/progress.md "Waiting for owner". Skip blocked items; never retry a
   hard stop the owner hasn't answered.
4. End the run by appending a dated entry to docs/progress.md: task, PR, CI/deploy result, decisions
   (auto-decided under §8.2), cost observed, next task. Keep it short; the owner reads it on a phone.
5. Commit as the repository's configured identity. Never add AI attribution lines to commits or PRs.
```
