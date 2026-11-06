// PG-8 "Pipeline & Data Health" tab. Reads publish/latest/m2_scorecard.json and m2_lineage.json (small, no per-row data).
import { useEffect, useState } from "react";

interface Warn { check: string; category: string; severity: string; day: string; value: number; expected: number; ratio: number }
interface Card { run_id: string; checks: string[]; warnings: Warn[]; synthetic: boolean }
interface Lineage { run_id: string; models: Record<string, string[]>; metrics_by_mart: Record<string, string[]>; synthetic: boolean }

const get = <T,>(name: string): Promise<T> =>
  fetch(`/publish/latest/${name}`, { cache: "no-cache" }).then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject(new Error(`${name} ${r.status}`))));

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
      <p className="muted small">Run {card.run_id}. Synthetic data. Drift findings are statistical warnings, never errors.</p>
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
