select invoice_id, tenant_id, billing_period_start, billing_period_end, line_type, amount_usd, currency
from {{ bronze('s3_revenue/invoices.parquet') }}
