{{ config(location=var('gold_path') ~ '/agg_exec_kpis.parquet') }}
-- Grain: day. Pre-aggregated KPIs for the dashboard (PLAN.md §4.2). M1 covers KPI-01, KPI-03, KPI-04.
with margin as (
    select margin_date, tenant_id, sum(ai_revenue_usd) as ai_revenue_usd, sum(cost_to_serve_usd) as cost_usd
    from {{ ref('fct_tenant_margin') }}
    group by all
),
spend as (
    select usage_date,
           sum(llm_cost_usd) as llm_spend_usd,
           sum(case when tenant_id is not null and feature_id is not null then llm_cost_usd else 0 end) as attributed_llm_spend_usd
    from {{ ref('fct_llm_usage_daily') }}
    group by all
),
total_revenue as (
    select revenue_date, sum(amount_usd) as total_revenue_usd
    from {{ ref('fct_revenue_daily') }}
    group by all
)
select
    m.margin_date as kpi_date,
    tr.total_revenue_usd,
    sum(m.ai_revenue_usd) as ai_revenue_usd,
    sum(m.cost_usd) as ai_cost_to_serve_usd,
    round((sum(m.ai_revenue_usd) - sum(m.cost_usd)) / nullif(sum(m.ai_revenue_usd), 0), 6) as kpi01_ai_gross_margin_pct,
    coalesce(s.llm_spend_usd, 0) as llm_spend_usd,
    round(coalesce(s.attributed_llm_spend_usd / nullif(s.llm_spend_usd, 0), 1), 6) as kpi03_llm_attribution_coverage_pct,
    count(*) filter (where m.ai_revenue_usd - m.cost_usd < 0) as kpi04_unprofitable_tenants,
    coalesce(sum(t.arr_usd) filter (where m.ai_revenue_usd - m.cost_usd < 0), 0) as kpi04_unprofitable_arr_usd,
    '{{ var("feature_scope") }}' as feature_scope,
    '{{ var("run_id") }}' as run_id
from margin m
join {{ ref('stg_tenants') }} t on t.tenant_id = m.tenant_id
left join spend s on s.usage_date = m.margin_date
left join total_revenue tr on tr.revenue_date = m.margin_date
group by m.margin_date, tr.total_revenue_usd, s.llm_spend_usd, s.attributed_llm_spend_usd
