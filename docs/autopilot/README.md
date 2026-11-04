# Autopilot: running milestones unattended

Lets a Claude Code **cloud scheduled task** continue PLAN.md's milestones while the owner's computer
is off, with progress visible on a phone. Status: **set up, not enabled**. It's enabled when the owner
completes the steps below.

## How it works

| Piece | Where | Role |
| --- | --- | --- |
| Driver | cloud scheduled task (claude.ai/code/routines), prompt in `scheduled-task-prompt.md` | one task per run, every 3 h |
| Rules | AGENTS.md §8 (owner applies `agents-md-autopilot-draft.md`) | loop, standing approval, hard stops |
| State | `docs/progress.md`, PLAN.md §17 | where the next run picks up; "Waiting for owner" items |
| Deploys | `.github/workflows/ci.yml` on merge to main (OIDC deploy role) | the only path that changes AWS |
| AWS checks, live model calls | `.github/workflows/ops.yml` (OIDC ops role: run and observe, no deploys) | cost report, pipeline run, fixture recording |
| Phone | Claude app **Code** tab (runs), GitHub app (PRs, CI), alert e-mail (budget) | watch and answer |

The cloud sessions never hold AWS credentials. The GitHub proxy rejects `gh pr` and `gh issue` (GraphQL), so runs use `gh api`.

## Owner steps to enable

1. **Rules:** copy `agents-md-autopilot-draft.md` into AGENTS.md (edit as you like) and commit it.
   Claude can't make this change itself: it's the owner's grant of authority.
2. **Ops role:** approve the `mc-shared-foundation` deploy that adds `mc-shared-foundation-github-ops`,
   then set the repository variable `AWS_OPS_ROLE_ARN` to its `GitHubOpsRoleArn` output.
3. **GitHub for cloud sessions:** at claude.ai/code, connect GitHub (Claude GitHub App on this repo,
   or `/web-setup`).
4. **Scheduled task:** create it at claude.ai/code/routines with `scheduled-task-prompt.md`.
5. Optional: GitHub Pro ($4/month) would allow branch protection on this private repo. Without it,
   the "merge only on green CI" rule is procedural, and the deploy job still runs only after every CI job passes.

## Limits

- Runs draw on your Claude subscription usage; when it's exhausted, runs wait for the next window.
- Scheduled tasks are a research preview; a schedule runs at most hourly.
- Some steps always need you (hard stops, AGENTS.md §8.3), for example AWS console steps or model-access forms.
