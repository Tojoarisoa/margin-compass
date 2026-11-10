// M5-01 daily margin brief card. Reads publish/latest/margin_brief.json (written by the nightly review, no LLM).
// Every figure comes from the pipeline; this file only formats.
import { useEffect, useState } from "react";
import { money } from "./format";

interface BriefAction { action_id: string; action_type: string; title: string; impact_usd_month: string | number; approver: string; insight?: string }
interface Brief { headline: string; action_count: number; total_impact_usd_month: string | number; top_actions: BriefAction[]; data_label?: string }

export function BriefCard() {
  const [brief, setBrief] = useState<Brief | null>(null);
  useEffect(() => {
    fetch("/publish/latest/margin_brief.json", { cache: "no-cache" })
      .then((r) => (r.ok ? (r.json() as Promise<Brief>) : Promise.reject(new Error(String(r.status)))))
      .then(setBrief)
      .catch(() => setBrief(null));
  }, []);
  if (!brief) return null;
  return (
    <section className="card" aria-labelledby="brief-title">
      <h2 id="brief-title">Daily margin brief</h2>
      <p>{brief.headline}</p>
      {brief.top_actions.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th scope="col">Proposed action</th><th scope="col">Type</th><th scope="col">Approver</th><th scope="col" className="num">At stake per month</th></tr></thead>
            <tbody>
              {brief.top_actions.map((a) => (
                <tr key={a.action_id}><td>{a.title}{a.insight && <div className="muted small">{a.insight}</div>}</td><td>{a.action_type}</td><td>{a.approver}</td><td className="num">{money(Number(a.impact_usd_month))}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">Notes under an action are a model's suggestion to check first, not a finding. Proposals only: nothing is applied without approval. Synthetic data.</p>
    </section>
  );
}
