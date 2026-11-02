# Runbook: M0-07 AWS account setup and foundation deploy

Owner-run, once per AWS account. Everything after step 4 is in IaC (`infra/`).
Facts below were checked on 2026-11-02/03; sources at the end.

## What the foundation stack creates (`mc-shared-foundation`, us-east-1)

| Resource | Purpose | Cost |
| --- | --- | --- |
| SNS topic `mc-shared-foundation-alerts` + your e-mail | Budget and anomaly alerts | $0 (free tier) |
| Budget `mc-shared-foundation-monthly-total` | Alert at $3 actual; $5 forecast and actual | $0 (monitoring is free) |
| Managed policy `mc-shared-foundation-kill-switch-deny` + Budgets execution role | Kill switch: denies `bedrock:*` and `states:StartExecution` | $0 |
| Budgets action (only when `mc:killSwitchRoleNames` is set, from M1) | Attaches the deny policy to workload roles at $5 actual | $0 (first 2 action-enabled budgets free) |
| Cost Anomaly Detection subscription (and monitor if none exists) | Immediate SNS alert for anomalies ≥ $1 | $0 |
| S3 bucket `mc-shared-foundation-billing-<account>` + FOCUS 1.2 export | Real AWS bill, daily, Parquet (source S7, ADR-015) | < $0.01/month storage |
| GitHub OIDC provider + role `mc-shared-foundation-github-deploy` | CI deploys without access keys; may only assume CDK bootstrap roles | $0 |

**Cost delta: ≈ $0.00–0.01/month.** CDK bootstrap adds a staging bucket and ECR repository (pennies).

## Steps

### 1. Create the account (console, one time)
1. Sign up for a **new** AWS account and choose the **Paid plan** (the Free plan closes the account after 6 months; VER-01).
2. Do **not** join AWS Organizations (it ends Free Tier credits).
3. Root user: enable MFA; create **no** root access keys; set alternate contacts.
4. Create one IAM user for yourself with console access, MFA, and `AdministratorAccess`. Create **no access keys** (AGENTS.md rule 8). This human identity is the only thing created by hand.
5. Account settings: activate **IAM user and role access to Billing information**.
6. Open **Cost Explorer** once to enable it.

### 2. Local tooling
- AWS CLI ≥ 2.32.0, Node.js, and [uv](https://docs.astral.sh/uv/).
- Sign in without keys: `aws login --profile mc-admin` (browser flow; short-lived credentials). Make sure `~/.aws/credentials` has no static keys for that profile; they would take precedence.
- `export AWS_PROFILE=mc-admin AWS_REGION=us-east-1`

### 3. Pre-deploy checks
1. **Existing anomaly monitor.** Enabling Cost Explorer may have created an "AWS services" monitor, and only one can exist:
   `aws ce get-anomaly-monitors --query 'AnomalyMonitors[].[MonitorName,MonitorArn,MonitorType]'`
   If one is listed with type `DIMENSIONAL`, pass its ARN in step 5 as `-c mc:existingAnomalyMonitorArn=<arn>`.
2. **Lambda memory quota.** New accounts get reduced quotas (VER-12). In Service Quotas → AWS Lambda, check the function memory and concurrency quotas; the pipeline needs up to 6,144 MB (PLAN.md §7.5). Request an increase if lower.
3. **Bedrock prices (VER-05 open item).** In the Bedrock console or the AWS Pricing Calculator (us-east-1), read on-demand input/output, cache-read/write, and batch prices for `amazon.nova-micro-v1:0`, `anthropic.claude-haiku-5-5`, `anthropic.claude-haiku-4-5-20251001-v1:0`, and `amazon.titan-embed-text-v2:0`. Send them to be recorded in ADR-003.
4. **GitHub repository.** The deploy role trusts `repo:Tojoarisoa/margin-compass:ref:refs/heads/main` (`mc:githubRepo` in `infra/cdk.json`). The match is exact and case-sensitive, so it uses the account's canonical casing. It works the same for a private or public repository.

### 4. Bootstrap CDK (one time)
```bash
cd infra
uv sync
npx aws-cdk@2.1147.0 bootstrap aws://$(aws sts get-caller-identity --query Account --output text)/us-east-1
```

### 5. Deploy the foundation
```bash
uv run pytest -q    # 21 synth-time tests must pass first
npx aws-cdk@2.1147.0 deploy mc-shared-foundation \
  -c mc:alertEmail=you@example.com \
  [-c mc:existingAnomalyMonitorArn=arn:aws:ce::...]
```
The e-mail is passed at deploy time and never committed.

### 6. After deploy
1. **Confirm the SNS subscription** from the e-mail AWS sends; alerts don't arrive until you do.
2. **Note the output** `GitHubDeployRoleArn`; it becomes the `AWS_DEPLOY_ROLE_ARN` variable of the GitHub repository (M1-08).
3. **Activate cost allocation tags** once the tags appear in Billing (can take up to 24 hours): Billing → Cost allocation tags → activate `project`, `env`, `stage`, `owner`, `cost-center`.
4. **Check delivery:** the first FOCUS 1.2 file lands under `s3://mc-shared-foundation-billing-<account>/focus-1-2/` within about 24 hours. Billing data, and so budget alerts, refresh at least once a day (VER-06).

### 7. Kill switch (from M1)
When workload roles exist, list them in `mc:killSwitchRoleNames` in `infra/cdk.json` and redeploy. At $5 actual spend, Budgets attaches the deny policy automatically; it resets at the next budget period. To lift it early, detach `mc-shared-foundation-kill-switch-deny` from the roles. Code-level LLM caps (AGENTS.md rule 6) remain the first line of defense because billing lags.

## Rollback
`npx aws-cdk@2.1147.0 destroy mc-shared-foundation` removes everything except the billing bucket (retained so billing history isn't lost). Delete the bucket's objects and the bucket by hand only if you mean to.

## Sources (checked 2026-11-02/03)
- AWS Data Exports: [FOCUS 1.2 table](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-focus-1-2-aws.md), [columns](https://docs.aws.amazon.com/cur/latest/userguide/table-dictionary-focus-1-2-aws-columns.html), [bucket policy](https://docs.aws.amazon.com/cur/latest/userguide/dataexports-s3-bucket.html), [CloudFormation export](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bcmdataexports-export.html)
- AWS Budgets: [BudgetsAction](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-budgets-budgetsaction.html), [action role](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-action-role.html), [example policies](https://docs.aws.amazon.com/cost-management/latest/userguide/billing-example-policies.html), [pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/)
- Cost Anomaly Detection: [AnomalySubscription](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ce-anomalysubscription.html), [default monitor for new Cost Explorer users](https://aws.amazon.com/blogs/aws-cloud-financial-management/new-aws-cost-explorer-users-can-now-automatically-detect-cost-anomalies-2/), no-charge statements in [AWS announcements](https://aws.amazon.com/about-aws/whats-new/2024/05/aws-cost-anomaly-detection-reduces-latency)
- IAM OIDC: [create an OIDC provider](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html) (trusted root CAs; thumbprint only as fallback)
- CLI: [`aws login` announcement](https://aws.amazon.com/about-aws/whats-new/2025/11/console-credentials-aws-cli-sdk-authentication/)
- [aws-cdk-lib 2.275.0 on PyPI](https://pypi.org/project/aws-cdk-lib/); CDK CLI 2.1147.0 (npm)
