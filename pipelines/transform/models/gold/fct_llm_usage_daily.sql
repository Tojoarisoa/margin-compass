{{ config(location=var('gold_path') ~ '/fct_llm_usage_daily.parquet') }}
-- Grain: day x tenant x feature x model (PLAN.md §7.3).
select usage_date, tenant_id, feature_id, provider, model_id, request_count, input_tokens,
       uncached_input_tokens, cached_input_tokens, output_tokens, retry_count, price_effective_from, llm_cost_usd
from {{ ref('slv_llm_usage_priced') }}
