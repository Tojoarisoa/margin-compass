# Owner sign-in (M5-03)

The Action Center has two modes. Visitors decide in a browser sandbox (nothing is sent). The owner signs in with
Cognito and their decisions are recorded in the core table, where the closed-loop simulator picks them up.

## What the IaC creates (`mc-dev-web`)

| Resource | Notes | Cost |
| --- | --- | --- |
| Cognito user pool `mc-dev-web-owners` | Lite plan, self sign-up off, no hosted UI, deletion protection on, retained | $0 (free up to 10,000 MAU, VER-02) |
| App client `mc-dev-web-dashboard` | public (no secret), SRP only, 1 h access token, 1 day refresh | $0 |
| Group `owner` | membership is what the API checks | $0 |

The API (`POST /api/approvals`) accepts a decision only with an access token from this pool and client whose user is
in the `owner` group; Cognito `GetUser` validates the token. Each decision is an item `APPROVAL#<action_id>` /
`DECIDED#<time>` in `mc-dev-state-core`, kept without TTL. The newest decision per action wins.

## One-time owner steps (console, not automated)

1. AWS console, us-east-1, Cognito, user pool `mc-dev-web-owners` (pool ID is the `OwnerPoolId` output of `mc-dev-web`).
2. **Create user**: a username of your choice, your e-mail, "Set a password" with a temporary password (14+ characters,
   upper, lower, digit, symbol). Don't send an invitation (the pool sends no e-mail).
3. Open the user, **Add user to group**, choose `owner`.
4. On the dashboard, Action Center, **Owner sign-in**: sign in with the temporary password and choose a new one.
5. Approve or reject one action, then check the item exists (ops workflow or console, table `mc-dev-state-core`,
   PK starting `APPROVAL#`). That round trip ticks M5-03.

To revoke access, remove the user from `owner` or disable the user; tokens expire within an hour.

## Decisions in the simulation (backfill, opt-in)

A backfill started with `{"approvals": true}` in the execution input makes the static step export the latest decision
per action (`mc_agents.owner.export_approvals`, one Scan of the core table filtered on `APPROVAL#`) to
`approvals/approvals.jsonl` in the lake; each month step reads that file and applies the closed-loop effects. Without the
flag the backfill is unchanged. A month step with the flag fails with `no_approvals` if the export is missing. Effects
start at `decided_at`, so a decision made after the simulation window (ends 2026-10-31) changes nothing.
