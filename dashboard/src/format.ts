// Display formatting only. Every figure is computed by the pipeline (publish step) or the agent's tools.
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int = new Intl.NumberFormat("en-US");

export const money = (x: number) => usd.format(x);
export const count = (x: number) => int.format(x);
export const percent = (ratio: number | null, digits = 2) => (ratio === null ? "n/a" : `${(ratio * 100).toFixed(digits)}%`);
