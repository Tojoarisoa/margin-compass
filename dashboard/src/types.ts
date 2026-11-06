// Shape of publish/latest/pg1.json (schema pg1.v0), written by pipelines/mc_pipelines/publish.py.
export interface Totals {
  ai_revenue_usd: number;
  ai_cost_to_serve_usd: number;
  ai_gross_margin_usd: number;
  ai_gross_margin_pct: number | null;
}
export interface TenantRow extends Totals {
  tenant_id: string;
  plan: string | null;
  request_count: number;
}
export interface Snapshot {
  schema_version: "pg1.v0";
  page: string;
  generated_at: string;
  run_id: string;
  ingest_date: string;
  data_label: "synthetic";
  feature_scope: string;
  window: { from: string; to: string; days: number };
  headline: {
    window: Totals;
    last_30_days: Totals & { from: string; to: string };
    total_revenue_usd: number;
    llm_attribution_coverage_pct: number | null;
    unprofitable_tenants: number;
    tenants: number;
  };
  trend: { date: string; ai_revenue_usd: number; ai_cost_to_serve_usd: number; ai_gross_margin_pct: number | null }[];
  forecast: { metric: string; model_version: string | null; model_alias: string | null; points: { date: string; p10: number; p50: number; p90: number }[] };
  tenants: TenantRow[];
  /** Present when the M2 marts exist: registry KPIs over the whole window (metrics/metrics.yml). */
  m2_kpis?: Record<string, number | null>;
  not_yet_available: Record<string, string>;
}
