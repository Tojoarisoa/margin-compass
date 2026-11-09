import { useState } from "react";
import { ApiError, ask, waitForJob, type Job } from "./api";

const PERSONAS: Record<string, string[]> = {
  CFO: [
    "What was the portfolio AI gross margin in August 2025?",
    "What was the portfolio AI gross margin in September 2025?",
  ],
  "RevOps / Customer Success": [
    "What was the AI gross margin for tenant bc-t0003 in September 2025?",
    "Which three tenants had the lowest AI gross margin percentage from August 1 to October 29, 2025?",
  ],
  "FinOps Practitioner": [
    "How much did it cost to serve bc-t0012 in October 2025?",
  ],
};

const STATUS_TEXT: Record<Job["status"], string> = {
  pending: "Queued…", running: "Thinking…", answered: "", needs_approval: "", blocked: "Blocked by a guardrail", unverified: "Answer withheld", budget_exceeded: "Unavailable right now", error: "Error",
};

const STEP_LABEL: Record<string, string> = {
  route: "Understand the question", specialist: "Look up the figures", verify: "Check against the evidence", respond: "Write the answer",
};

const GRAPH_NODES = ["route", "specialist", "verify", "respond"] as const;

/** Live graph view: the fixed agent graph with the nodes the run visited lit up (from `trail`, node and status only). */
export function AgentGraph({ trail, done }: { trail?: Job["trail"]; done?: boolean }) {
  if (!trail || trail.length === 0) return null;
  const visits: Record<string, number> = {};
  for (const t of trail) {
    const n = t.node === "route" || t.node === "verify" || t.node === "respond" ? t.node : "specialist";
    visits[n] = (visits[n] ?? 0) + 1;
  }
  if (done) visits.respond = visits.respond ?? 1;
  const last = trail[trail.length - 1];
  const lastNode = last.node === "route" || last.node === "verify" ? last.node : "specialist";
  const w = 110, gap = 30;
  return (
    <svg className="agent-graph" role="img" viewBox={`0 0 ${GRAPH_NODES.length * (w + gap) - gap} 70`}
         aria-label={`Agent graph: ${GRAPH_NODES.filter((n) => visits[n]).map((n) => STEP_LABEL[n]).join(", then ")}`}>
      {GRAPH_NODES.map((n, i) => {
        const x = i * (w + gap), seen = visits[n] ?? 0;
        return (
          <g key={n}>
            {i > 0 && <line x1={x - gap} y1={25} x2={x} y2={25} stroke="currentColor" strokeOpacity={seen ? 0.8 : 0.25} />}
            <rect x={x} y={5} width={w} height={40} rx={6} fill="none" stroke="currentColor"
                  strokeWidth={!done && n === lastNode ? 3 : 1.5} strokeOpacity={seen ? 1 : 0.3} />
            <text x={x + w / 2} y={29} textAnchor="middle" fontSize={11} fill="currentColor" opacity={seen ? 1 : 0.45}>{STEP_LABEL[n]}</text>
            {seen > 1 && <text x={x + w / 2} y={62} textAnchor="middle" fontSize={10} fill="currentColor">retried ×{seen - 1}</text>}
          </g>
        );
      })}
    </svg>
  );
}

export function AgentSteps({ trail }: { trail?: Job["trail"] }) {
  if (!trail || trail.length === 0) return null;
  return (
    <ol className="steps" aria-label="Steps taken">
      {trail.map((t, i) => (
        <li key={`${t.node}-${i}`}>{STEP_LABEL[t.node] ?? "Look up the figures"}<span className="muted"> · {t.status}</span></li>
      ))}
    </ol>
  );
}

const ROLE_LABEL: Record<string, string> = { revops_lead: "RevOps lead", cfo: "CFO", finance_director: "Finance director" };

