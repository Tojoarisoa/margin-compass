{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- Simulated S2 shared-infrastructure export (FOCUS 1.2). The real S7 export shares this contract, so both
-- load through the same columns. x-feature and x-env tags are kept as columns; an untagged row keeps NULLs
-- and is routed to the unallocated bucket by the allocation step, not dropped here.
select
    cast(charge_period_start as date) as charge_date,
    cast(billing_period_start as date) as billing_period_start,
    billing_account_id, provider_name, service_name, service_category, sku_id,
    charge_category, pricing_unit,
    cast(consumed_quantity as double) as consumed_quantity,
    cast(billed_cost as decimal(18, 4)) as billed_cost,
    cast(effective_cost as decimal(18, 4)) as effective_cost,
    cast(list_cost as decimal(18, 4)) as list_cost,
    billing_currency,
    nullif(tag_feature, '') as feature_tag,
    nullif(tag_env, '') as env_tag
from read_parquet('{{ var("m2_landing_path") }}/s2_focus/focus.parquet')
