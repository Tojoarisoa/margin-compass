select
    usage_date,
    tenant_id,
    feature_id,
    gen_ai_provider_name as provider,
    gen_ai_request_model as model_id,
    gen_ai_operation_name as operation,
    request_count,
    gen_ai_usage_input_tokens as input_tokens,  -- includes cached tokens (ADR-015)
    gen_ai_usage_cache_read_input_tokens as cached_input_tokens,
    gen_ai_usage_output_tokens as output_tokens,
    retry_count
from {{ bronze('s1_llm_telemetry/telemetry_daily.parquet') }}
