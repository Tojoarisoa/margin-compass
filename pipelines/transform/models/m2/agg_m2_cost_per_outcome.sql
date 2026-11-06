{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/agg_m2_cost_per_outcome.parquet') }}
-- Grain: day x tenant. Cost (fct_m2_tenant_margin) and outcomes (fct_quality) at one grain so the registry's
-- cost_per_outcome (KPI-05) is a ratio of sums at any roll-up. Outcome = ticket resolved remotely (PLAN.md §3).
-- Cost to serve here is the tenant's whole fully loaded cost (all features), an assumption until cost is split by outcome type.
select
    coalesce(m.margin_date, q.outcome_date) as metric_date,
    coalesce(m.tenant_id, q.tenant_id) as tenant_id,
    cast(coalesce(m.cost_to_serve_usd, 0) as decimal(18, 6)) as cost_to_serve_usd,
    coalesce(q.resolved_remotely, 0) as resolved_remotely
from {{ ref('fct_m2_tenant_margin') }} m
full outer join {{ ref('fct_quality') }} q on q.outcome_date = m.margin_date and q.tenant_id = m.tenant_id
