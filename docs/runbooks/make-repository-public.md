# Runbook: make the repository public (planned for M6)

The repository starts **private** (owner decision, 2026-11-03). Before switching it to public:

1. **Secrets:** scan the full history, not just the latest commit (for example `gitleaks detect --log-opts="--all"`). Any hit means rotating that secret, not just deleting the line. The design keeps secrets in SSM and uses OIDC, so this should find nothing.
2. **Personal data in history:** commit author e-mails become public. Check `git log --format='%an <%ae>' | sort -u` and confirm you're comfortable with every address shown.
3. **Account-specific values:** no AWS account IDs, alert e-mails, or ARNs committed (they are passed with `-c` at deploy time).
4. **Synthetic labeling:** README and dashboard state that BoonCore and its data are synthetic, and nothing is medical advice (AGENTS.md rule 10, ADR-017).
5. **License:** add a `LICENSE` file if you want others to reuse the code.
6. **CI:** public repositories run standard GitHub-hosted runners for free; private ones draw on the $12/month GitHub Free allowance. Nothing in AWS changes: the deploy role trusts `repo:Tojoarisoa/margin-compass:ref:refs/heads/main` either way.
7. **Branch protection:** require pull requests and passing checks on `main` before the first outside contributor can open one.
8. **Actions logs:** logs of a public repository are public. Repository *variables* are printed in logs (step inputs, `env`, expanded `if:` conditions); *secrets* are masked. Keep account values (role ARNs, alert e-mail, anomaly monitor ARN) in secrets, and delete the workflow runs recorded while the repository was private before switching.
9. **Pull request descriptions and refs:** PR titles, bodies, comments, and every PR head commit (`refs/pull/<n>/head`, even after the branch is deleted) become public. Only GitHub Support can delete a pull request.

**Done 2026-11-06** (owner decision: go public so CI runs on free minutes). Checked: full history of every ref (account ID, alert e-mail, ARNs, key and token patterns, high-entropy strings): clean; commit identities: the owner's noreply address only on `main`; account values moved to secrets; old runs deleted; PR footers removed. Settings: fork PR workflows need approval for all outside contributors, default `GITHUB_TOKEN` read-only, `main` protected against force pushes and deletion, secret scanning with push protection on.
