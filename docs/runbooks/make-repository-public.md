# Runbook: make the repository public (planned for M6)

The repository starts **private** (owner decision, 2026-11-03). Before switching it to public:

1. **Secrets:** scan the full history, not just the latest commit (for example `gitleaks detect --log-opts="--all"`). Any hit means rotating that secret, not just deleting the line. The design keeps secrets in SSM and uses OIDC, so this should find nothing.
2. **Personal data in history:** commit author e-mails become public. Check `git log --format='%an <%ae>' | sort -u` and confirm you're comfortable with every address shown.
3. **Account-specific values:** no AWS account IDs, alert e-mails, or ARNs committed (they are passed with `-c` at deploy time).
4. **Synthetic labeling:** README and dashboard state that BoonCore and its data are synthetic, and nothing is medical advice (AGENTS.md rule 10, ADR-017).
5. **License:** add a `LICENSE` file if you want others to reuse the code.
6. **CI:** public repositories run standard GitHub-hosted runners for free; private ones draw on the $12/month GitHub Free allowance. Nothing in AWS changes: the deploy role trusts `repo:Tojoarisoa/margin-compass:ref:refs/heads/main` either way.
7. **Branch protection:** require pull requests and passing checks on `main` before the first outside contributor can open one.
