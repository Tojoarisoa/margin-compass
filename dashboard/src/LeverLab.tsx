// PG-4 lever scenarios (M3-05). Routing and caching levers replayed in the browser with the shared lever engine
// (calc-spec, ADR-016). Savings only count when the quality and safety-recall guardrails hold. Synthetic baseline.
import { useMemo, useState } from "react";
import { replayLever, type LeverInput } from "./levers";

const FIELDS: { key: keyof LeverInput; label: string; hint: string }[] = [
  { key: "cost_cents", label: "Baseline AI cost (cents/month)", hint: "one feature" },
  { key: "route_bps", label: "Traffic routed to cheaper tier (bps)", hint: "10,000 = 100%" },
  { key: "cheap_cost_ratio_bps", label: "Cheaper tier cost vs baseline (bps)", hint: "2,500 = a quarter of the cost" },
  { key: "cache_hit_bps", label: "Cache hit share (bps)", hint: "of remaining spend" },
  { key: "quality_bps", label: "Current quality score (bps)", hint: "" },
  { key: "quality_drop_bps", label: "Quality lost at 100% routing (bps)", hint: "" },
  { key: "guardrail_bps", label: "Largest allowed quality loss (bps)", hint: "" },
  { key: "recall_bps", label: "Safety-event recall (bps)", hint: "floor is 9,900" },
  { key: "recall_drop_bps", label: "Recall lost at 100% routing (bps)", hint: "" },
];

const DEFAULTS: LeverInput = {
  cost_cents: 500_000, route_bps: 3_000, cheap_cost_ratio_bps: 2_500, cache_hit_bps: 1_000,
  quality_bps: 9_200, quality_drop_bps: 600, guardrail_bps: 300, recall_bps: 9_950, recall_drop_bps: 100,
};

const usd = (cents: number) => (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = (bps: number) => `${(bps / 100).toFixed(1)}%`;

export default function LeverLab() {
  const [lv, setLv] = useState<LeverInput>(DEFAULTS);
  const result = useMemo(() => { try { return replayLever(lv); } catch { return null; } }, [lv]);
  const update = (key: keyof LeverInput, raw: string) => {
    const n = Number(raw);
    if (raw.trim() === "" || !Number.isSafeInteger(n) || n < 0) return;
    setLv((p) => ({ ...p, [key]: n }));
  };
  return (
    <div>
      <p className="muted small">
        Replay a routing and caching change on one feature (synthetic baseline). Savings count only if the quality guardrail
        and the 99% safety-recall floor hold.
      </p>
      <div className="table-wrap">
        <table>
          <tbody>
            {FIELDS.map((f) => (
              <tr key={f.key}>
                <th scope="row" title={f.hint}>{f.label}</th>
                <td><input aria-label={f.label} inputMode="numeric" value={String(lv[f.key])} onChange={(e) => update(f.key, e.target.value)} size={9} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result ? (
        <div className="table-wrap">
          <table>
            <tbody>
              <tr><th scope="row">New AI cost</th><td className="num">{usd(result.new_cost_cents)}</td></tr>
              <tr><th scope="row">Savings</th><td className="num">{usd(result.savings_cents)}</td></tr>
              <tr><th scope="row">Quality after</th><td className="num">{pct(result.quality_after_bps)} ({result.quality_ok ? "within guardrail" : "breaches guardrail"})</td></tr>
              <tr><th scope="row">Safety recall after</th><td className="num">{pct(result.recall_after_bps)} ({result.recall_ok ? "above floor" : "below floor"})</td></tr>
              <tr><th scope="row">Allowed</th><td className="num">{result.allowed ? "Yes" : "No, blocked by a guardrail"}</td></tr>
              <tr><th scope="row">Savings counted</th><td className="num">{usd(result.applied_savings_cents)}</td></tr>
            </tbody>
          </table>
        </div>
      ) : <p className="muted">Invalid input.</p>}
    </div>
  );
}
