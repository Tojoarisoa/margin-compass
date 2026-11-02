# Runbook: M0-07 AWS account setup and foundation deploy

**Who:** the owner, once per AWS account. **Time:** about 45 minutes of clicking and typing, plus up to 24 hours of waiting for billing data.
**Result:** a fresh AWS account with budgets, a kill switch, anomaly alerts, a daily FOCUS 1.2 bill export, and a GitHub deploy role, all from code (`infra/`). Only your sign-in identity is created by hand.

Tick each box as you go. Every step says where to click, what to type, and what you should see. **Console** links open the AWS console (sign in first); **Docs** links are AWS's own instructions for the same step. If a console link has moved, the docs link shows the current path.

---

## Part A: Create and secure the account (console, ~20 min)

- [ ] **A1. Sign up on the Paid plan.**
  Open the [AWS sign-up page](https://portal.aws.amazon.com/billing/signup). When asked to choose a plan, pick **Paid plan**.
  *Why:* the Free plan closes the account after 6 months (VER-01). The Paid plan still gets Free Tier credits and only charges what you use, and our budget caps everything at $5.
  ✅ You land on the AWS console home page.

- [ ] **A2. Don't join AWS Organizations.** Skip any prompt to create or join an organization; it ends Free Tier credits (VER-01).

- [ ] **A3. Turn on MFA for the root user.**
  Console: [IAM → Security credentials](https://console.aws.amazon.com/iam/home#/security_credentials) → **Assign MFA device** → choose an authenticator app or passkey.
  Docs: [Enable MFA for the root user](https://docs.aws.amazon.com/IAM/latest/UserGuide/enable-mfa-for-root.html).
  Do **not** create root access keys.
  ✅ The page shows one MFA device and no access keys.

- [ ] **A4. Let IAM users see billing, and set alternate contacts.** *(still as root)*
  Console: [Account](https://console.aws.amazon.com/billing/home#/account) → **IAM user and role access to Billing information** → **Edit** → **Activate**. On the same page, fill in **Alternate contacts**.
  Docs: [Activate IAM access to billing](https://docs.aws.amazon.com/cost-management/latest/userguide/control-access-billing.html), [Alternate contacts](https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-update-contact-alternate.html).
  ✅ The setting shows **Activated**.

- [ ] **A5. Create your admin IAM user (no access keys).**
  Console: [IAM → Users → Create user](https://console.aws.amazon.com/iam/home#/users/create).
  1. User name: `mc-admin`. Tick **Provide user access to the AWS Management Console**, choose **I want to create an IAM user**, set a password.
  2. Permissions: **Attach policies directly** → `AdministratorAccess` (it includes `SignInLocalDevelopmentAccess`, which `aws login` needs).
  3. Create the user, sign out of root, and sign in as `mc-admin` using the sign-in URL shown.
  4. Add MFA for `mc-admin` the same way as A3 ([docs](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa_enable_virtual.html)).
  Docs: [Create an IAM user](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html).
  Do **not** create access keys; AGENTS.md rule 8 forbids long-lived keys.
  ✅ You're signed in as `mc-admin` with MFA, and [Billing and Cost Management](https://console.aws.amazon.com/costmanagement/home) opens without an access error (thanks to A4). Use this user from now on, never root.

- [ ] **A6. Enable Cost Explorer.** *(as `mc-admin`)*
  Console: [Cost Explorer](https://console.aws.amazon.com/costmanagement/home#/cost-explorer) → **Launch Cost Explorer** if prompted.
  Docs: [Enabling Cost Explorer](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-enable.html).
  Note: this can automatically create an "AWS services" anomaly monitor. That's fine; the deploy script detects and reuses it.
  ✅ Cost Explorer opens (data can take up to 24 hours to appear in a new account).

---

## Part B: Install the tools on your Mac (~10 min)

- [ ] **B1. AWS CLI 2.32.0 or later** (not installed on this Mac yet).
  Docs: [Install or update the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (macOS → command-line installer).
  ✅ `aws --version` prints `aws-cli/2.32.0` or higher.

- [ ] **B2. Node.js** for the CDK CLI. Already installed here (`node --version`). Otherwise: [nodejs.org/download](https://nodejs.org/en/download).

- [ ] **B3. uv** for Python. Already installed here (`uv --version`). Otherwise: [uv installation](https://docs.astral.sh/uv/getting-started/installation/).

---

## Part C: Sign in from the terminal, no access keys (~2 min)

- [ ] **C1.** Run:

  ```bash
  aws login --profile mc-admin
  ```

  When it asks for a Region, enter `us-east-1`. Your browser opens; choose your `mc-admin` session and return to the terminal.
  Docs: [Login with console credentials](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html).
  ✅ `aws sts get-caller-identity --profile mc-admin` shows `...:user/mc-admin`.
  Sessions refresh automatically for up to 12 hours; after that, run `aws login --profile mc-admin` again.

---

## Part D: Preflight checks (~2 min)

- [ ] **D1.** From the repository root:

  ```bash
  infra/scripts/preflight.sh
  ```

  It only reads; it changes nothing. It checks your tools and sign-in, warns about static keys, looks for an existing anomaly monitor (one Cost Explorer API call, at most $0.01), checks whether CDK is bootstrapped, and shows your Lambda quotas.
  ✅ Every line shows ✓, or ! with an explanation.

- [ ] **D2. Lambda quotas.** If the table in D1 shows concurrent executions far below 1,000 or a memory limit below 6,144 MB, request an increase.
  Console: [Service Quotas → AWS Lambda](https://us-east-1.console.aws.amazon.com/servicequotas/home/services/lambda/quotas). Docs: [Requesting a quota increase](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html).
  Not needed until M2, so you can continue while a request is pending.

---

## Part E: Record Bedrock prices for ADR-003 (~5 min)

- [ ] **E1.** Open the [Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) or the [AWS Pricing Calculator](https://calculator.aws/) for **US East (N. Virginia)**, and copy the per-1M-token prices into the table below (paste it into a message):

  | Model ID | Input | Output | Cache read | Cache write | Batch input | Batch output |
  | --- | --- | --- | --- | --- | --- | --- |
  | `amazon.nova-micro-v1:0` | | | | | | |
  | `anthropic.claude-haiku-5-5` | | | | | | |
  | `anthropic.claude-haiku-4-5-20251001-v1:0` | | | | | | |
  | `amazon.titan-embed-text-v2:0` | | — | — | — | | — |

  You can also browse the models in the [Bedrock model catalog](https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/model-catalog). If the console asks you to enable model access, enable only these four.

---

## Part F: Deploy the foundation (~5 min)

- [ ] **F1.** From the repository root, with your real e-mail:

  ```bash
  ALERT_EMAIL=you@example.com infra/scripts/deploy-foundation.sh
  ```

  The script runs the 21 tests, reuses an existing anomaly monitor if there is one, bootstraps CDK the first time ([what bootstrapping is](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html)), and deploys `mc-shared-foundation`. CDK lists the IAM changes and asks **"Do you wish to deploy these changes (y/n)?"**: review and answer `y`.
  Your e-mail is passed at deploy time and never committed.
  ✅ It ends with `✓ Deployed` and prints an output named `GitHubDeployRoleArn`.

---

## Part G: After the deploy

- [ ] **G1. Confirm the alert e-mail (required).** AWS sends "AWS Notification - Subscription Confirmation" to your address. Click **Confirm subscription**. Until you do, no budget or anomaly alert reaches you.
  Check: [SNS → Subscriptions](https://us-east-1.console.aws.amazon.com/sns/v3/home?region=us-east-1#/subscriptions) shows the subscription as **Confirmed**. Docs: [SNS e-mail subscriptions](https://docs.aws.amazon.com/sns/latest/dg/sns-email-notifications.html).

- [ ] **G2. Check what was created.**

  | What | Where to look | You should see |
  | --- | --- | --- |
  | Stack | [CloudFormation](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks) | `mc-shared-foundation` in `CREATE_COMPLETE` |
  | Budget | [Budgets](https://console.aws.amazon.com/costmanagement/home#/budgets) ([docs](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)) | `mc-shared-foundation-monthly-total`, $5.00, three alerts |
  | Anomaly alerts | [Cost Anomaly Detection](https://console.aws.amazon.com/costmanagement/home#/anomaly-detection/overview) ([docs](https://docs.aws.amazon.com/cost-management/latest/userguide/getting-started-ad.html)) | Subscription `mc-shared-foundation-anomaly-alerts`, immediate, ≥ $1 |
  | Bill export | [Data Exports](https://console.aws.amazon.com/costmanagement/home#/bcm-data-exports) ([docs](https://docs.aws.amazon.com/cur/latest/userguide/what-is-data-exports.html)) | `mc-shared-foundation-focus-1-2`, FOCUS 1.2, Parquet |

- [ ] **G3. Save the deploy role for GitHub.** Copy the `GitHubDeployRoleArn` output and store it as a repository variable (used by CI in M1-08):

  ```bash
  gh variable set AWS_DEPLOY_ROLE_ARN --repo Tojoarisoa/margin-compass --body "arn:aws:iam::<account>:role/mc-shared-foundation-github-deploy"
  ```

- [ ] **G4. Activate cost allocation tags (after up to 24 hours).** The five tags appear in Billing only after resources carrying them have been billed. Then run:

  ```bash
  infra/scripts/activate-cost-tags.sh
  ```

  or tick them in [Billing → Cost allocation tags](https://console.aws.amazon.com/billing/home#/tags) ([docs](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/activating-tags.html)).

- [ ] **G5. First bill export (within about 24 hours).** A Parquet file appears under `focus-1-2/` in the bucket `mc-shared-foundation-billing-<account>` ([S3 console](https://s3.console.aws.amazon.com/s3/buckets)). Billing data, and therefore budget alerts, refresh at least once a day (VER-06).

- [ ] **G6. Tell me it's done**, with the Bedrock prices from Part E. I'll record them in ADR-003 and tick M0-07, which closes M0.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `aws: command not found` or `aws login` unknown | Install or update the AWS CLI to 2.32.0+ (B1) |
| `Not signed in for profile 'mc-admin'` | `aws login --profile mc-admin` (C1); sessions last up to 12 hours |
| Expired-token or access-denied errors right after `aws login` | Remove any `[mc-admin]` section from `~/.aws/credentials`; static keys there override the login session |
| Deploy fails on `AWS::CE::AnomalyMonitor` ("limit exceeded") | An AWS-services monitor exists but wasn't detected. Find it in [Cost Anomaly Detection](https://console.aws.amazon.com/costmanagement/home#/anomaly-detection/overview) → Cost monitors, copy its ARN, and deploy manually: `cd infra && npx aws-cdk@2.1147.0 deploy mc-shared-foundation -c mc:alertEmail=you@example.com -c mc:existingAnomalyMonitorArn=<arn>` |
| No alert e-mails | The SNS subscription isn't confirmed (G1), or billing data hasn't refreshed yet (up to a day) |
| Billing pages show "access denied" as `mc-admin` | Step A4 wasn't completed (it must be done as root) |

## Kill switch (from M1)

When workload roles exist, list them in `mc:killSwitchRoleNames` in `infra/cdk.json` and redeploy. At $5 actual spend, Budgets attaches the deny policy `mc-shared-foundation-kill-switch-deny` automatically; it resets at the next budget period. To lift it early, detach that policy from the roles. Code-level LLM caps (AGENTS.md rule 6) stay the first line of defense because billing lags.

## Rollback

`cd infra && npx aws-cdk@2.1147.0 destroy mc-shared-foundation` removes everything except the billing bucket, which is kept so billing history isn't lost. Delete it by hand only if you mean to.

## What the stack creates (`mc-shared-foundation`, us-east-1)

| Resource | Purpose | Cost |
| --- | --- | --- |
| SNS topic `mc-shared-foundation-alerts` + your e-mail | Budget and anomaly alerts | $0 (free tier) |
| Budget `mc-shared-foundation-monthly-total` | Alert at $3 actual; $5 forecast and actual | $0 (monitoring is free) |
| Managed policy `mc-shared-foundation-kill-switch-deny` + Budgets execution role | Kill switch: denies `bedrock:*` and `states:StartExecution` | $0 |
| Budgets action (only when `mc:killSwitchRoleNames` is set, from M1) | Attaches the deny policy to workload roles at $5 actual | $0 (first 2 action-enabled budgets free) |
| Cost Anomaly Detection subscription (and monitor if none exists) | Immediate SNS alert for anomalies ≥ $1 | $0 |
| S3 bucket `mc-shared-foundation-billing-<account>` + FOCUS 1.2 export | Real AWS bill, daily, Parquet (source S7, ADR-015) | < $0.01/month storage |
| GitHub OIDC provider + role `mc-shared-foundation-github-deploy` | CI deploys without access keys; trusts `repo:Tojoarisoa/margin-compass:ref:refs/heads/main` only, and may only assume CDK bootstrap roles | $0 |

**Cost delta: ≈ $0.00–0.01/month.** CDK bootstrap adds a staging bucket and ECR repository (pennies). Each preflight or deploy run makes one Cost Explorer API call (at most $0.01).

## Sources (checked 2026-11-02/03)

- AWS Data Exports: [FOCUS 1.2 table](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-focus-1-2-aws.md), [columns](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-focus-1-2-aws-columns.html), [bucket policy](https://docs.aws.amazon.com/cur/latest/userguide/dataexports-s3-bucket.html), [CloudFormation export](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bcmdataexports-export.html)
- AWS Budgets: [BudgetsAction](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-budgets-budgetsaction.html), [action role](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-action-role.html), [example policies](https://docs.aws.amazon.com/cost-management/latest/userguide/billing-example-policies.html), [pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/)
- Cost Anomaly Detection: [AnomalySubscription](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ce-anomalysubscription.html), [default monitor for new Cost Explorer users](https://aws.amazon.com/blogs/aws-cloud-financial-management/new-aws-cost-explorer-users-can-now-automatically-detect-cost-anomalies-2/), [Cost Explorer API pricing](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/)
- IAM and CLI: [create an OIDC provider](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html), [`aws login`](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html), [`export-credentials`](https://docs.aws.amazon.com/cli/latest/reference/configure/export-credentials.html), [`update-cost-allocation-tags-status`](https://docs.aws.amazon.com/cli/latest/reference/ce/update-cost-allocation-tags-status.html)
- [aws-cdk-lib 2.275.0 on PyPI](https://pypi.org/project/aws-cdk-lib/); CDK CLI 2.1147.0 (npm)
