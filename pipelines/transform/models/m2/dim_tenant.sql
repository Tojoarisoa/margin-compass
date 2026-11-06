{{ config(enabled=var('m2_landing_path', '') != '',
          location=var('gold_path') ~ '/dim_tenant.parquet') }}
-- SCD2 tenant dimension: one row per plan version (valid_from inclusive, valid_to exclusive, NULL = current),
-- with the static tenant attributes. Join facts on tenant_id and date >= valid_from and (valid_to is null or date < valid_to).
select
    h.tenant_id, h.valid_from, h.valid_to, h.plan, h.arr_usd, h.ai_addon_arr_usd, h.discount_pct, h.is_current,
    t.segment, t.unlimited_ai, t.approved_models, t.data_residency, t.allowed_providers,
    t.fiscal_year_end, t.onboarded_on, t.contract_start, t.renewal_date
from read_parquet('{{ var("m2_landing_path") }}/tenants/plan_history.parquet') h
join read_parquet('{{ var("m2_landing_path") }}/tenants/tenants.parquet') t using (tenant_id)
