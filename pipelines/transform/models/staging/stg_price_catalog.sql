select model_id, provider, tier, input_usd_per_mtok, output_usd_per_mtok, cache_read_usd_per_mtok,
       effective_from, coalesce(effective_to, date '9999-12-31') as effective_to
from {{ bronze('s5_price_catalog/price_catalog.parquet') }}
