# Case study: how a fictional AI SaaS recovered 3.56 margin points

**Synthetic.** BoonCore is a simulated company (seed 42). Every number below comes from the deterministic pipeline, not from a model, and none of it is real customer data.

Source: ops `realized-check` run 45766158041 (2026-11-26, main 176c95c). It simulates the window twice with the same seed: a counterfactual run with no actions, and a run with 7 approved actions. KPI-01 is computed by `infra/scripts/ops/kpi01_summary.py` from each run's pg1 snapshot (ratio of sums, Decimal).

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
| Last 30 days (2026-10-02 to 10-31) | 54.42% | 57.98% | **+3.56 pts** |
| Whole window (579 days) | 51.55% | 51.96% | +0.41 pts |

The last 30 days are the fair comparison: actions start taking effect from 2026-09-01 plus an adoption lag, so most of the window predates them. Over the last 30 days AI cost-to-serve fell from $308,780 to $295,343 and AI revenue rose from $677,418 to $702,821 (the `growth` plan price change, net of the simulated demand response and churn).

Realized rows (`fct_realized_margin`): 251 realized, saving $18,332.74 of cost and adding $36,593.94 of revenue; 21 more ($131.46 saved, $10,900.32 revenue) still wait for verification and count as $0.

## Price prediction (KPI-09)

The calc-spec predicted the `growth` plan +10% change before it took effect; the simulation then observed it (150 tenants, 2 months, synthetic).

| | Predicted | Observed | Error | Target |
| --- | --- | --- | --- | --- |
| Revenue | $46,890.96 | $47,494.27 | 1.3% | 10% |
| Margin | $59,018.64 | $55,966.26 | 5.5% | 10% |

KPI-09 passes. It did not at first: the first run missed revenue by 22.9% and margin by 16.2%. Three causes were found and fixed, not tuned away: the prediction and the simulated price used different effective dates; the invoices did not carry the price uplift; and the prediction ignored the drop in usage a price rise causes. The prediction now declares that response (a 10% usage drop, an assumption) instead of borrowing the simulator's own parameters.

## What did not work at first

- **KPI-01 counted cost savings only.** AI revenue was identical in both runs (+1.98 pts), because invoices were written without the approved price change. Invoices now carry the uplift from its effective date, and a tenant churned by an ACT-3 action stops being invoiced from its churn day.
- **The price prediction missed** (see above) until both sides used the same effective date.

## Takeaways

- Allocating cost per request was the step that made the leaks visible; the actions themselves were ordinary.
- Counting only verified savings, against a same-seed counterfactual, keeps the headline honest.
- A pricing prediction needs the same effective date, and an explicit demand assumption, before it can be trusted.
