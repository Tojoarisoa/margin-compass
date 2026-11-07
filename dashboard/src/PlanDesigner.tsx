// PG-4 plan designer (M3-05). Revenue, margin and churn-adjusted margin per segment, computed in the browser with the
// shared pricing and churn engines (calc-spec, ADR-016). Segment profiles are synthetic and illustrative, not tenant data.
import { useMemo, useState } from "react";
import { churnAdjust } from "./churnAdjust";
import { pricePlan, type PricingInput } from "./pricing";

interface Segment { name: string; seats: number; usage_units: number; outcomes: number; cost_cents: number; churn_bps: number }
interface Plan { name: string; seat_price_cents: number; included_units: number; overage_rate_micro: number; outcome_price_micro: number; usage_cap_cents: number | null; discount_bps: number }

// Monthly profile of one typical account per segment (synthetic).
const SEGMENTS: Segment[] = [
  { name: "Starter", seats: 5, usage_units: 8_000, outcomes: 40, cost_cents: 9_000, churn_bps: 400 },
  { name: "Growth", seats: 40, usage_units: 90_000, outcomes: 600, cost_cents: 110_000, churn_bps: 200 },
  { name: "Enterprise", seats: 250, usage_units: 700_000, outcomes: 6_000, cost_cents: 820_000, churn_bps: 80 },
];
const HORIZON_MONTHS = 12;

const BASE: Plan = { name: "Current", seat_price_cents: 3_000, included_units: 50_000, overage_rate_micro: 4_000, outcome_price_micro: 0, usage_cap_cents: null, discount_bps: 0 };

const FIELDS: { key: keyof Plan; label: string; hint: string }[] = [
  { key: "seat_price_cents", label: "Seat price (cents/month)", hint: "per seat" },
  { key: "included_units", label: "Included usage (units)", hint: "per account per month" },
  { key: "overage_rate_micro", label: "Overage rate (micro-$/unit)", hint: "1,000,000 = $1" },
  { key: "outcome_price_micro", label: "Outcome price (micro-$/outcome)", hint: "1,000,000 = $1" },
  { key: "usage_cap_cents", label: "Usage cap (cents, blank = none)", hint: "caps overage plus outcomes" },
  { key: "discount_bps", label: "Discount (bps)", hint: "10,000 = 100%" },
];

const usd = (cents: number) => (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = (bps: number | null) => (bps === null ? "n/a" : `${(bps / 100).toFixed(1)}%`);

function evaluate(plan: Plan) {
  const rows = SEGMENTS.map((s) => {
    const input: PricingInput = {
      seats: s.seats, seat_price_cents: plan.seat_price_cents, addon_cents: 0, included_units: plan.included_units,
      overage_rate_micro: plan.overage_rate_micro, usage_units: s.usage_units, outcome_price_micro: plan.outcome_price_micro,
      outcomes: s.outcomes, usage_cap_cents: plan.usage_cap_cents, discount_bps: plan.discount_bps, cost_cents: s.cost_cents,
    };
    const p = pricePlan(input);
    const c = churnAdjust({ revenue_cents: p.revenue_cents, cost_cents: s.cost_cents, churn_bps: s.churn_bps, months: HORIZON_MONTHS });
    return { name: s.name, revenue: p.revenue_cents, margin: p.margin_cents, bps: p.margin_bps, adj: c.adj_margin_cents };
  });
  return rows;
}

function parse(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isSafeInteger(n) && n >= 0 ? n : NaN;
}

export default function PlanDesigner() {
  const [plans, setPlans] = useState<Plan[]>([{ ...BASE }, { ...BASE, name: "Scenario B", included_units: 30_000 }]);
  const results = useMemo(() => plans.map((p) => { try { return evaluate(p); } catch { return null; } }), [plans]);

  const update = (i: number, key: keyof Plan, raw: string) => {
    const n = parse(raw);
    if (Number.isNaN(n)) return;
    if (n === null && key !== "usage_cap_cents") return;
    setPlans((ps) => ps.map((p, j) => (j === i ? { ...p, [key]: n } : p)));
  };

  return (
    <div>
      <p className="muted small">
        Compare up to 3 pricing scenarios for one typical account per segment (synthetic profiles). Revenue and margin are per account per month;
        churn-adjusted margin is the expected total over {HORIZON_MONTHS} months after segment churn.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th scope="col">Plan input</th>{plans.map((p, i) => <th scope="col" key={i}>{p.name}</th>)}</tr>
          </thead>
          <tbody>
            {FIELDS.map((f) => (
              <tr key={f.key}>
                <th scope="row" title={f.hint}>{f.label}</th>
                {plans.map((p, i) => (
                  <td key={i}>
                    <input aria-label={`${f.label}, ${p.name}`} inputMode="numeric" value={p[f.key] === null ? "" : String(p[f.key])}
                      onChange={(e) => update(i, f.key, e.target.value)} size={9} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        {plans.length < 3 && <button onClick={() => setPlans((ps) => [...ps, { ...ps[ps.length - 1], name: `Scenario ${"ABC"[ps.length]}` }])}>Add scenario</button>}
        {plans.length > 1 && <button onClick={() => setPlans((ps) => ps.slice(0, -1))}>Remove last</button>}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th scope="col">Segment</th><th scope="col">Scenario</th><th scope="col" className="num">Revenue</th>
              <th scope="col" className="num">Margin</th><th scope="col" className="num">Margin %</th>
              <th scope="col" className="num">{HORIZON_MONTHS}-month churn-adjusted margin</th></tr>
          </thead>
          <tbody>
            {SEGMENTS.flatMap((s, si) => plans.map((p, pi) => {
              const r = results[pi]?.[si];
              return (
                <tr key={`${s.name}-${pi}`}>
                  <td>{pi === 0 ? s.name : ""}</td><td>{p.name}</td>
                  {r ? (<><td className="num">{usd(r.revenue)}</td><td className="num">{usd(r.margin)}</td><td className="num">{pct(r.bps)}</td><td className="num">{usd(r.adj)}</td></>)
                    : <td colSpan={4} className="muted">Invalid input</td>}
                </tr>
              );
            }))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
