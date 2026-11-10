{{ config(enabled=var('m2_landing_path', '') != '' and var('m2_realized', false), materialized='view') }}
-- M5-04: realized cost effect per approved action x day (counterfactual minus actual). Synthetic data.
select
    action_id, cast(day as date) as day, counterfactual_cost_usd, actual_cost_usd, saved_usd, revenue_delta_usd, status
from read_parquet('{{ var("m2_landing_path") }}/s5_realized/realized_cost.parquet')
