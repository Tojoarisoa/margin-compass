{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/dim_feature.parquet') }}
select feature_id, name as feature_name, default_tier, batch_eligible
from read_parquet('{{ var("m2_landing_path") }}/features/features.parquet')
