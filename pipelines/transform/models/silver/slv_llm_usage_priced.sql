{{ config(location=var('silver_path') ~ '/slv_llm_usage_priced.parquet') }}
-- Token cost priced against the effective-dated catalog (PLAN.md §6.2 Stage 2).
-- Cached tokens are part of input tokens, so they're priced once at the cache-read rate.
select
    u.usage_date, u.tenant_id, u.feature_id, u.provider, u.model_id, u.request_count,
    u.input_tokens, u.cached_input_tokens, u.input_tokens - u.cached_input_tokens as uncached_input_tokens,
    u.output_tokens, u.retry_count,
    p.effective_from as price_effective_from,
    cast((
        (u.input_tokens - u.cached_input_tokens) * p.input_usd_per_mtok
        + u.cached_input_tokens * p.cache_read_usd_per_mtok
        + u.output_tokens * p.output_usd_per_mtok
    ) / 1000000.0 as decimal(18, 6)) as llm_cost_usd
from {{ ref('stg_llm_telemetry') }} u
left join {{ ref('stg_price_catalog') }} p
    on p.model_id = u.model_id
   and u.usage_date between p.effective_from and p.effective_to
