// M5-04 realized margin card (KPI-02). Reads publish/latest/realized.json (totals only, written by the M2 build).
// Every figure comes from the pipeline; this file only formats. Hidden if the file is missing.
import { useEffect, useState } from "react";
import { money } from "./format";

interface Realized {
  actions_realized: number; actions_pending: number; saved_usd: string; revenue_delta_usd: string;
  realized_margin_usd: string; pending_saved_usd: string; realization_rate: string | null; method?: string; data_label?: string;
}

export function RealizedCard() {
  const [r, setR] = useState<Realized | null>(null);
  useEffect(() => {
    fetch("/publish/latest/realized.json", { cache: "no-cache" })
      .then((x) => (x.ok ? (x.json() as Promise<Realized>) : Promise.reject(new Error(String(x.status)))))
      .then(setR)
      .catch(() => setR(null));
  }, []);
  if (!r) return null;
  const rate = r.realization_rate === null ? "n/a" : `${(Number(r.realization_rate) * 100).toFixed(1)}%`;
  return (
    <section className="card" aria-labelledby="realized-title">
      <h2 id="realized-title">Realized margin</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Measure</th><th scope="col" className="num">Value</th></tr></thead>
          <tbody>
            <tr><td>Realized margin</td><td className="num">{money(Number(r.realized_margin_usd))}</td></tr>
            <tr><td>Cost saved</td><td className="num">{money(Number(r.saved_usd))}</td></tr>
            <tr><td>Revenue change</td><td className="num">{money(Number(r.revenue_delta_usd))}</td></tr>
            <tr><td>Still pending verification</td><td className="num">{money(Number(r.pending_saved_usd))}</td></tr>
            <tr><td>Realization rate</td><td className="num">{rate}</td></tr>
            <tr><td>Actions realized / pending</td><td className="num">{r.actions_realized} / {r.actions_pending}</td></tr>
          </tbody>
        </table>
      </div>
      <p className="muted small">{r.method ?? ""} Effect sizes are synthetic assumptions. Synthetic data.</p>
    </section>
  );
}
