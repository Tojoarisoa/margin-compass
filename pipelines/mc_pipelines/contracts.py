"""Expected landing schemas (docs/data-contracts/booncore-landing-m1.md).

Kept independent of the producer on purpose: if the simulator's output drifts from the contract,
ingest quarantines the file instead of passing the drift downstream (PLAN.md §6.2 Stage 1).
"""

from __future__ import annotations

import hashlib

MONEY = "decimal128(14, 2)"
PCT = "decimal128(5, 2)"

EXPECTED_SCHEMAS: dict[str, list[tuple[str, str]]] = {
    "tenants/tenants.parquet": [
        ("tenant_id", "string"), ("segment", "string"), ("plan", "string"), ("arr_usd", MONEY),
        ("ai_addon_arr_usd", MONEY), ("discount_pct", PCT), ("unlimited_ai", "bool"),
        ("contract_start", "date32[day]"), ("renewal_date", "date32[day]"),
    ],
    "s1_llm_telemetry/telemetry_daily.parquet": [
        ("usage_date", "date32[day]"), ("tenant_id", "string"), ("feature_id", "string"),
        ("gen_ai_provider_name", "string"), ("gen_ai_request_model", "string"), ("gen_ai_operation_name", "string"),
        ("request_count", "int64"), ("gen_ai_usage_input_tokens", "int64"), ("gen_ai_usage_output_tokens", "int64"),
        ("gen_ai_usage_cache_read_input_tokens", "int64"), ("retry_count", "int64"),
    ],
    "s3_revenue/subscriptions.parquet": [
        ("tenant_id", "string"), ("plan", "string"), ("contract_start", "date32[day]"), ("renewal_date", "date32[day]"),
        ("arr_usd", MONEY), ("ai_addon_arr_usd", MONEY), ("discount_pct", PCT), ("unlimited_ai", "bool"),
        ("currency", "string"),
    ],
    "s3_revenue/invoices.parquet": [
        ("invoice_id", "string"), ("tenant_id", "string"), ("billing_period_start", "date32[day]"),
        ("billing_period_end", "date32[day]"), ("line_type", "string"), ("amount_usd", MONEY), ("currency", "string"),
    ],
    "s5_price_catalog/price_catalog.parquet": [
        ("model_id", "string"), ("provider", "string"), ("tier", "string"), ("input_usd_per_mtok", "double"),
        ("output_usd_per_mtok", "double"), ("cache_read_usd_per_mtok", "double"), ("batch_discount_pct", "double"),
        ("baa_covered", "bool"), ("eu_region", "bool"), ("effective_from", "date32[day]"), ("effective_to", "date32[day]"),
    ],
    "labels/patterns.parquet": [
        ("pattern_id", "string"), ("pattern_type", "string"), ("feature_id", "string"), ("tenant_scope", "string"),
        ("model_scope", "string"), ("start_date", "date32[day]"), ("end_date", "date32[day]"),
        ("affected_metric", "string"), ("magnitude", "double"), ("expected_impact_usd_per_day", MONEY),
        ("detectable_by", "string"),
    ],
}


def schema_fingerprint(fields: list[tuple[str, str]]) -> str:
    """Stable hash of (name, type) pairs, recorded in the ingestion manifest."""
    return hashlib.sha256(";".join(f"{n}:{t}" for n, t in fields).encode()).hexdigest()[:16]
