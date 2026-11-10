// M5-02 PG-7 Action Center, visitor sandbox (PLAN.md §9.3). Reads publish/latest/actions.json (written by the nightly review).
// Decisions and rationale stay in this browser; nothing is sent or stored, and the waterfall is recomputed locally.
import { useEffect, useMemo, useState } from "react";
import { money } from "./format";

interface QueueAction {
  action_id: string; action_type: string; target: string; title: string; impact_usd_month: string; confidence: string;
  effort: number; quality_impact: string; risk: string; status: string; approver: string; assumptions: string; insight?: string;
}
interface Queue { actions: QueueAction[]; data_label?: string }
type Decision = { choice: "approved" | "rejected"; rationale: string };

const ROLE_LABEL: Record<string, string> = {
  head_of_ai_platform: "Head of AI Platform", pricing_committee: "Pricing committee", revops_lead: "RevOps lead",
};
const TYPE_LABEL: Record<string, string> = { "ACT-1": "Engineering lever", "ACT-2": "Pricing change", "ACT-3": "Account action" };

/** "$1,234.50" or "-$1,234.50" to a number. */
export function parseMoney(s: string): number {
  const n = Number(s.replace(/[$,]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

/** Identified, approved, rejected and still-pending monthly impact. Realized stays unknown until M5-04. */
export function waterfall(actions: { action_id: string; impact_usd_month: string }[], decisions: Record<string, Decision>) {
  let identified = 0, approved = 0, rejected = 0;
  for (const a of actions) {
    const v = parseMoney(a.impact_usd_month);
    identified += v;
    const d = decisions[a.action_id];
    if (d?.choice === "approved") approved += v;
    else if (d?.choice === "rejected") rejected += v;
  }
  return { identified, approved, rejected, pending: identified - approved - rejected };
}

export default function ActionCenter() {
  const [queue, setQueue] = useState<QueueAction[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [role, setRole] = useState("all");
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch("/publish/latest/actions.json", { cache: "no-cache" })
      .then((r) => (r.ok ? (r.json() as Promise<Queue>) : Promise.reject(new Error(String(r.status)))))
      .then((q) => setQueue(q.actions))
      .catch(() => setFailed(true));
  }, []);

  const roles = useMemo(() => [...new Set((queue ?? []).map((a) => a.approver))].sort(), [queue]);
  if (failed) return <p className="muted">The action queue isn't published yet.</p>;
  if (!queue) return <p className="muted">Loading actions…</p>;
  if (queue.length === 0) return <p>No margin actions are proposed tonight.</p>;

  const shown = queue.filter((a) => role === "all" || a.approver === role);
  const w = waterfall(queue, decisions);
  const decide = (id: string, choice: Decision["choice"]) => {
    setDecisions((d) => ({ ...d, [id]: { choice, rationale: (draft[id] ?? "").trim() } }));
  };

  return (
    <div>
      <section className="tiles" aria-label="Margin waterfall, per month">
        <div className="tile"><div className="tile-label">Identified</div><div className="tile-value">{money(w.identified)}</div></div>
        <div className="tile"><div className="tile-label">Approved (your sandbox)</div><div className="tile-value">{money(w.approved)}</div></div>
        <div className="tile"><div className="tile-label">Rejected</div><div className="tile-value">{money(w.rejected)}</div></div>
        <div className="tile"><div className="tile-label">Still pending</div><div className="tile-value">{money(w.pending)}</div></div>
        <div className="tile"><div className="tile-label">Realized</div><div className="tile-value">n/a</div><div className="tile-note">needs the closed loop (M5-04)</div></div>
      </section>
      <p>
        <label>Approver queue{" "}
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="all">All queues ({queue.length})</option>
            {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r} ({queue.filter((a) => a.approver === r).length})</option>)}
          </select>
        </label>
      </p>
      <ul className="action-queue" style={{ listStyle: "none", padding: 0 }}>
        {shown.map((a) => {
          const d = decisions[a.action_id];
          return (
            <li key={a.action_id} className="card">
              <h3>{a.title}</h3>
              <p className="muted small">
                {a.action_type} {TYPE_LABEL[a.action_type] ?? ""} · approver: {ROLE_LABEL[a.approver] ?? a.approver} · at stake {a.impact_usd_month} a month · confidence {a.confidence} · effort {a.effort}
              </p>
              <p><strong>Quality impact:</strong> {a.quality_impact}<br /><strong>Risk:</strong> {a.risk}</p>
              {a.insight && <p className="muted small">{a.insight}</p>}
              <p className="muted small">{a.assumptions}</p>
              {d ? (
                <p className="muted">
                  You marked it {d.choice}{d.rationale ? `: "${d.rationale}"` : ""} (sandbox only: this stays in your browser and changes no data).{" "}
                  <button type="button" className="chip" onClick={() => setDecisions(({ [a.action_id]: _, ...rest }) => rest)}>Undo</button>
                </p>
              ) : (
                <div role="group" aria-label={`Decide: ${a.title}`}>
                  <label>Rationale (optional){" "}
                    <input type="text" value={draft[a.action_id] ?? ""} maxLength={200}
                      onChange={(e) => setDraft((x) => ({ ...x, [a.action_id]: e.target.value }))} />
                  </label>{" "}
                  <button type="button" onClick={() => decide(a.action_id, "approved")}>Approve</button>{" "}
                  <button type="button" className="chip" onClick={() => decide(a.action_id, "rejected")}>Reject</button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="muted small">Visitor sandbox: decisions are not saved or sent, and nothing is applied. Synthetic data.</p>
    </div>
  );
}
