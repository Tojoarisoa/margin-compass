// PG-9 Architecture & About. Static text and a simple diagram; no data fetch, no per-answer figures.
const STAGES: { name: string; text: string }[] = [
  { name: "Simulate", text: "A generator produces a year and a half of telemetry for a fictional AI product (BoonCore): requests, tokens, outcomes and the shared infrastructure behind them." },
  { name: "Ingest and model", text: "Raw files land in object storage, are checked against data contracts, and are modelled into cost-to-serve and margin tables." },
  { name: "Analyse", text: "Forecasts, margin-leak detection and churn scoring read those tables and write their results back as data." },
  { name: "Answer", text: "Questions go to a small set of read-only agents. Every number in an answer comes from a deterministic tool and is checked against an evidence ledger before it is shown." },
  { name: "Decide", text: "Pricing and lever simulators run the same calculation in the browser and in the agents, so a figure never differs between the two." },
];

export default function About() {
  return (
    <div>
      <ol className="about-flow" aria-label="Architecture">
        {STAGES.map((s) => (
          <li key={s.name}><strong>{s.name}.</strong> {s.text}</li>
        ))}
      </ol>
      <h3>What this is</h3>
      <p className="muted">
        A worked example of AI margin management: it shows what each customer, feature and request costs to serve, where
        margin leaks, and which pricing or engineering changes would recover it without hurting quality.
      </p>
      <h3>Limitations</h3>
      <ul className="muted">
        <li>All data is synthetic. Tenants, prices and usage are simulated, so the figures illustrate the method, not a real business.</li>
        <li>Agents only read data and propose actions. Nothing is changed in any system; approvals are simulated records.</li>
        <li>Forecasts and the churn model are baselines trained on simulated history and carry wide uncertainty.</li>
        <li>A cost-saving lever is counted only when a quality check supports it.</li>
      </ul>
    </div>
  );
}
