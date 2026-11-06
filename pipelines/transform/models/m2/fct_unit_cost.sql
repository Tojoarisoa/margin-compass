{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/fct_unit_cost.parquet') }}
-- Grain: day x feature x model. Sums, plus unit costs recomputed from those sums (never averaged across rows).
-- Cost per 1k tokens uses all tokens in the row (input + output); cached input is part of input (ADR-015).
with s as (
    select usage_date as cost_date, feature_id, model_id,
           sum(request_count) as requests,
           sum(input_tokens) as input_tokens, sum(cached_input_tokens) as cached_input_tokens,
           sum(output_tokens) as output_tokens, sum(llm_cost_usd) as llm_cost_usd
    from {{ ref('slv_m2_llm_usage_priced') }}
    group by all
)
select cost_date, feature_id, model_id, requests, input_tokens, cached_input_tokens, output_tokens,
       cast(llm_cost_usd as decimal(18, 6)) as llm_cost_usd,
       cast(llm_cost_usd / nullif(requests, 0) as decimal(18, 8)) as cost_per_request_usd,
       cast(llm_cost_usd * 1000 / nullif(input_tokens + output_tokens, 0) as decimal(18, 8)) as cost_per_1k_tokens_usd,
       cast(cached_input_tokens * 1.0 / nullif(input_tokens, 0) as decimal(9, 6)) as cache_hit_share
from s
