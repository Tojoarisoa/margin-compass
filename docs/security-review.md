# Security review (M6-03)

First pass, autopilot run 124 (2026-11-11). Scope: what the code and IaC on `main` say, read in this pass. Nothing
here was probed on the live stack; the kill-switch game day and a live red-team run are still to do.

## Findings

| # | Area | Finding | Severity | Status |
| --- | --- | --- | --- | --- |
| 1 | Public API | `POST /api/ask` on the default path (one-node analyst, `MC_GRAPH` off) did not run the AG-01 intake rules; only the graph did. | Medium | Fixed in PR #285: injection, authority bypass and SQL attack get 400 `blocked` before any job, rate-limit hit, spend or model call. |
| 2 | Intake | "Approve this price change yourself" passed the authority-bypass rule (it allowed only "it"/"this" before "yourself"). | Medium | Fixed in PR #283 (found by the EV-09 set). |
| 3 | Retrieval | Instructions inside a retrieved document (contract-borne injection) reached the model as tool output. | Medium | Fixed in PR #284: instruction-like passages are withheld. |
| 4 | Intake | The `secrets` rule matches the bare word "token(s)", so graph-path questions about token usage are blocked. | Low (availability) | Open, Waiting for owner (narrowing it loosens a guardrail). The public ask path skips this one rule. |
| 5 | Deploy role | `cloudfront:CreateInvalidation` on `distribution/*` (all distributions in the account), not only the dashboard's. | Low | Fixed (2026-11-12): the grant now requires the distribution's `project` tag to be `margin-compass` (`aws:ResourceTag/project`; the web stack deploys before the foundation stack, so its ID can't be referenced). Tag-condition support for `CreateInvalidation` read from a copy of the Service Authorization Reference (iam-dataset); AWS docs unreachable from the cloud session. |
| 6 | CSP | `style-src 'self' 'unsafe-inline'`. Scripts stay `'self'` only, so this does not allow script injection. | Low | Accepted for now (inline styles in the dashboard build). |
| 7 | Verifier (AG-08) | An answer citing an evidence ID that is not in the ledger (for example "[E1]" with nothing retrieved) was verified; only figures and the presence of one real citation were checked. | Medium | Fixed in PR #319: unknown `[E<n>]` citations fail verification (analyst revises, graph retries, then fails closed). Found in run 129 while testing #318. |

## What was checked

- **Git history secret scan (2026-11-12, full history of `main` and all fetched branches, 560 commits on `main`):**
  every diff searched for AWS access key IDs (`AKIA`/`ASIA`), private key blocks, GitHub tokens (`ghp_`,
  `github_pat_`, ...), Slack tokens, Anthropic/OpenAI-style keys, Google API keys, inline AWS secret keys and
  quoted password/secret assignments; also 12-digit account IDs, e-mail addresses and committed `.env`/`.pem`/key
  files. No match: the only account IDs are the test placeholders (`123456789012`), every commit identity is the
  GitHub noreply address. Pattern scan only (no entropy scoring; gitleaks could not be fetched in the cloud session).

- **IAM (infra/margin_compass_infra):** allow statements name `mc-*` resources or single ARNs: lake prefixes,
  the core table, the agent and embedding model ARNs, the function's own ARN, the `mc-*` log groups and state
  machines. Two `*` resources: the kill switch's **deny** (`bedrock:*`, `states:StartExecution`), and the ops role's
  read-only `ReadCosts` (`ce:GetCostAndUsage`, `bcm-data-exports:ListExports`, `ListExecutions`). Checked
  2026-11-12 (Service Authorization Reference, iam-dataset copy): `ListExports` has no resource type and
  `GetCostAndUsage` only an optional billing view, so both need `*`; `ListExecutions` takes an `export` ARN, whose
  ID AWS generates, so it stays in the same statement (list only, no data). Service principals writing to the lake, the billing bucket and the
  alert topic are pinned to this account (`aws:SourceAccount` / `aws:SourceArn`). The budget action may attach and
  detach only the kill-switch policy, only on `mc-*` roles. The deploy role assumes the CDK bootstrap roles (standard).
- **OIDC trust:** GitHub deploy and ops roles require `aud = sts.amazonaws.com` and an exact `sub` (StringEquals).
  Not changed in this review.
- **Public endpoints:** the Lambda function URL uses `AWS_IAM` auth behind CloudFront OAC, so it is reachable only
  through the distribution. `POST /api/ask`: body size cap, 300-character question, control characters stripped,
  intake (#285), per-client hourly limit, global spend guard, per-question call and dollar caps, async worker never
  retried. `GET /api/jobs/{id}`: 32-hex job IDs (uuid4), job records expire after one day; the public response
  omits cost, call count and model. `POST /api/approvals`: owner only (Cognito access token, claim checks, then
  `GetUser`, which also catches revoked tokens). `GET /api/owner-config`, `GET /api/health`: no data.
- **Owner sign-in:** Cognito user pool with no self sign-up, SRP only (no OAuth flows or hosted UI), token
  revocation on, one-hour access and ID tokens, deletion protection; tokens kept in memory only in the dashboard.
- **Browser:** CSP `default-src 'self'`, `script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`,
  `connect-src` adds only Cognito; HSTS one year, `X-Frame-Options: DENY`, `nosniff`, strict referrer policy.
- **Agents:** tools are read-only; SQL goes through the guarded `query_gold` (SELECT only, allow-listed marts,
  row cap); every user-visible number comes from a tool and the ledger; EV-09 red-team set gates CI (#283).

## Not done yet

- Kill-switch game day (attach the deny policy on purpose, confirm Bedrock and Step Functions fail closed, detach).
- A live red-team run against the deployed API (the CI set checks the rules, not the live stack).
- Secret scanning of the full history (not re-run in this pass).
