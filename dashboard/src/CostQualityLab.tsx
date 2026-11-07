// PG-5 Cost-Quality Lab (M3-05). Cost-vs-quality frontier for one feature: sweep the share of traffic routed to the
// cheaper tier with the shared lever engine (calc-spec, ADR-016) and mark where a guardrail first blocks the change.
// Synthetic baseline, integer arithmetic only.
import { useMemo, useState } from "react";
import { replayLever, type LeverInput } from "./levers";

const BASE: LeverInput = {
  cost_cents: 500_000, route_bps: 0, cheap_cost_ratio_bps: 2_500, cache_hit_bps: 1_000,
  quality_bps: 9_200, quality_drop_bps: 600, guardrail_bps: 300, recall_bps: 9_950, recall_drop_bps: 100,
};
const STEPS = Array.from({ length: 11 }, (_, i) => i * 1_000);
const usd = (c: number) => (c / 100).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = (b: number) => `${(b / 100).toFixed(1)}%`;

export default function CostQualityLab() {
  const [guard, setGuard] = useState(BASE.guardrail_bps);
  const [cache, setCache] = useState(BASE.cache_hit_bps);
  const rows = useMemo(() => STEPS.map((route_bps) => {
    const r = replayLever({ ...BASE, route_bps, guardrail_bps: guard, cache_hit_bps: cache });
    return { route_bps, ...r };
  }), [guard, cache]);
  const best = rows.filter((r) => r.allowed).reduce((a, r) => (r.savings_cents > a.savings_cents ? r : a), rows[0]);
  const frontier = rows.filter((r, i) => i === 0 || r.new_cost_cents < rows[i - 1].new_cost_cents);
  const num = (setter: (n: number) => void) => (e: { target: { value: string } }) => {
    const n = Number(e.target.value);
    if (e.target.value.trim() !== "" && Number.isSafeInteger(n) && n >= 0 && n <= 10_000) setter(n);
  };
  const w = 320, h = 140, minC = Math.min(...rows.map((r) => r.new_cost_cents)), maxC = BASE.cost_cents;
  const x = (q: number) => 10 + ((q - Math.min(...rows.map((r) => r.quality_after_bps))) / Math.max(1, BASE.quality_bps - Math.min(...rows.map((r) => r.quality_after_bps)))) * (w - 20);
  const y = (c: number) => h - 10 - ((c - minC) / Math.max(1, maxC - minC)) * (h - 20);
  return (
    <div>
      <p className="muted small">
        Cost against quality for one feature (synthetic baseline of {usd(BASE.cost_cents)}/month), as more traffic moves to the
        cheaper tier. The frontier keeps only points where cost falls; blocked points breach the quality guardrail or the 99% safety-recall floor.
      </p>
      <label>Largest allowed quality loss (bps) <input aria-label="Largest allowed quality loss (bps)" inputMode="numeric" value={guard} onChange={num(setGuard)} size={6} /></label>{" "}
      <label>Cache hit share (bps) <input aria-label="Cache hit share (bps)" inputMode="numeric" value={cache} onChange={num(setCache)} size={6} /></label>
      <svg role="img" aria-label="Cost against quality frontier" viewBox={`0 0 ${w} ${h}`} width="100%" style={{ maxWidth: 420 }}>
        <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={frontier.map((r) => `${x(r.quality_after_bps)},${y(r.new_cost_cents)}`).join(" ")} />
        {rows.map((r) => (
          <circle key={r.route_bps} cx={x(r.quality_after_bps)} cy={y(r.new_cost_cents)} r="3" fill={r.allowed ? "currentColor" : "none"} stroke="currentColor">
            <title>{`${pct(r.route_bps)} routed: ${usd(r.new_cost_cents)}, quality ${pct(r.quality_after_bps)}${r.allowed ? "" : " (blocked)"}`}</title>
          </circle>
        ))}
      </svg>
      <p className="muted small">Filled points are allowed; hollow points are blocked. Left is lower quality, bottom is lower cost.</p>
      <p>Best allowed: route {pct(best.route_bps)} for savings of {usd(best.savings_cents)} per month at quality {pct(best.quality_after_bps)}.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Routed</th><th>AI cost</th><th>Savings</th><th>Quality</th><th>Safety recall</th><th>Status</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.route_bps}>
                <td className="num">{pct(r.route_bps)}</td><td className="num">{usd(r.new_cost_cents)}</td><td className="num">{usd(r.savings_cents)}</td>
                <td className="num">{pct(r.quality_after_bps)}</td><td className="num">{pct(r.recall_after_bps)}</td>
                <td>{r.allowed ? (r === best ? "Best allowed" : "Allowed") : !r.quality_ok ? "Blocked: quality" : "Blocked: recall"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
