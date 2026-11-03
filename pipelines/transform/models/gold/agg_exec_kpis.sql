{{ config(location=var('gold_path') ~ '/agg_exec_kpis.parquet') }}
-- Grain: day. Pre-aggregated KPIs for the dashboard (PLAN.md §4.2). M1 covers KPI-01, KPI-03, KPI-04.
-- unallocated_llm_cost_usd is computed independently of the margin fact (usage rows that can't be
-- matched to a known tenant, a known feature, or the simulated window), so the cost-preservation
-- gate "allocated + unallocated = total" is not true by construction.
with margin as (
    select margin_date, tenant_id, sum(ai_revenue_usd) as ai_revenue_usd, sum(cost_to_serve_usd) as cost_usd
    from {{ ref('fct_tenant_margin') }}
    group by all
),
usage as (
    select u.usage_date, u.llm_cost_usd,
           (t.tenant_id is null or u.feature_id is null or u.feature_id not in ('F1')
            or u.usage_date not between date '{{ var("window_start") }}' and date '{{ var("window_end") }}') as is_unallocated
    from {{ ref('fct_llm_usage_daily') }} u
    left join {{ ref('stg_tenants') }} t on t.tenant_id = u.tenant_id
),
spend as (
    select usage_date,
           sum(llm_cost_usd) as llm_spend_usd,
           sum(case when is_unallocated then llm_cost_usd else 0 end) as unallocated_llm_cost_usd
    from usage
    group by all
),
total_revenue as (
    select revenue_date, sum(amount_usd) as total_revenue_usd
    from {{ ref('fct_revenue_daily') }}
    group by all
)
select
    m.margin_date as kpi_date,
    cast(tr.total_revenue_usd as decimal(18, 2)) as total_revenue_usd,
    cast(sum(m.ai_revenue_usd) as decimal(18, 2)) as ai_revenue_usd,
    cast(sum(m.cost_usd) as decimal(18, 6)) as ai_cost_to_serve_usd,
    round(cast((sum(m.ai_revenue_usd) - sum(m.cost_usd)) / nullif(sum(m.ai_revenue_usd), 0) as double), 6) as kpi01_ai_gross_margin_pct,
    cast(coalesce(s.llm_spend_usd, 0) as decimal(18, 6)) as llm_spend_usd,
    cast(coalesce(s.unallocated_llm_cost_usd, 0) as decimal(18, 6)) as unallocated_llm_cost_usd,
    round(cast(coalesce(1 - s.unallocated_llm_cost_usd / nullif(s.llm_spend_usd, 0), 1) as double), 6) as kpi03_llm_attribution_coverage_pct,
    cast(count(*) filter (where m.ai_revenue_usd - m.cost_usd < 0) as bigint) as kpi04_unprofitable_tenants,
    cast(coalesce(sum(t.arr_usd) filter (where m.ai_revenue_usd - m.cost_usd < 0), 0) as decimal(18, 2)) as kpi04_unprofitable_arr_usd,
    '{{ var("feature_scope") }}' as feature_scope,
    '{{ var("run_id") }}' as run_id
from margin m
join {{ ref('stg_tenants') }} t on t.tenant_id = m.tenant_id
left join spend s on s.usage_date = m.margin_date
left join total_revenue tr on tr.revenue_date = m.margin_date
group by m.margin_date, tr.total_revenue_usd, s.llm_spend_usd, s.unallocated_llm_cost_usd
