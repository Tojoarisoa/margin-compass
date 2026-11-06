{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('silver_path') ~ '/slv_m2_llm_usage_priced.parquet') }}
-- M2 telemetry priced against the effective-dated catalog, with cached and batch rates (m2-plan.md M2-02.1).
-- Cached tokens are part of input tokens, so they're priced once, at the cache-read rate.
-- The batch discount applies to the whole row; a batch row on a model without batch pricing prices to NULL
-- and fails the not-null test rather than being silently priced at list.
select
    u.usage_ts, u.usage_date, u.grain, u.tenant_id, u.feature_id, u.provider, u.model_id, u.is_batch,
    u.request_count, u.input_tokens, u.cached_input_tokens,
    u.input_tokens - u.cached_input_tokens as uncached_input_tokens,
    u.output_tokens, u.retry_count,
    p.effective_from as price_effective_from,
    cast((
        (u.input_tokens - u.cached_input_tokens) * p.input_usd_per_mtok
        + u.cached_input_tokens * coalesce(p.cache_read_usd_per_mtok, 0)
        + u.output_tokens * p.output_usd_per_mtok
    ) / 1000000.0
      * case when u.is_batch then 1 - p.batch_discount_pct else 1 end as decimal(18, 6)) as llm_cost_usd
from {{ ref('stg_m2_telemetry') }} u
left join {{ ref('stg_m2_price_catalog') }} p
    on p.model_id = u.model_id
   and u.usage_date >= p.effective_from and u.usage_date < p.effective_to
