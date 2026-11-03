select tenant_id, segment, plan, arr_usd, ai_addon_arr_usd, discount_pct, unlimited_ai, contract_start, renewal_date
from {{ bronze('tenants/tenants.parquet') }}
