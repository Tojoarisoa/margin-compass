import { lazy, Suspense, useEffect, useState } from "react";
import { AskPanel } from "./AskPanel";
import { CogsForecast, MarginForecast, MarginTrend } from "./charts";
import { count, money, percent } from "./format";
import type { Snapshot } from "./types";

const Explorer = lazy(() => import("./Explorer"));
const Health = lazy(() => import("./Health"));

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

export function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [showExplorer, setShowExplorer] = useState(false);
  const [showHealth, setShowHealth] = useState(false);

  useEffect(() => {
    fetch("/publish/latest/pg1.json", { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`snapshot ${r.status}`))))
      .then((d: Snapshot) => (d.schema_version === "pg1.v0" ? setSnap(d) : Promise.reject(new Error("unknown snapshot version"))))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <main className="page"><p className="error">Couldn't load the margin snapshot ({error}).</p></main>;
  if (!snap) return <main className="page"><p className="muted">Loading…</p></main>;

  const h = snap.headline;
  return (
    <main className="page">
      <div className="banner" role="note">
        <strong>Synthetic data.</strong> BoonCore is a fictional company; all tenants and figures are simulated.
      </div>
      <header>
        <h1>Executive Margin Overview <span className="tag">v0</span></h1>
        <p className="muted">AI cost-to-serve and gross margin, {snap.window.from} to {snap.window.to} ({snap.window.days} days).</p>
      </header>

      <section className="tiles" aria-label="Headline KPIs">
        <Tile label="AI gross margin" value={percent(h.window.ai_gross_margin_pct)} note={`last 30 days: ${percent(h.last_30_days.ai_gross_margin_pct)}`} />
        <Tile label="AI revenue" value={money(h.window.ai_revenue_usd)} note={`last 30 days: ${money(h.last_30_days.ai_revenue_usd)}`} />
        <Tile label="AI cost to serve" value={money(h.window.ai_cost_to_serve_usd)} note={`last 30 days: ${money(h.last_30_days.ai_cost_to_serve_usd)}`} />
        <Tile label="Unprofitable tenants" value={`${h.unprofitable_tenants} of ${h.tenants}`} />
        <Tile label="LLM attribution coverage" value={percent(h.llm_attribution_coverage_pct, 1)} note="target ≥ 98%" />
      </section>

      {snap.m2_kpis && (
        <section className="tiles" aria-label="Fully loaded KPIs">
          <Tile label="Gross margin, fully loaded" value={percent(snap.m2_kpis.gross_margin_pct ?? null)} note={snap.m2_kpis.gross_margin_usd == null ? undefined : money(snap.m2_kpis.gross_margin_usd)} />
          <Tile label="Cost per outcome" value={snap.m2_kpis.cost_per_outcome_usd == null ? "n/a" : money(snap.m2_kpis.cost_per_outcome_usd)} />
          <Tile label="Unit cost per request" value={snap.m2_kpis.unit_cost_per_request_usd == null ? "n/a" : `$${snap.m2_kpis.unit_cost_per_request_usd.toFixed(4)}`} />
          <Tile label="Safety-event recall" value={percent(snap.m2_kpis.safety_event_recall ?? null, 1)} />
          <Tile label="Attribution coverage (all cost)" value={percent(snap.m2_kpis.attribution_coverage ?? null, 1)} />
          {snap.m2_at_risk && <Tile label="ARR at risk" value={money(snap.m2_at_risk.arr_at_risk_usd)} note={`${snap.m2_at_risk.unprofitable_tenants} unprofitable tenants`} />}
        </section>
      )}

      <div className="grid">
        <section className="card" aria-labelledby="trend-title">
          <h2 id="trend-title">Daily AI gross margin</h2>
          <MarginTrend snap={snap} />
        </section>
        {snap.m2_margin_forecast && snap.m2_margin_forecast.points.length > 0 && (
          <section className="card" aria-labelledby="mf-title">
            <h2 id="mf-title">AI gross margin: forecast band</h2>
            <MarginForecast snap={snap} />
            <p className="muted small">{snap.m2_margin_forecast.assumption}.</p>
          </section>
        )}
        <section className="card" aria-labelledby="fc-title">
          <h2 id="fc-title">AI COGS: last 30 days and 30-day forecast</h2>
          <CogsForecast snap={snap} />
          <p className="muted small">Model {snap.forecast.model_version} ({snap.forecast.model_alias}), seasonal naive. Band: P10–P90.</p>
        </section>
      </div>

      {snap.m2_features && snap.m2_features.length > 0 && (
        <section className="card" aria-labelledby="features-title">
          <h2 id="features-title">Fully loaded cost to serve by feature</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Feature</th><th scope="col" className="num">Requests</th><th scope="col" className="num">LLM</th>
                  <th scope="col" className="num">Agent compute</th><th scope="col" className="num">Vector</th>
                  <th scope="col" className="num">Network + observability</th><th scope="col" className="num">Third-party</th>
                  <th scope="col" className="num">Total</th><th scope="col" className="num">Share</th></tr>
              </thead>
              <tbody>
                {snap.m2_features.map((f) => (
                  <tr key={f.feature_id}>
                    <td>{f.feature_id} {f.feature_name ?? ""}</td><td className="num">{f.requests.toLocaleString("en-US")}</td>
                    <td className="num">{money(f.llm_cost_usd)}</td><td className="num">{money(f.agent_compute_usd)}</td>
                    <td className="num">{money(f.vector_usd)}</td><td className="num">{money(f.network_observability_usd)}</td>
                    <td className="num">{money(f.third_party_usd)}</td><td className="num">{money(f.cost_to_serve_usd)}</td>
                    <td className="num">{percent(f.cost_share, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">Revenue is booked per tenant, so features show cost and share of cost, not a margin %.</p>
        </section>
      )}

      {snap.m2_at_risk && snap.m2_at_risk.worst.length > 0 && (
        <section className="card" aria-labelledby="risk-title">
          <h2 id="risk-title">Unprofitable tenants, fully loaded (worst first)</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Tenant</th><th scope="col">Plan</th><th scope="col" className="num">ARR</th>
                  <th scope="col" className="num">Revenue</th><th scope="col" className="num">Cost to serve</th>
                  <th scope="col" className="num">Margin</th></tr>
              </thead>
              <tbody>
                {snap.m2_at_risk.worst.map((t) => (
                  <tr key={t.tenant_id}>
                    <td>{t.tenant_id}</td><td>{t.plan ?? "n/a"}</td><td className="num">{money(t.arr_usd)}</td>
                    <td className="num">{money(t.revenue_usd)}</td><td className="num">{money(t.cost_to_serve_usd)}</td>
                    <td className="num">{money(t.margin_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {snap.m2_kpis && (
        <section className="card" aria-labelledby="explore-title">
          <h2 id="explore-title">Cost-to-serve explorer</h2>
          {showExplorer ? (
            <Suspense fallback={<p className="muted">Loading explorer…</p>}><Explorer /></Suspense>
          ) : (
            <button onClick={() => setShowExplorer(true)}>Open explorer</button>
          )}
        </section>
      )}

      {snap.m2_kpis && (
        <section className="card" aria-labelledby="health-title">
          <h2 id="health-title">Pipeline and data health</h2>
          {showHealth ? (
            <Suspense fallback={<p className="muted">Loading health…</p>}><Health /></Suspense>
          ) : (
            <button onClick={() => setShowHealth(true)}>Open health</button>
          )}
        </section>
      )}

      <AskPanel />

      <section className="card" aria-labelledby="tenants-title">
        <h2 id="tenants-title">Tenants by AI gross margin (lowest first)</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Tenant</th><th scope="col">Plan</th><th scope="col" className="num">AI revenue</th>
                <th scope="col" className="num">Cost to serve</th><th scope="col" className="num">Gross margin</th>
                <th scope="col" className="num">Margin %</th><th scope="col" className="num">Requests</th></tr>
            </thead>
            <tbody>
              {snap.tenants.map((t) => (
                <tr key={t.tenant_id}>
                  <td>{t.tenant_id}</td><td>{t.plan ?? "n/a"}</td><td className="num">{money(t.ai_revenue_usd)}</td>
                  <td className="num">{money(t.ai_cost_to_serve_usd)}</td><td className="num">{money(t.ai_gross_margin_usd)}</td>
                  <td className="num">{percent(t.ai_gross_margin_pct)}</td><td className="num">{count(t.request_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="muted small">
        Snapshot {snap.generated_at} · run {snap.run_id.slice(0, 8)}
      </footer>
    </main>
  );
}
