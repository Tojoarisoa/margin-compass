# dashboard/: Margin Compass dashboard

PLAN.md §9, ADR-009. **M1-07** ships **PG-1 Executive Margin Overview v0** and an Ask box for the
Cost-to-Serve Analyst. All data is synthetic.

```bash
cd dashboard
npm ci                 # exact pins, lockfile, no install scripts (.npmrc)
npm run dev            # copies ../data/local/publish/latest/pg1.json, then serves on :5173
npm run build          # type-check + production build into dist/
```

Deploy: `infra/scripts/deploy-dashboard.sh` (after `mc-dev-data` and `mc-dev-web`).

| Path on the distribution | Source | Notes |
| --- | --- | --- |
| `/` | lake `site/` (this build) | hashed assets cached 1 year; `index.html` revalidates |
| `/publish/latest/pg1.json` | lake `publish/` (pipeline publish step) | schema `pg1.v0`, ≤ 200 KB (§7.5), cached 5 minutes |
| `/api/ask`, `/api/jobs/<id>` | agent API Lambda (OAC) | POST sends `x-amz-content-sha256` of the body (VER-08); polling (ADR-012) |

The dashboard only formats numbers: every figure comes from the publish step or the agent's tools.
Supply chain (ADR-009): exact versions, committed lockfile, `npm ci`, `npm audit` in the deploy script.
