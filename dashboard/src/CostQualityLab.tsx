// PG-5 Cost-Quality Lab (M3-05). Cost-vs-quality frontier for one feature: sweep the share of traffic routed to the
// cheaper tier with the shared lever engine (calc-spec, ADR-016) and mark where a guardrail first blocks the change.
// Synthetic baseline, integer arithmetic only.
import { useMemo, useState } from "react";
import { Chart } from "./charts";
import { replayLever, type LeverInput } from "./levers";
import { ACCENT } from "./theme";

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
  return (
    <div>
      <p className="muted small">
        Cost against quality for one feature (synthetic baseline of {usd(BASE.cost_cents)}/month), as more traffic moves to the
        cheaper tier. The frontier keeps only points where cost falls; blocked points breach the quality guardrail or the 99% safety-recall floor.
      </p>
      <label>Largest allowed quality loss (bps) <input aria-label="Largest allowed quality loss (bps)" inputMode="numeric" value={guard} onChange={num(setGuard)} size={6} /></label>{" "}
      <label>Cache hit share (bps) <input aria-label="Cache hit share (bps)" inputMode="numeric" value={cache} onChange={num(setCache)} size={6} /></label>
      <Chart label="Cost against quality frontier" option={{
        grid: { left: 16, right: 24, top: 56, bottom: 48, containLabel: true },
        legend: { top: 0, data: ["Frontier", "Allowed", "Blocked"] },
        tooltip: { trigger: "item", formatter: (p: { data: { route: number; value: [number, number]; allowed: boolean } }) => p.data?.route === undefined ? "" :
          `<b>${pct(p.data.route)} routed to the cheaper tier</b><br/>Quality ${p.data.value[0].toFixed(1)}%<br/>` +
          `AI cost ${usd(p.data.value[1] * 100)}/month<br/>${p.data.allowed ? "Allowed" : "Blocked by a guardrail"}` },
        xAxis: { type: "value", name: "Quality (%)", nameLocation: "middle", nameGap: 28, scale: true, axisLabel: { formatter: (v: number) => `${v}%` } },
        yAxis: { type: "value", name: "AI cost per month", nameLocation: "end", nameGap: 12, scale: true,
          axisLabel: { formatter: (v: number) => `$${(v / 1000).toFixed(1)}k` } },
        series: [
          { name: "Frontier", type: "line", color: ACCENT, symbol: "none", lineStyle: { width: 2 }, tooltip: { show: false },
            data: frontier.map((r) => [r.quality_after_bps / 100, r.new_cost_cents / 100]) },
          { name: "Allowed", type: "scatter", symbolSize: 10, color: ACCENT, emphasis: { scale: 1.6 },
            data: rows.filter((r) => r.allowed).map((r) => ({ value: [r.quality_after_bps / 100, r.new_cost_cents / 100], route: r.route_bps, allowed: true })) },
          { name: "Blocked", type: "scatter", symbolSize: 10, color: "#fb7185", itemStyle: { color: "transparent", borderColor: "#fb7185", borderWidth: 2 },
            emphasis: { scale: 1.6 },
            data: rows.filter((r) => !r.allowed).map((r) => ({ value: [r.quality_after_bps / 100, r.new_cost_cents / 100], route: r.route_bps, allowed: false })) },
        ],
      }} />
      <p className="muted small">Filled points are allowed; hollow red points are blocked. Hover a point for its details.</p>
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
