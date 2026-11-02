# infra/: AWS CDK v2 (Python)

Infrastructure as code for Margin Compass (ADR-005). Nothing is created by hand except the owner's sign-in identity.

| Path | What |
| --- | --- |
| `app.py` | CDK app; applies mandatory tags and the forbidden-resource guard to every stack |
| `margin_compass_infra/foundation_stack.py` | `mc-shared-foundation`: budgets, kill switch, anomaly alerts, FOCUS 1.2 export, GitHub OIDC (M0-07) |
| `margin_compass_infra/guardrails.py` | Synth fails on any PLAN.md §11.2 forbidden resource unless an accepted ADR allows it |
| `margin_compass_infra/tagging.py` | `project`, `env`, `stage`, `owner`, `cost-center` on every taggable resource |
| `margin_compass_infra/config.py` | Typed config from `cdk.json` context |
| `tests/` | Synth-time tests; no AWS account needed |

```bash
uv sync
uv run pytest -q                                   # local, offline
npx aws-cdk@2.1147.0 synth -c mc:alertEmail=you@example.com
```

Deploying: follow [`docs/runbooks/m0-07-aws-account-setup.md`](../docs/runbooks/m0-07-aws-account-setup.md).

Naming: `mc-<env>-<stage>-<name>`. Account-wide resources use `env = shared`.
