{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('silver_path') ~ '/slv_m2_revenue_daily.parquet') }}
-- Daily-izes each M2 invoice line (subscription, AI add-on, discount) across its billing period, exact to the
-- cent: cents are split evenly and the remainder cents go to the first days, so days sum to the invoice.
-- Floor division is taken on the absolute value so negative (discount) lines split symmetrically.
with lines as (
    select *,
        cast(round(amount_usd * 100) as bigint) as amount_cents,
        datediff('day', billing_period_start, billing_period_end) as period_days
    from {{ ref('stg_m2_invoices') }}
),
days as (
    select l.*, d.revenue_date, datediff('day', l.billing_period_start, d.revenue_date) as day_index
    from lines l,
         lateral (select unnest(generate_series(l.billing_period_start, l.billing_period_end - interval 1 day, interval 1 day))::date as revenue_date) d
)
select
    revenue_date, tenant_id, invoice_id, line_type as revenue_component,
    billing_period_start, billing_period_end,
    cast(sign(amount_cents) * (abs(amount_cents) // period_days
         + case when day_index < abs(amount_cents) % period_days then 1 else 0 end) / 100.0 as decimal(14, 2)) as amount_usd
from days
