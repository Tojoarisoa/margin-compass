// Scenario difference v1 (calc-spec/README.md, ADR-016): signed after-minus-before changes. Integer arithmetic only;
// matches agents/mc_agents/tools/scenario_delta.py on every vector in calc-spec/vectors/delta_v1.json (EV-12). Synthetic inputs only.

export const DELTA_FIELDS = ["revenue_cents", "margin_cents", "margin_bps", "adj_revenue_cents", "adj_margin_cents"] as const;
type Side = Partial<Record<(typeof DELTA_FIELDS)[number], number | null>>;

export function scenarioDelta(inp: { before: Side; after: Side }): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const f of DELTA_FIELDS) {
    const hasB = f in inp.before;
    if (hasB !== f in inp.after) throw new Error(`${f} must be given on both sides or neither`);
    if (!hasB) continue;
    const b = inp.before[f] ?? null;
    const a = inp.after[f] ?? null;
    for (const v of [b, a]) if (v !== null && !Number.isSafeInteger(v)) throw new Error(`${f} must be an integer or null`);
    if ((b === null || a === null) && f !== "margin_bps") throw new Error(`${f} must be an integer`);
    out[`${f}_change`] = b === null || a === null ? null : a - b;
  }
  if (Object.keys(out).length === 0) throw new Error("no comparable fields");
  return out;
}
