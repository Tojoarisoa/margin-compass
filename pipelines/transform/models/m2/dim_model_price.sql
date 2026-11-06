{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/dim_model_price.parquet') }}
-- Effective-dated model prices (effective_from inclusive, effective_to exclusive; open = 9999-12-31).
select * from {{ ref('stg_m2_price_catalog') }}
