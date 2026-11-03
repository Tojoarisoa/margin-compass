{{ config(location=var('gold_path') ~ '/fct_revenue_daily.parquet') }}
-- Grain: day x tenant x revenue component (PLAN.md §7.3). Amounts are net of negotiated discounts.
select r.revenue_date, r.tenant_id, r.revenue_component, sum(r.amount_usd) as amount_usd, any_value(r.currency) as currency,
       any_value(t.plan) as plan, any_value(t.discount_pct) as discount_pct
from {{ ref('slv_revenue_daily') }} r
join {{ ref('stg_tenants') }} t using (tenant_id)
group by all
