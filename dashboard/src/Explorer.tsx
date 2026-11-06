// PG-2 Cost-to-Serve Explorer. Reads publish/latest/pg2.json: views pre-aggregated by the pipeline, so every figure
// equals the marts (ADR-009 fallback: the DuckDB-WASM spike needs the parquet extension from a public CDN).
import { useEffect, useState } from "react";
import { money, percent } from "./format";

interface Cost { requests: number; llm_cost_usd: number; agent_compute_usd: number; vector_usd: number; network_observability_usd: number; third_party_usd: number; cost_to_serve_usd: number }
type Row = Cost & { tenant_id?: string; feature_id?: string; feature_name?: string | null; month?: string };
interface Wf { tenant_id: string; revenue_usd: number; discount_usd: number; llm_cost_usd: number; infra_cost_usd: number; margin_usd: number }
interface Cov { month: string; allocated_usd: number; unallocated_usd: number; coverage: number | null }
interface Pg2 { schema_version: "pg2.v0"; margin_waterfall: Wf[]; attribution_by_month: Cov[]; by_tenant: Row[]; by_feature: Row[]; by_month: Row[]; by_tenant_feature: Row[] }

const VIEWS = { by_tenant: "Tenant", by_feature: "Feature", by_month: "Month", by_tenant_feature: "Tenant and feature" } as const;
type View = keyof typeof VIEWS;

const label = (r: Row) => [r.tenant_id, r.month, r.feature_id && `${r.feature_id}${r.feature_name ? ` ${r.feature_name}` : ""}`].filter(Boolean).join(" / ");

export default function Explorer() {
  const [data, setData] = useState<Pg2 | null>(null);
  const [view, setView] = useState<View>("by_tenant");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/publish/latest/pg2.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`pg2 ${r.status}`))))
      .then((d: Pg2) => (d.schema_version === "pg2.v0" ? setData(d) : Promise.reject(new Error("unknown version"))))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">Explorer couldn't load ({error}).</p>;
  if (!data) return <p className="muted">Loading explorer…</p>;

  const rows = [...data[view]].sort((a, b) => (view === "by_month" ? 0 : b.cost_to_serve_usd - a.cost_to_serve_usd)).slice(0, 50);
  return (
    <div>
      <label>Group by{" "}
        <select value={view} onChange={(e) => setView(e.target.value as View)}>
          {(Object.keys(VIEWS) as View[]).map((v) => <option key={v} value={v}>{VIEWS[v]}</option>)}
        </select>
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th scope="col">{VIEWS[view]}</th><th scope="col" className="num">Requests</th><th scope="col" className="num">LLM</th>
              <th scope="col" className="num">Agent compute</th><th scope="col" className="num">Vector</th>
              <th scope="col" className="num">Network + observability</th><th scope="col" className="num">Third-party</th>
              <th scope="col" className="num">Total</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={label(r)}>
                <td>{label(r)}</td><td className="num">{r.requests.toLocaleString("en-US")}</td><td className="num">{money(r.llm_cost_usd)}</td>
                <td className="num">{money(r.agent_compute_usd)}</td><td className="num">{money(r.vector_usd)}</td>
                <td className="num">{money(r.network_observability_usd)}</td><td className="num">{money(r.third_party_usd)}</td>
                <td className="num">{money(r.cost_to_serve_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Margin by tenant: revenue to margin (lowest margin first, top 10)</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th scope="col">Tenant</th><th scope="col" className="num">Revenue (net of discount)</th><th scope="col" className="num">Discount</th>
              <th scope="col" className="num">LLM cost</th><th scope="col" className="num">Infrastructure</th><th scope="col" className="num">Margin</th></tr>
          </thead>
          <tbody>
            {data.margin_waterfall.slice(0, 10).map((w) => (
              <tr key={w.tenant_id}><td>{w.tenant_id}</td><td className="num">{money(w.revenue_usd)}</td><td className="num">{money(w.discount_usd)}</td>
                <td className="num">{money(w.llm_cost_usd)}</td><td className="num">{money(w.infra_cost_usd)}</td><td className="num">{money(w.margin_usd)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Shared-infrastructure attribution coverage by month</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Month</th><th scope="col" className="num">Allocated</th><th scope="col" className="num">Unallocated</th><th scope="col" className="num">Coverage</th></tr></thead>
          <tbody>
            {data.attribution_by_month.map((c) => (
              <tr key={c.month}><td>{c.month}</td><td className="num">{money(c.allocated_usd)}</td><td className="num">{money(c.unallocated_usd)}</td><td className="num">{percent(c.coverage, 1)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Fully loaded cost to serve, whole window; top 50 rows by cost (months in order). Revenue is per tenant, so no margin % by feature.</p>
    </div>
  );
}
