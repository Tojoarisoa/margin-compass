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
  /** Present with m2_kpis: fully loaded cost to serve per feature (revenue is per tenant, so no per-feature margin %). */
  m2_features?: FeatureCost[];
  /** Present with m2_kpis: tenants with negative fully loaded margin over the window and the ARR they carry. */
  m2_at_risk?: AtRisk;
  /** Present with m2_kpis: margin % band for the forecast days (revenue held at the last-30-day mean). */
  m2_margin_forecast?: { assumption: string; daily_revenue_usd?: number; points: { date: string; low: number | null; mid: number | null; high: number | null }[] };
  not_yet_available: Record<string, string>;
}

export interface FeatureCost {
  feature_id: string; feature_name: string | null; requests: number; llm_cost_usd: number; agent_compute_usd: number;
  vector_usd: number; network_observability_usd: number; third_party_usd: number; cost_to_serve_usd: number; cost_share: number | null;
}

export interface AtRisk {
  unprofitable_tenants: number; arr_at_risk_usd: number;
  worst: { tenant_id: string; plan: string | null; arr_usd: number; revenue_usd: number; cost_to_serve_usd: number; margin_usd: number }[];
}
