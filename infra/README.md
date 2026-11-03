# infra/: AWS CDK v2 (Python)

Infrastructure as code for Margin Compass (ADR-005). Nothing is created by hand except the owner's sign-in identity.

| Path | What |
| --- | --- |
| `app.py` | CDK app; applies mandatory tags and the forbidden-resource guard to every stack |
| `margin_compass_infra/foundation_stack.py` | `mc-shared-foundation`: budgets, kill switch, anomaly alerts, FOCUS 1.2 export, GitHub OIDC (M0-07) |
| `margin_compass_infra/state_stack.py` | `mc-dev-state`: DynamoDB core table, provisioned 2/2 (model registry M1-04; agent jobs, budgets, rate limits M1-07) |
| `margin_compass_infra/data_stack.py` | `mc-dev-data`: S3 lake (§7.1 retention), the pipeline Lambda (container, 2 GB, 10 min), S3 Vectors knowledge index (M1-02, M1-05) |
| `margin_compass_infra/web_stack.py` | `mc-dev-web`: CloudFront (S3 + Lambda OAC) for the dashboard, `publish/` snapshots, and the agent API Lambda (M1-07) |
| `margin_compass_infra/guardrails.py` | Synth fails on any PLAN.md §11.2 forbidden resource unless an accepted ADR allows it |
| `margin_compass_infra/tagging.py` | `project`, `env`, `stage`, `owner`, `cost-center` on every taggable resource |
| `margin_compass_infra/config.py` | Typed config from `cdk.json` context |
| `tests/` | Synth-time tests; no AWS account needed |
| `scripts/preflight.sh` | Read-only checks before deploying (tools, sign-in, existing anomaly monitor, bootstrap, Lambda quotas) |
| `scripts/deploy-foundation.sh` | Tests, bootstraps if needed, deploys `mc-shared-foundation` (`ALERT_EMAIL=… scripts/deploy-foundation.sh`) |
| `scripts/activate-cost-tags.sh` | Activates the five mandatory tags as cost allocation tags |
| `scripts/deploy-dashboard.sh` | Builds `dashboard/` (`npm ci`, audit, build) and syncs it to the lake's `site/`, then invalidates CloudFront |

```bash
uv sync
uv run pytest -q                                   # local, offline
npx aws-cdk@2.1147.0 synth -c mc:alertEmail=you@example.com   # signed in (aws login); offline: CDK_DEFAULT_ACCOUNT=000000000000
```

Deploy order for app stacks: `mc-dev-state` → `mc-dev-data` → `mc-dev-web` → `mc-shared-foundation` (the kill switch names roles from the app stacks), then `scripts/deploy-dashboard.sh`. Pass `-c mc:alertEmail=…` and, if the account has an AWS-created anomaly monitor, `-c mc:existingAnomalyMonitorArn=…`.

Deploying the foundation: follow [`docs/runbooks/m0-07-aws-account-setup.md`](../docs/runbooks/m0-07-aws-account-setup.md).

Naming: `mc-<env>-<stage>-<name>`. Account-wide resources use `env = shared`.
