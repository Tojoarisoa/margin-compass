{{ config(enabled=var('m2_landing_path', '') != '', materialized='view') }}
-- M2 effective-dated catalog: effective_from inclusive, effective_to exclusive (open = 9999-12-31).
select model_id, provider, tier, input_usd_per_mtok, output_usd_per_mtok, cache_read_usd_per_mtok,
       batch_discount_pct, effective_from, coalesce(effective_to, date '9999-12-31') as effective_to
from read_parquet('{{ var("m2_landing_path") }}/s5_price_catalog/price_catalog.parquet')
