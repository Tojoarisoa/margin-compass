{{ config(enabled=var('m2_landing_path', '') != '' and var('m2_realized', false),
          location=var('gold_path') ~ '/fct_realized_margin.parquet') }}
-- Grain: action x day. realized_margin_usd = cost saved + revenue delta (<= 0, revenue lost to ACT-3 churn; the AI
-- add-on is flat, so volume cuts alone change no revenue). Only rows past the 14-day window count as realized
-- (PLAN.md §8.4); the rest stay
-- pending_verification and carry no realized amount. approval_date_simulated: the approval was placed 60 days before
-- the data date (owner 2026-11-26), not on the owner's real decision date. Synthetic.
select
    action_id, day, counterfactual_cost_usd, actual_cost_usd, saved_usd, revenue_delta_usd, status, approval_date_simulated,
    case when status = 'realized' then saved_usd + revenue_delta_usd else 0 end as realized_margin_usd
from {{ ref('stg_m2_realized') }}
