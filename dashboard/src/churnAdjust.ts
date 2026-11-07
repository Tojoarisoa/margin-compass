// Churn-adjusted revenue and margin v1 (calc-spec/README.md, ADR-016). Integer arithmetic only; matches
// agents/mc_agents/tools/churn_adjust.py on every vector in calc-spec/vectors/churn_v1.json (EV-12). Synthetic inputs only.
import { roundDiv } from "./pricing.ts";

export interface ChurnInput {
  revenue_cents: number;
  cost_cents: number;
  churn_bps: number;
  months: number;
}

export interface ChurnResult {
  expected_months_bps: number;
  survival_bps: number;
  adj_revenue_cents: number;
  adj_cost_cents: number;
  adj_margin_cents: number;
}

export function churnAdjust(inp: ChurnInput): ChurnResult {
  for (const f of Object.keys(inp) as (keyof ChurnInput)[]) {
    if (!Number.isSafeInteger(inp[f]) || inp[f] < 0) throw new Error(`${f} must be a non-negative integer`);
  }
  if (inp.churn_bps > 10000) throw new Error("churn_bps must be at most 10000");
  if (inp.months < 1 || inp.months > 60) throw new Error("months must be between 1 and 60");
  let survival = 10000;
  let expected = 0;
  for (let i = 0; i < inp.months; i++) {
    expected += survival;
    survival = roundDiv(survival * (10000 - inp.churn_bps), 10000);
  }
  const revenue = roundDiv(inp.revenue_cents * expected, 10000);
  const cost = roundDiv(inp.cost_cents * expected, 10000);
  return {
    expected_months_bps: expected, survival_bps: survival,
    adj_revenue_cents: revenue, adj_cost_cents: cost, adj_margin_cents: revenue - cost,
  };
}
