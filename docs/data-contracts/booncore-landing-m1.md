# Data contract: BoonCore landing files (M1)

- **Producer:** `simulator/` (`booncore-sim --profile m1`), version 0.1.0
- **Consumer:** M1-02 ingest (landing → bronze), then dbt models
- **Status:** M1 walking skeleton; extended in M2-01 (all features, ~400 tenants)
- **Classification:** **synthetic**; no personal data, no prompt or response content (AGENTS.md rules 10 and 16)

## Layout and guarantees

```text
<out>/
├── manifest.json                              # seed, window, row counts, SHA-256 per file
├── tenants/tenants.parquet
├── s1_llm_telemetry/telemetry_daily.parquet   # source S1
├── s3_revenue/subscriptions.parquet           # source S3
├── s3_revenue/invoices.parquet                # source S3
├── s5_price_catalog/price_catalog.parquet     # source S5
└── labels/patterns.parquet                    # ground truth; never used as a model feature
```

- Every Parquet file has key-value metadata `synthetic=true`, `generator`, `generator_version`, `profile`, `seed`.
- **Deterministic:** the same profile and seed produce byte-identical files and manifest. Nothing time-dependent is written.
- Money is `decimal(14,2)` in USD, rounded half-up to the cent.
- Dates are `date32`. `billing_period_end` is exclusive.

## Tables

### `tenants` (grain: tenant)

| Column | Type | Notes |
| --- | --- | --- |
| `tenant_id` | string | `bc-t0001`…; primary key |
| `segment` | string | `imaging`, `in_vitro_diagnostics`, `patient_monitoring`, `surgical`, `other_devices` |
| `plan` | string | `starter`, `growth`, `enterprise` |
| `arr_usd` | decimal(14,2) | Annual contract value |
| `ai_addon_arr_usd` | decimal(14,2) | 35% of `arr_usd` |
| `discount_pct` | decimal(5,2) | Negotiated discount, 0–0.25 |
| `unlimited_ai` | bool | Legacy "unlimited AI" clause |
| `contract_start`, `renewal_date` | date32 | Annual term |

### `s1_llm_telemetry/telemetry_daily` (grain: day × tenant × feature × model)

Column names are the OpenTelemetry GenAI attributes pinned in ADR-015, in snake_case.

| Column | Type | Notes |
| --- | --- | --- |
| `usage_date` | date32 | |
| `tenant_id` | string | FK → tenants |
| `feature_id` | string | M1: `F1` only |
| `gen_ai_provider_name` | string | Fictional: `provider_a` |
| `gen_ai_request_model` | string | M1: `a-small`, `a-mid`; FK → price catalog |
| `gen_ai_operation_name` | string | `chat` |
| `request_count` | int64 | > 0 (rows with no requests are omitted) |
| `gen_ai_usage_input_tokens` | int64 | **Includes** cached tokens (ADR-015); price cached tokens once |
| `gen_ai_usage_output_tokens` | int64 | |
| `gen_ai_usage_cache_read_input_tokens` | int64 | ≤ input tokens |
| `retry_count` | int64 | ≤ `request_count` |

Unique key: (`usage_date`, `tenant_id`, `feature_id`, `gen_ai_request_model`).

### `s3_revenue/subscriptions` (grain: tenant)

Same contract terms as `tenants` (`plan`, `contract_start`, `renewal_date`, `arr_usd`, `ai_addon_arr_usd`, `discount_pct`, `unlimited_ai`) plus `currency` = `USD`.

### `s3_revenue/invoices` (grain: invoice line)

| Column | Type | Notes |
| --- | --- | --- |
| `invoice_id` | string | `inv-YYYYMM-<tenant_id>` |
| `tenant_id` | string | FK → tenants |
| `billing_period_start`, `billing_period_end` | date32 | Calendar month; end exclusive |
| `line_type` | string | `subscription` or `ai_addon` |
| `amount_usd` | decimal(14,2) | `annual / 12 × (1 − discount)`, half-up to the cent |
| `currency` | string | `USD` |

Billed monthly in advance; M1 covers August, September, and October 2025 in full, even though telemetry ends on 2025-10-29.

### `s5_price_catalog/price_catalog` (grain: model × effective date)

`model_id`, `provider`, `tier`, `input_usd_per_mtok`, `output_usd_per_mtok`, `cache_read_usd_per_mtok` (10% of input for provider A), `batch_discount_pct`, `baa_covered`, `eu_region`, `effective_from`, `effective_to` (null = current). Prices are **synthetic** (spec §4).

### `labels/patterns` (grain: injected pattern)

`pattern_id`, `pattern_type`, `feature_id`, `tenant_scope`, `model_scope`, `start_date`, `end_date` (null = ongoing), `affected_metric`, `magnitude`, `expected_impact_usd_per_day` (computed against a no-pattern counterfactual from the same random draws), `detectable_by`. M1 contains PT-01 only: +40% F1 input tokens per request from 2025-09-15.

## Known limitations (M1)

- **AI gross margin is unrealistically high (~98%) because only F1 exists.** Calibration to the plan's ~50% starting point happens in M2-01, when F0 and F2–F4 are added (spec §3). Label M1 margin views "F1 only".
- No outcomes (S4), contracts beyond the core terms, shared-infrastructure costs (S2), or corpus (S6) yet.
