{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- M2 telemetry from the monthly landing chunks (all months under the landing path). Synthetic data.
select
    cast(usage_ts as timestamp) as usage_ts,
    cast(usage_ts as date) as usage_date,
    grain, tenant_id, feature_id,
    gen_ai_provider_name as provider,
    gen_ai_request_model as model_id,
    gen_ai_operation_name as operation,
    is_batch, request_count,
    gen_ai_usage_input_tokens as input_tokens,  -- includes cached tokens (ADR-015)
    gen_ai_usage_cache_read_input_tokens as cached_input_tokens,
    gen_ai_usage_output_tokens as output_tokens,
    retry_count
from read_parquet('{{ var("m2_landing_path") }}/s1_llm_telemetry/month=*/telemetry.parquet')
