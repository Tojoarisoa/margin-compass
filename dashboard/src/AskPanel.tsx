import { useState } from "react";
import { ApiError, ask, waitForJob, type Job } from "./api";

const SUGGESTED = [
  "What was the AI gross margin for tenant bc-t0003 in September 2025?",
  "Which three tenants had the lowest AI gross margin percentage from August 1 to October 29, 2025?",
  "What was the portfolio AI gross margin in August 2025?",
];

const STATUS_TEXT: Record<Job["status"], string> = {
  pending: "Queued…", running: "Thinking…", answered: "", unverified: "Answer withheld", budget_exceeded: "Unavailable right now", error: "Error",
};

export function AskPanel() {
  const [question, setQuestion] = useState("");
  const [job, setJob] = useState<Job | null>(null);
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
      await waitForJob(id, setJob);
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
      <div className="suggested">
        {SUGGESTED.map((s) => (
          <button key={s} type="button" className="chip" disabled={busy} onClick={() => { setQuestion(s); void submit(s); }}>{s}</button>
        ))}
      </div>
      <div aria-live="polite">
        {error && <p className="error">{error}</p>}
        {job && STATUS_TEXT[job.status] && <p className="muted">{STATUS_TEXT[job.status]}</p>}
        {job?.answer && (
          <div className="answer">
            <p>{job.answer}</p>
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
    </section>
  );
}
