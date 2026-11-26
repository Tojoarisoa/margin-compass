# Case study: how a fictional AI SaaS recovered 1.98 margin points

**Synthetic.** BoonCore is a simulated company (seed 42). Every number below comes from the deterministic pipeline, not from a model, and none of it is real customer data.

Source: ops `realized-check` run 45749151067 (2026-11-26, main 914b6a7). It simulates the window twice with the same seed: a counterfactual run with no actions, and a run with 7 approved actions. KPI-01 is computed by `infra/scripts/ops/kpi01_summary.py` from each run's pg1 snapshot (ratio of sums, Decimal).

## The company

BoonCore sells an AI add-on to its SaaS tenants. Over the 19-month window (2025-04-01 to 2026-10-31) it bills $10.57M of AI revenue at a 51.55% AI gross margin. Nobody can say which features, tenants or plans lose money, because cost-to-serve is not allocated.

## What Margin Compass did

1. Allocated the cost of every request to a tenant, feature and plan, including shared infrastructure.
2. Ranked margin leaks and proposed actions: ACT-1 engineering fixes, ACT-3 account changes, and one ACT-2 price change.
3. The role with authority approved 7: the top 6 ACT-1/ACT-3 and the `growth` plan +10% (ACT-2). Approval dates are simulated (60 days before the data date, owner decision 2026-11-26).
4. Measured what each action actually returned against the counterfactual.

## Result (KPI-01, AI gross margin)

| Period | Counterfactual | With actions | Change |
| --- | --- | --- | --- |
| Last 30 days (2026-10-02 to 10-31) | 54.42% | 56.40% | **+1.98 pts** |
| Whole window (579 days) | 51.55% | 51.72% | +0.17 pts |

The last 30 days are the fair comparison: actions start taking effect from 2026-09-01 plus an adoption lag, so most of the window predates them. Over the last 30 days AI cost-to-serve fell from $308,780 to $295,343 on unchanged revenue ($677,418).

Realized rows (`fct_realized_margin`): 251 realized, saving $18,332.74 of cost and adding $36,593.94 of revenue; 9 more ($131.46 saved, $1,557.19 revenue) still wait for verification and count as $0.

## What did not work

- **Price prediction (KPI-09): missed.** The calc-spec predicted $46,890.96 of revenue from the plan change; the simulation observed $38,151.13, an error of 22.9% against a 10% target. The margin error was 0.6%. Likely cause (unverified): the prediction starts at approval, while the simulated price starts after the adoption lag. The miss is reported, not tuned away.
- **Price revenue is not in KPI-01 yet.** AI revenue is the same in both runs, so the +1.98 points come from cost savings only; the ACT-2 revenue shows only in the realized rows. Why the invoices do not carry the uplift is not yet checked.

## Takeaways

- Allocating cost per request was the step that made the leaks visible; the actions themselves were ordinary.
- Counting only verified savings, against a same-seed counterfactual, keeps the headline honest.
- A pricing prediction needs the same effective date on both sides before it can be trusted.
