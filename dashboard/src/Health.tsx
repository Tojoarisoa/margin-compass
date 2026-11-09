// PG-8 "Pipeline & Data Health" tab. Reads publish/latest/m2_scorecard.json and m2_lineage.json (small, no per-row data).
import { useEffect, useState } from "react";

interface Warn { check: string; category: string; severity: string; day: string; value: number; expected: number; ratio: number }
interface Card { run_id: string; generated_at?: string; data_through?: string | null; checks: string[]; warnings: Warn[]; synthetic: boolean }
interface Lineage { run_id: string; models: Record<string, string[]>; metrics_by_mart: Record<string, string[]>; synthetic: boolean }

const get = <T,>(name: string): Promise<T> =>
  fetch(`/publish/latest/${name}`, { cache: "no-cache" }).then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject(new Error(`${name} ${r.status}`))));

interface Fin { status: string; by_stage: { key: string; cost_usd: number }[]; by_service: { key: string; cost_usd: number }[]; latest_month?: string; latest_month_usd?: number }

function Finops() {
  const [fin, setFin] = useState<Fin | null>(null);
  useEffect(() => { get<Fin>("finops.json").then(setFin).catch(() => setFin(null)); }, []);
  if (!fin) return null;
  return (
    <div>
      <h3>Platform FinOps</h3>
      {fin.status !== "ok" ? <p className="muted">Awaiting first export of the platform's AWS bill.</p> : (
        <>
          <p className="muted small">Month {fin.latest_month?.slice(0, 7)}: ${fin.latest_month_usd?.toFixed(2)} (real AWS cost, not synthetic).</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Lifecycle stage</th><th scope="col" className="num">Cost</th></tr></thead>
              <tbody>{fin.by_stage.map((r) => <tr key={r.key}><td>{r.key}</td><td className="num">${r.cost_usd.toFixed(2)}</td></tr>)}</tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Service</th><th scope="col" className="num">Cost</th></tr></thead>
              <tbody>{fin.by_service.map((r) => <tr key={r.key}><td>{r.key}</td><td className="num">${r.cost_usd.toFixed(2)}</td></tr>)}</tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

interface Dog { status: string; first_date?: string; last_date?: string; total_calls: number; total_cost_usd: number; by_model: { model_id: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; mean_latency_ms: number }[] }

function Dogfood() {
  const [d, setD] = useState<Dog | null>(null);
  useEffect(() => { get<Dog>("dogfood.json").then(setD).catch(() => setD(null)); }, []);
  if (!d) return null;
  return (
    <div>
      <h3>Platform's own model calls (dogfood)</h3>
      {d.status !== "ok" ? <p className="muted">Awaiting first model calls.</p> : (
        <>
          <p className="muted small">{d.total_calls} calls, ${d.total_cost_usd.toFixed(4)}, {d.first_date} to {d.last_date}. Real usage by the demo tenant, kept apart from BoonCore's margin. No prompt or answer content is stored.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th scope="col">Model</th><th scope="col" className="num">Calls</th><th scope="col" className="num">Cost</th><th scope="col" className="num">Mean latency (ms)</th></tr></thead>
              <tbody>{d.by_model.map((m) => <tr key={m.model_id}><td>{m.model_id}</td><td className="num">{m.calls}</td><td className="num">${m.cost_usd.toFixed(4)}</td><td className="num">{m.mean_latency_ms}</td></tr>)}</tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

interface Quality { gates: Record<string, Record<string, unknown>> }
const GATE_NAMES: Record<string, string> = { ev03: "EV-03 margin-leak detection", ev11: "EV-11 churn model" };
const SHOWN = ["precision", "recall", "mttd_days", "alerts", "labels", "auc", "brier", "test_n", "scored"];

function AiQuality() {
  const [q, setQ] = useState<Quality | null>(null);
  useEffect(() => { get<Quality>("quality.json").then(setQ).catch(() => setQ(null)); }, []);
  if (!q) return null;
  return (
    <div>
      <h3>AI quality: evaluation gates</h3>
      <p className="muted small">Results of the latest build on synthetic data. A failed gate is shown here and never hidden.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Gate</th><th scope="col">Result</th><th scope="col">Measured</th></tr></thead>
          <tbody>
            {Object.entries(q.gates).map(([k, g]) => (
              <tr key={k}>
                <td>{GATE_NAMES[k] ?? k}</td>
                <td>{g.passed === true ? "Passed" : g.passed === false ? "Not passed" : "n/a"}</td>
                <td>{SHOWN.filter((f) => typeof g[f] === "number").map((f) => `${f}: ${g[f]}`).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface Runs { runs: { run_id: string; finished_at: string; status: string; models: number }[] }

function RunHistory() {
  const [runs, setRuns] = useState<Runs | null>(null);
  useEffect(() => { get<Runs>("runs.json").then(setRuns).catch(() => setRuns(null)); }, []);
  if (!runs || runs.runs.length === 0) return null;
  return (
    <>
      <h3>Run history</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Run</th><th scope="col">Finished (UTC)</th><th scope="col">Status</th><th scope="col" className="num">Models</th></tr></thead>
          <tbody>{runs.runs.map((r) => <tr key={r.run_id}><td>{r.run_id}</td><td>{r.finished_at.replace("T", " ").slice(0, 16)}</td><td>{r.status}</td><td className="num">{r.models}</td></tr>)}</tbody>
        </table>
      </div>
    </>
  );
}

export default function Health() {
  const [card, setCard] = useState<Card | null>(null);
  const [lin, setLin] = useState<Lineage | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([get<Card>("m2_scorecard.json"), get<Lineage>("m2_lineage.json")])
      .then(([c, l]) => { setCard(c); setLin(l); })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">Health tab couldn't load ({error}).</p>;
  if (!card || !lin) return <p className="muted">Loading health…</p>;

  const perCheck = card.checks.map((c) => ({ check: c, n: card.warnings.filter((w) => w.check === c).length }));
  return (
    <div>
      <p className="muted small">Run {card.run_id}{card.generated_at ? `, built ${card.generated_at.replace("T", " ").slice(0, 16)} UTC` : ""}{card.data_through ? `, data through ${card.data_through}` : ""}. Synthetic data. Drift findings are statistical warnings, never errors.</p>
      <h3>Drift checks</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Check</th><th scope="col" className="num">Warnings</th></tr></thead>
          <tbody>{perCheck.map((c) => <tr key={c.check}><td>{c.check}</td><td className="num">{c.n}</td></tr>)}</tbody>
        </table>
      </div>
      {card.warnings.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Day</th><th scope="col">Check</th><th scope="col" className="num">Value</th><th scope="col" className="num">Expected</th><th scope="col" className="num">Ratio</th></tr></thead>
            <tbody>
              {card.warnings.slice(0, 20).map((w) => (
                <tr key={`${w.check}-${w.day}`}><td>{w.day}</td><td>{w.check}</td><td className="num">{w.value}</td><td className="num">{w.expected}</td><td className="num">{w.ratio}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3>Lineage: model to upstream models</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Model</th><th scope="col">Upstream</th></tr></thead>
          <tbody>{Object.entries(lin.models).sort().map(([m, up]) => <tr key={m}><td>{m}</td><td>{up.join(", ") || "none"}</td></tr>)}</tbody>
        </table>
      </div>
      <AiQuality />
      <RunHistory />
      <Finops />
      <Dogfood />
      <h3>Metrics each mart feeds</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th scope="col">Mart</th><th scope="col">Metrics</th></tr></thead>
          <tbody>{Object.entries(lin.metrics_by_mart).map(([m, ms]) => <tr key={m}><td>{m}</td><td>{ms.join(", ")}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