/** Visitor sandbox (PLAN.md §9.3): the decision stays in this browser; nothing is sent or stored. */
export function ApprovalBox({ approver }: { approver?: string }) {
  const [decision, setDecision] = useState<"approved" | "rejected" | null>(null);
  const role = ROLE_LABEL[approver ?? ""] ?? (approver || "the approver");
  return (
    <div className="approval" role="group" aria-label="Approval">
      <p>This answer proposes an action. It needs approval from <strong>{role}</strong> before anything changes.</p>
      {decision ? (
        <p className="muted">You marked it {decision} (sandbox only: this stays in your browser and changes no data).</p>
      ) : (
        <>
          <button type="button" onClick={() => setDecision("approved")}>Approve</button>{" "}
          <button type="button" className="chip" onClick={() => setDecision("rejected")}>Reject</button>
        </>
      )}
    </div>
  );
}

export function AskPanel() {
  const [question, setQuestion] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [persona, setPersona] = useState(Object.keys(PERSONAS)[0]);
  const [history, setHistory] = useState<{ q: string; job: Job }[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(q: string) {
    if (!q.trim() || busy) return;
    setBusy(true);
    setError("");
    setJob(null);
    try {
      const id = await ask(q.trim());
      setJob({ job_id: id, status: "pending" });
      const done = await waitForJob(id, setJob);
      setHistory((h) => [{ q: q.trim(), job: done }, ...h].slice(0, 5));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The agent is unavailable right now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card ask" aria-labelledby="ask-title">
      <h2 id="ask-title">Ask the Cost-to-Serve Analyst</h2>
      <p className="muted">
        The analyst answers from deterministic metric tools; every figure is checked against the evidence ledger.
        Limited to a few questions per hour.
      </p>
      <form onSubmit={(e) => { e.preventDefault(); void submit(question); }}>
        <label htmlFor="q" className="sr-only">Question</label>
        <textarea id="q" maxLength={300} rows={2} value={question} placeholder="e.g. How much did it cost to serve bc-t0012 in October 2025?"
          onChange={(e) => setQuestion(e.target.value)} disabled={busy} />
        <button type="submit" disabled={busy || !question.trim()}>{busy ? "Working…" : "Ask"}</button>
      </form>
      <label htmlFor="persona" className="muted">Suggested questions for </label>
      <select id="persona" value={persona} onChange={(e) => setPersona(e.target.value)} disabled={busy}>
        {Object.keys(PERSONAS).map((p) => <option key={p}>{p}</option>)}
      </select>
      <div className="suggested">
        {PERSONAS[persona].map((s) => (
          <button key={s} type="button" className="chip" disabled={busy} onClick={() => { setQuestion(s); void submit(s); }}>{s}</button>
        ))}
      </div>
      <div aria-live="polite">
        {error && <p className="error">{error}</p>}
        {job && STATUS_TEXT[job.status] && <p className="muted">{STATUS_TEXT[job.status]}</p>}
        <AgentGraph trail={job?.trail} done={job?.status === "answered"} />
        <AgentSteps trail={job?.trail} />
        {job?.answer && (
          <div className="answer">
            <p>{job.answer}</p>
            {job.status === "needs_approval" && <ApprovalBox key={job.job_id} approver={job.approver} />}
            {job.evidence && job.evidence.length > 0 && (
              <details>
                <summary>Evidence ({job.evidence.length})</summary>
                {job.evidence.map((e) => (
                  <pre key={e.id}>{`[${e.id}] ${e.tool}(${JSON.stringify(e.args)})\n${JSON.stringify(e.result, null, 2)}`}</pre>
                ))}
              </details>
            )}
          </div>
        )}
      </div>
      {history.length > 1 && (
        <details className="history">
          <summary>Earlier questions ({history.length - 1})</summary>
          {history.slice(1).map((h) => (
            <p key={h.job.job_id}><strong>{h.q}</strong><br />{h.job.answer || STATUS_TEXT[h.job.status]}</p>
          ))}
        </details>
      )}
    </section>
  );
}
