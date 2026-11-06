{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- M2 invoice lines (S3). Discount lines are negative.
select invoice_id, tenant_id,
       cast(billing_period_start as date) as billing_period_start,
       cast(billing_period_end as date) as billing_period_end,
       line_type, cast(amount_usd as decimal(14, 2)) as amount_usd
from read_parquet('{{ var("m2_landing_path") }}/s3_revenue/invoices.parquet')
