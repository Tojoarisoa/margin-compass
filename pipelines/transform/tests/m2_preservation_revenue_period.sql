{{ config(enabled=var('m2_gates', false) and var('m2_landing_path', '') != '', severity='error', tags=['preservation', 'm2']) }}
-- M2 gate (enabled with var m2_gates, so subset builds in tests do not pick it up): revenue per tenant and billing period in the margin mart equals the invoices for that period.
-- The margin mart is built on daily revenue, so each period is the sum of its days.
select i.tenant_id, i.billing_period_start, i.invoiced, coalesce(m.margin_revenue, 0) as margin_revenue
from (select tenant_id, billing_period_start, billing_period_end, sum(amount_usd) as invoiced
      from {{ ref('stg_m2_invoices') }} group by all) i
left join lateral (
    select sum(revenue_usd) as margin_revenue from {{ ref('fct_m2_tenant_margin') }} m
    where m.tenant_id = i.tenant_id and m.margin_date >= i.billing_period_start and m.margin_date < i.billing_period_end
) m on true
where coalesce(m.margin_revenue, 0) <> i.invoiced
