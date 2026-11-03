{{ config(severity='error', tags=['preservation']) }}
-- PLAN.md §6.2 Stage 2 gate: daily-ized revenue equals invoiced revenue, exactly, for every invoice line.
with daily as (
    select invoice_id, revenue_component as line_type, sum(amount_usd) as daily_total
    from {{ ref('slv_revenue_daily') }} group by all
)
select i.invoice_id, i.line_type, i.amount_usd, d.daily_total
from {{ ref('stg_invoices') }} i
left join daily d using (invoice_id, line_type)
where d.daily_total is null or d.daily_total != i.amount_usd
