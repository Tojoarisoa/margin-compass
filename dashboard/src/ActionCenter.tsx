// M5-02 PG-7 Action Center, visitor sandbox (PLAN.md §9.3). Reads publish/latest/actions.json (written by the nightly review).
// Visitors: decisions and rationale stay in this browser; nothing is sent or stored, and the waterfall is recomputed locally.
// Owner mode (M5-03): a signed-in owner's decisions are recorded through the owner-only API.
import { useEffect, useMemo, useState } from "react";
import type { CognitoUser } from "amazon-cognito-identity-js";
import { money } from "./format";
import { loadOwnerConfig, recordDecision, setNewPassword, signIn, tokenGroups, type OwnerConfig, type OwnerSession } from "./owner";

interface QueueAction {
  action_id: string; action_type: string; target: string; title: string; impact_usd_month: string; confidence: string;
  effort: number; quality_impact: string; risk: string; status: string; approver: string; assumptions: string; insight?: string; renewal_date?: string;
}
interface Queue { actions: QueueAction[]; data_label?: string }
type Decision = { choice: "approved" | "rejected"; rationale: string; saved?: boolean };

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

/** Renewal actions sorted by due date, with whole days from `today` (UTC dates, so the result doesn't depend on the time zone). */
export function renewalCalendar<T extends { renewal_date?: string }>(actions: T[], today: Date): (T & { days: number })[] {
  const t0 = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return actions
    .filter((a): a is T & { renewal_date: string } => !!a.renewal_date && !Number.isNaN(Date.parse(a.renewal_date)))
    .map((a) => ({ ...a, days: Math.round((Date.parse(a.renewal_date) - t0) / 86_400_000) }))
    .sort((x, y) => x.days - y.days);
}

function OwnerSignIn({ cfg, onSession }: { cfg: OwnerConfig; onSession: (s: OwnerSession) => void }) {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<CognitoUser | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!open) return <p className="muted small"><button type="button" className="chip" onClick={() => setOpen(true)}>Owner sign-in</button></p>;
  const accept = (s: OwnerSession) => {
    if (!tokenGroups(s.accessToken).includes("owner")) throw new Error("This account may not record decisions.");
    onSession(s);
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      if (pending) accept(await setNewPassword(pending, password));
      else {
        const r = await signIn(cfg, username.trim(), password);
        if (r.kind === "new_password") { setPending(r.user); setPassword(""); }
        else accept(r.session);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} aria-label="Owner sign-in">
      {!pending && <label>User{" "}<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>}{" "}
      <label>{pending ? "Choose a new password" : "Password"}{" "}
        <input type="password" autoComplete={pending ? "new-password" : "current-password"} value={password}
          onChange={(e) => setPassword(e.target.value)} required minLength={pending ? 14 : 1} />
      </label>{" "}
      <button type="submit" disabled={busy}>{pending ? "Set password" : "Sign in"}</button>{" "}
      <button type="button" className="chip" onClick={() => setOpen(false)}>Cancel</button>
      {error && <p role="alert" className="muted">{error}</p>}
    </form>
  );
}

export default function ActionCenter() {
  const [queue, setQueue] = useState<QueueAction[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [role, setRole] = useState("all");
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [ownerCfg, setOwnerCfg] = useState<OwnerConfig | null>(null);
  const [session, setSession] = useState<OwnerSession | null>(null);
  const [saveError, setSaveError] = useState<Record<string, string>>({});

  useEffect(() => { loadOwnerConfig().then(setOwnerCfg); }, []);

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
  const renewals = renewalCalendar(queue, new Date());
  const decide = async (a: QueueAction, choice: Decision["choice"]) => {
    const rationale = (draft[a.action_id] ?? "").trim();
    if (!session) {
      setDecisions((d) => ({ ...d, [a.action_id]: { choice, rationale } }));
      return;
    }
    try {
      await recordDecision(session, { action_id: a.action_id, action_type: a.action_type, target: a.target, decision: choice, rationale });
      setSaveError(({ [a.action_id]: _, ...rest }) => rest);
      setDecisions((d) => ({ ...d, [a.action_id]: { choice, rationale, saved: true } }));
    } catch (err) {
      setSaveError((x) => ({ ...x, [a.action_id]: err instanceof Error ? err.message : "Not saved" }));
    }
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
      {renewals.length > 0 && (
        <section aria-label="Renewal calendar">
          <h3>Renewal calendar</h3>
          <table>
            <thead><tr><th>Renews</th><th>In</th><th>Account</th><th>At stake / month</th><th>Playbook</th></tr></thead>
            <tbody>
              {renewals.map((r) => (
                <tr key={r.action_id}>
                  <td>{r.renewal_date}</td>
                  <td>{r.days < 0 ? `${-r.days} days ago` : `${r.days} days`}</td>
                  <td>{r.target.split("/")[0]}</td>
                  <td>{r.impact_usd_month}</td>
                  <td>Review 28-day margin and usage; propose a fair-use cap or price within the discount-authority matrix; {ROLE_LABEL[r.approver] ?? r.approver} signs off</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {session ? (
        <p className="muted small">Signed in as owner ({session.username}): decisions are recorded.{" "}
          <button type="button" className="chip" onClick={() => setSession(null)}>Sign out</button></p>
      ) : ownerCfg && <OwnerSignIn cfg={ownerCfg} onSession={setSession} />}
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
              {d?.saved ? (
                <p className="muted">Recorded as {d.choice}{d.rationale ? `: "${d.rationale}"` : ""}.</p>
              ) : d ? (
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
                  <button type="button" onClick={() => decide(a, "approved")}>Approve</button>{" "}
                  <button type="button" className="chip" onClick={() => decide(a, "rejected")}>Reject</button>
                  {saveError[a.action_id] && <span role="alert" className="muted small"> Not saved: {saveError[a.action_id]}</span>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <p className="muted small">{session ? "Owner mode: decisions are recorded. Synthetic data." : "Visitor sandbox: decisions are not saved or sent, and nothing is applied. Synthetic data."}</p>
    </div>
  );
}
