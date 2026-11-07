# calc-spec: shared pricing and lever calculation spec (ADR-016, EV-12)

One definition of the pricing math, implemented twice (agent tools in Python, browser simulator in TypeScript) and
checked against the same vectors. Any math change starts here. All data is synthetic.

## Pricing engine v1 (`pricing.md`-level summary)

Money is integer **cents**; usage rates are integer **micro-dollars per unit** (1 USD = 1,000,000); ratios are
integer **basis points**. Only integer arithmetic is used, so every implementation agrees to the cent.

`round_div(n, d)` = round half up of `n / d` for `n >= 0` (`(2n + d) // (2d)`).

Inputs (one tenant, one billing month): `seats`, `seat_price_cents`, `addon_cents` (flat AI add-on),
`included_units`, `overage_rate_micro`, `usage_units`, `outcome_price_micro`, `outcomes`, `usage_cap_cents`
(optional, caps overage plus outcome charges), `discount_bps`, `cost_cents` (AI COGS for the month).

1. `seat_cents = seats * seat_price_cents`
2. `overage_cents = round_div(max(0, usage_units - included_units) * overage_rate_micro, 10000)`
3. `outcome_cents = round_div(outcomes * outcome_price_micro, 10000)`
4. `usage_cents = min(overage_cents + outcome_cents, usage_cap_cents)` (no cap when `usage_cap_cents` is null)
5. `gross_cents = seat_cents + addon_cents + usage_cents`
6. `discount_cents = round_div(gross_cents * discount_bps, 10000)`
7. `revenue_cents = gross_cents - discount_cents`
8. `margin_cents = revenue_cents - cost_cents` (may be negative)
9. `margin_bps` = `null` if `revenue_cents == 0`, else `sign(margin) * round_div(abs(margin_cents) * 10000, revenue_cents)`

Output fields: the names above (`seat_cents` … `margin_bps`).

Vectors: `vectors/pricing_v1.json`, a list of `{name, input, expected}`. Both implementations must match exactly.
Python: `agents/mc_agents/tools/pricing.py`. TypeScript: `dashboard/src/pricing.ts`; EV-12 parity check: `npm run parity` in `dashboard/` (runs in CI).

## Lever replay v1 (engineering levers: routing and caching)

Integer cents and basis points, same `round_div`. Inputs (one feature, one month): `cost_cents` (baseline AI cost),
`route_bps` (traffic share moved to a cheaper tier), `cheap_cost_ratio_bps` (cheaper tier cost per call vs baseline),
`cache_hit_bps` (share of remaining spend avoided by caching), `quality_bps`, `quality_drop_bps` (quality lost at 100%
routing), `guardrail_bps` (largest allowed quality loss), `recall_bps` (safety-event recall), `recall_drop_bps`
(recall lost at 100% routing). Percent-like inputs are at most 10000.

1. `routed_base = round_div(cost * route_bps, 10000)`; `routed_new = round_div(routed_base * cheap_cost_ratio_bps, 10000)`
2. `kept = cost - routed_base`; `cache_saved = round_div((kept + routed_new) * cache_hit_bps, 10000)`
3. `new_cost = kept + routed_new - cache_saved`; `savings = cost - new_cost` (negative if the tier costs more)
4. `quality_loss = round_div(quality_drop_bps * route_bps, 10000)`; `recall_after = max(0, recall_bps - round_div(recall_drop_bps * route_bps, 10000))`
5. `quality_ok = quality_loss <= guardrail_bps`; `recall_ok = recall_after >= 9900` (KPI-08b hard floor); `allowed = both`
6. `applied_savings = savings if allowed else 0`

Vectors: `vectors/levers_v1.json`. Python: `agents/mc_agents/tools/levers.py`. TypeScript: `dashboard/src/levers.ts`. Same `npm run parity` check.

## Churn-adjusted revenue v1

Integer cents and basis points, same `round_div`. Inputs: `revenue_cents` and `cost_cents` (one month, from the pricing
engine), `churn_bps` (monthly churn probability, from the churn model), `months` (horizon, 1 to 60). Month 1 is billed in full;
churn applies at each renewal after it.

1. `survival_1 = 10000`; `survival_(k+1) = round_div(survival_k * (10000 - churn_bps), 10000)`
2. `expected_months_bps = sum(survival_1 .. survival_months)`; `survival_bps = survival_(months+1)`
3. `adj_revenue = round_div(revenue * expected_months_bps, 10000)`; `adj_cost` likewise (a churned tenant costs nothing)
4. `adj_margin = adj_revenue - adj_cost`

Vectors: `vectors/churn_v1.json`. Python: `agents/mc_agents/tools/churn_adjust.py`. TypeScript: `dashboard/src/churnAdjust.ts`. Same `npm run parity` check.
