{{ config(severity='error', tags=['preservation']) }}
-- PLAN.md §6.2 Stage 2 gate, at the gold grain: per tenant, component, and billing period, the sum of
-- fct_revenue_daily equals the invoices, exactly.
with invoiced as (
    select tenant_id, line_type as revenue_component, billing_period_start, billing_period_end, sum(amount_usd) as invoiced
    from {{ ref('stg_invoices') }} group by all
), gold as (
    select i.tenant_id, i.revenue_component, i.billing_period_start, sum(g.amount_usd) as daily_total
    from invoiced i
    join {{ ref('fct_revenue_daily') }} g
      on g.tenant_id = i.tenant_id and g.revenue_component = i.revenue_component
     and g.revenue_date >= i.billing_period_start and g.revenue_date < i.billing_period_end
    group by all
)
select i.*, g.daily_total
from invoiced i left join gold g using (tenant_id, revenue_component, billing_period_start)
where g.daily_total is null or g.daily_total != i.invoiced
