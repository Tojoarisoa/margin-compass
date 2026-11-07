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
Python: `agents/mc_agents/tools/pricing.py`. TypeScript: not yet implemented (next step, then the EV-12 parity test).
