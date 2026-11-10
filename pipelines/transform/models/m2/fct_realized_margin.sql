{{ config(enabled=var('m2_landing_path', '') != '' and var('m2_realized', false),
          location=var('gold_path') ~ '/fct_realized_margin.parquet') }}
-- Grain: action x day. Cost side only (revenue from volume change is a later step, so realized_margin_usd equals
-- saved_usd for now). Only rows past the 14-day measurement window count as realized (PLAN.md §8.4); the rest stay
-- pending_verification and carry no realized amount. Synthetic.
select
    action_id, day, counterfactual_cost_usd, actual_cost_usd, saved_usd, status,
    case when status = 'realized' then saved_usd else 0 end as realized_margin_usd
from {{ ref('stg_m2_realized') }}
