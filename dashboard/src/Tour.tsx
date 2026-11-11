// Guided tour (M6-04): a short, skippable walk through the sections that exist on this page.
// Plain names only (public surface, AGENTS.md §6). Sections missing from the page are skipped.
import { useEffect, useState } from "react";

interface Step { id: string; title: string; text: string }

export const TOUR_STEPS: Step[] = [
  { id: "overview", title: "Margin at a glance", text: "Daily AI gross margin: revenue minus what every model call costs to serve, with a forecast band." },
  { id: "brief", title: "Daily brief", text: "What moved overnight and why. Every figure comes from a calculation, not from the language model." },
  { id: "actions", title: "Actions", text: "Recommended changes, each with the role that would approve it. Nothing changes a real system." },
  { id: "explore", title: "Explorer", text: "Pick a customer or feature to see what drives its cost and how quality compares." },
  { id: "leaks", title: "Margin leaks", text: "Stretches where a feature's AI cost jumped without the revenue to match, detected and sized." },
  { id: "plans", title: "Pricing and levers", text: "Try a plan price or an engineering lever. A saving only counts if quality holds." },
  { id: "health", title: "Data health", text: "Freshness and checks of the daily pipeline behind every number here." },
  { id: "ask", title: "Ask the analyst", text: "Ask in plain English. Answers cite their evidence and refuse what the data can't support." },
  { id: "about", title: "About", text: "How it is built. All data on this page is synthetic." },
];

const card: React.CSSProperties = {
  position: "fixed", left: 16, right: 16, bottom: 16, maxWidth: 420, margin: "0 auto", zIndex: 50,
  background: "var(--card-solid)", color: "var(--text)", border: "1px solid var(--line-strong)", borderRadius: 10,
  padding: "12px 14px", boxShadow: "0 6px 24px rgba(0,0,0,.25)",
};

export function presentSteps(has: (id: string) => boolean): Step[] {
  return TOUR_STEPS.filter((s) => has(s.id));
}

export function Tour() {
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [i, setI] = useState(0);
  const step = steps?.[i];

  useEffect(() => {
    if (step) document.getElementById(step.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [step]);
  useEffect(() => {
    if (!steps) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSteps(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [steps]);

  const start = () => { setI(0); setSteps(presentSteps((id) => document.getElementById(id) !== null)); };
  return (
    <>
      <button type="button" className="small" onClick={start} aria-haspopup="dialog">Take the tour</button>
      {steps && step && (
        <div role="dialog" aria-label="Guided tour" aria-live="polite" style={card}>
          <p className="small muted" style={{ margin: 0 }}>{i + 1} of {steps.length}</p>
          <strong>{step.title}</strong>
          <p style={{ margin: "6px 0 10px" }}>{step.text}</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" onClick={() => setSteps(null)}>Close</button>
            <button type="button" onClick={() => setI(i - 1)} disabled={i === 0}>Back</button>
            {i < steps.length - 1
              ? <button type="button" onClick={() => setI(i + 1)}>Next</button>
              : <button type="button" onClick={() => setSteps(null)}>Done</button>}
          </div>
        </div>
      )}
    </>
  );
}
