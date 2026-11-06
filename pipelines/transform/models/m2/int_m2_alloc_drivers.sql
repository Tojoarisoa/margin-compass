{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- Allocation drivers per day x tenant x feature from the priced telemetry (hourly rows are rolled up to the day).
-- cumulative_input_tokens grows over the tenant's history (stored volume proxy for vector storage).
with daily as (
    select usage_date, tenant_id, feature_id,
           sum(request_count) as requests,
           sum(input_tokens + output_tokens) as tokens,
           sum(input_tokens) as input_tokens
    from {{ ref('slv_m2_llm_usage_priced') }}
    group by all
)
select usage_date, tenant_id, feature_id, requests, tokens,
       sum(input_tokens) over (partition by tenant_id, feature_id order by usage_date) as cumulative_input_tokens
from daily
