// Pricing engine v1 (calc-spec/README.md, ADR-016). Integer arithmetic only, so results are exact to the cent
// and match agents/mc_agents/tools/pricing.py on every vector in calc-spec/vectors/pricing_v1.json (EV-12).
// Money in cents, usage rates in micro-dollars per unit, ratios in basis points. Synthetic inputs only.

export interface PricingInput {
  seats: number;
  seat_price_cents: number;
  addon_cents: number;
  included_units: number;
  overage_rate_micro: number;
  usage_units: number;
  outcome_price_micro: number;
  outcomes: number;
  usage_cap_cents: number | null;
  discount_bps: number;
  cost_cents: number;
}

export interface PricingResult {
  seat_cents: number;
  overage_cents: number;
  outcome_cents: number;
  usage_cents: number;
  gross_cents: number;
  discount_cents: number;
  revenue_cents: number;
  margin_cents: number;
  margin_bps: number | null;
}

/** Round half up of n / d for n >= 0, d > 0. */
export function roundDiv(n: number, d: number): number {
  return Math.floor((2 * n + d) / (2 * d));
}

const NON_NEGATIVE: (keyof PricingInput)[] = [
  "seats", "seat_price_cents", "addon_cents", "included_units", "overage_rate_micro", "usage_units",
  "outcome_price_micro", "outcomes", "discount_bps",
];

export function pricePlan(p: PricingInput): PricingResult {
  for (const f of [...NON_NEGATIVE, "cost_cents" as const]) {
    const v = p[f] as number;
    if (!Number.isSafeInteger(v) || (v < 0 && f !== "cost_cents")) throw new Error(`${f} must be a non-negative integer`);
  }
  const cap = p.usage_cap_cents;
  if (cap !== null && (!Number.isSafeInteger(cap) || cap < 0)) throw new Error("usage_cap_cents must be a non-negative integer or null");
  if (p.discount_bps > 10000) throw new Error("discount_bps must be at most 10000");
  const seat = p.seats * p.seat_price_cents;
  const overage = roundDiv(Math.max(0, p.usage_units - p.included_units) * p.overage_rate_micro, 10000);
  const outcome = roundDiv(p.outcomes * p.outcome_price_micro, 10000);
  const usage = cap === null ? overage + outcome : Math.min(overage + outcome, cap);
  const gross = seat + p.addon_cents + usage;
  const discount = roundDiv(gross * p.discount_bps, 10000);
  const revenue = gross - discount;
  const margin = revenue - p.cost_cents;
  const bps = revenue === 0 ? null : (margin >= 0 ? 1 : -1) * roundDiv(Math.abs(margin) * 10000, revenue);
  return {
    seat_cents: seat, overage_cents: overage, outcome_cents: outcome, usage_cents: usage,
    gross_cents: gross, discount_cents: discount, revenue_cents: revenue, margin_cents: margin, margin_bps: bps,
  };
}
