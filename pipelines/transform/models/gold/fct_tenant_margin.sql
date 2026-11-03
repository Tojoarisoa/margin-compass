{{ config(location=var('gold_path') ~ '/fct_tenant_margin.parquet') }}
-- Grain: day x tenant x feature (PLAN.md §7.3), over the simulated window only.
-- M1 rules (revisit in M2-01/M2-02):
--   * AI-feature revenue = the daily-ized AI add-on, attributed to F1, the only AI feature in M1.
--   * Cost-to-serve = LLM token cost only (shared-infrastructure allocation arrives in M2-02).
with spine as (
    select d::date as margin_date, t.tenant_id, 'F1' as feature_id
    from generate_series(date '{{ var("window_start") }}', date '{{ var("window_end") }}', interval 1 day) as g(d)
    cross join {{ ref('stg_tenants') }} t
),
revenue as (
    select revenue_date, tenant_id, sum(amount_usd) as ai_revenue_usd
    from {{ ref('fct_revenue_daily') }}
    where revenue_component = 'ai_addon'
    group by all
),
cost as (
    select usage_date, tenant_id, feature_id, sum(llm_cost_usd) as llm_cost_usd, sum(request_count) as request_count
    from {{ ref('fct_llm_usage_daily') }}
    group by all
)
select
    s.margin_date, s.tenant_id, s.feature_id,
    coalesce(r.ai_revenue_usd, 0) as ai_revenue_usd,
    coalesce(c.llm_cost_usd, 0) as llm_cost_usd,
    coalesce(c.llm_cost_usd, 0) as cost_to_serve_usd,
    coalesce(r.ai_revenue_usd, 0) - coalesce(c.llm_cost_usd, 0) as gross_margin_usd,
    case when coalesce(r.ai_revenue_usd, 0) > 0
         then round((coalesce(r.ai_revenue_usd, 0) - coalesce(c.llm_cost_usd, 0)) / r.ai_revenue_usd, 6) end as gross_margin_pct,
    coalesce(c.request_count, 0) as request_count,
    '{{ var("feature_scope") }}' as feature_scope
from spine s
left join revenue r on r.revenue_date = s.margin_date and r.tenant_id = s.tenant_id
left join cost c on c.usage_date = s.margin_date and c.tenant_id = s.tenant_id and c.feature_id = s.feature_id
