{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/fct_m2_tenant_margin.parquet') }}
-- Grain: day x tenant. Fully loaded margin: all daily-ized revenue (subscription, AI add-on, discount) minus
-- fct_cost_to_serve (LLM + allocated infrastructure). Unallocated infrastructure is NOT charged to any tenant;
-- it is reported in fct_infra_cost_allocated (rule_id = 'UNALLOCATED') and by the cost-preservation gate.
-- Overage revenue is not simulated yet (flat add-on only). margin_pct is NULL on days without revenue.
-- Named fct_m2_tenant_margin beside the M1 fct_tenant_margin until the M1 profile is retired.
with revenue as (
    select revenue_date as margin_date, tenant_id,
           sum(amount_usd) as revenue_usd,
           sum(amount_usd) filter (where revenue_component = 'discount') as discount_usd
    from {{ ref('slv_m2_revenue_daily') }}
    group by all
),
cost as (
    select cost_date as margin_date, tenant_id,
           sum(llm_cost_usd) as llm_cost_usd, sum(infra_cost_usd) as infra_cost_usd,
           sum(cost_to_serve_usd) as cost_to_serve_usd
    from {{ ref('fct_cost_to_serve') }}
    group by all
)
select
    coalesce(r.margin_date, c.margin_date) as margin_date,
    coalesce(r.tenant_id, c.tenant_id) as tenant_id,
    cast(coalesce(r.revenue_usd, 0) as decimal(18, 2)) as revenue_usd,
    cast(coalesce(r.discount_usd, 0) as decimal(18, 2)) as discount_usd,
    cast(coalesce(c.llm_cost_usd, 0) as decimal(18, 6)) as llm_cost_usd,
    cast(coalesce(c.infra_cost_usd, 0) as decimal(18, 4)) as infra_cost_usd,
    cast(coalesce(c.cost_to_serve_usd, 0) as decimal(18, 6)) as cost_to_serve_usd,
    cast(coalesce(r.revenue_usd, 0) - coalesce(c.cost_to_serve_usd, 0) as decimal(18, 6)) as margin_usd,
    cast((coalesce(r.revenue_usd, 0) - coalesce(c.cost_to_serve_usd, 0)) / nullif(r.revenue_usd, 0) as decimal(12, 6)) as margin_pct
from revenue r
full outer join cost c on c.margin_date = r.margin_date and c.tenant_id = r.tenant_id
