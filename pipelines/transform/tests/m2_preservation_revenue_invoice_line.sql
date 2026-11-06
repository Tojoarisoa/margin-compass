{{ config(enabled=var('m2_gates', false) and var('m2_landing_path', '') != '', severity='error', tags=['preservation', 'm2']) }}
-- M2 gate (enabled with var m2_gates, so subset builds in tests do not pick it up): the daily-ized revenue of every invoice line sums to the invoice line, to the cent.
-- Returns the lines that differ (including lines with no daily rows).
select i.invoice_id, i.line_type, i.amount_usd as invoiced, coalesce(d.daily, 0) as daily
from (select invoice_id, line_type, sum(amount_usd) as amount_usd from {{ ref('stg_m2_invoices') }} group by all) i
left join (select invoice_id, revenue_component, sum(amount_usd) as daily
           from {{ ref('slv_m2_revenue_daily') }} group by all) d
  on d.invoice_id = i.invoice_id and d.revenue_component = i.line_type
where coalesce(d.daily, 0) <> i.amount_usd
