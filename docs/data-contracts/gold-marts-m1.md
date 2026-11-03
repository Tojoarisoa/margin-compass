# Data contract: gold marts (M1)

- **Producer:** `pipelines/transform` (dbt-duckdb), run by `mc-pipeline` (local) and `mc-dev-data-pipeline` (AWS dev)
- **Enforcement:** dbt `contract: enforced` on every mart: the build fails if a column's name or type drifts from `pipelines/transform/models/gold/schema.yml`
- **Gate:** EV-01, no error-severity failures (PLAN.md §13). Results: `gold/_quality/scorecard.json`; lineage: `gold/_quality/lineage.json`
- **Owner:** data platform (the project owner). **SLA:** ready by 07:00 UTC once the nightly run exists (M1-08). **PII:** none; all data is synthetic.
- **Schema decisions (owner, 2026-11-04):** revenue `DECIMAL(18,2)`, LLM cost `DECIMAL(18,6)`, counts `BIGINT`, ratios `DOUBLE`; `agg_exec_kpis.unallocated_llm_cost_usd` added.

## Marts

| Mart | Grain | Consumers |
| --- | --- | --- |
| `fct_llm_usage_daily` | day × tenant × feature × model | Cost-to-Serve Explorer, leak detector (M3), AG-03 |
| `fct_revenue_daily` | day × tenant × revenue component | margin marts, pricing simulator (M3), AG-05 |
| `fct_tenant_margin` | day × tenant × feature | PG-1 Executive overview (M1-07), AG-03, KPI-01/04 |
| `agg_exec_kpis` | day | PG-1 (M1-07), dashboard KPI tiles |

### `fct_llm_usage_daily`

| Column | Type | Rule |
| --- | --- | --- |
| `usage_date` | date | not null |
| `tenant_id` | varchar | not null and a known tenant: **warn** per row (unattributable rows become unallocated) |
| `feature_id` | varchar | not null and a known feature (`F1` in M1): **warn** per row |
| `provider`, `model_id` | varchar | `model_id` not null |
| `request_count`, `input_tokens`, `uncached_input_tokens`, `cached_input_tokens`, `output_tokens`, `retry_count` | bigint | no negatives; cached ≤ input |
| `price_effective_from` | date | not null: every row priced by an effective catalog entry |
| `llm_cost_usd` | decimal(18,6) | not null, ≥ 0 |

Unique: (`usage_date`, `tenant_id`, `feature_id`, `model_id`).

### `fct_revenue_daily`

`revenue_date` date · `tenant_id` varchar (known tenant) · `revenue_component` varchar (`subscription`, `ai_addon`) · `amount_usd` decimal(18,2) · `currency` varchar (`USD`) · `plan` varchar · `discount_pct` decimal(5,2). Unique: (`revenue_date`, `tenant_id`, `revenue_component`).

### `fct_tenant_margin`

`margin_date` date · `tenant_id` varchar · `feature_id` varchar · `ai_revenue_usd` decimal(18,2) · `llm_cost_usd`, `cost_to_serve_usd`, `gross_margin_usd` decimal(18,6) · `gross_margin_pct` double (null when revenue is 0) · `request_count` bigint · `feature_scope` varchar (`F1 only (M1)`). Exactly one row per day × known tenant × feature over the simulated window.

### `agg_exec_kpis`

`kpi_date` date (unique) · `total_revenue_usd`, `ai_revenue_usd` decimal(18,2) · `ai_cost_to_serve_usd`, `llm_spend_usd`, `unallocated_llm_cost_usd` decimal(18,6) · `kpi01_ai_gross_margin_pct`, `kpi03_llm_attribution_coverage_pct` double · `kpi04_unprofitable_tenants` bigint · `kpi04_unprofitable_arr_usd` decimal(18,2) · `feature_scope`, `run_id` varchar.

## Quality gates

| Gate | Severity | Test |
| --- | --- | --- |
| Revenue preservation per invoice line (silver) | error | `preservation_revenue_per_invoice_line` |
| Revenue preservation per tenant × component × period (gold) | error | `preservation_revenue_per_tenant_period` |
| Cost preservation: allocated + unallocated = total billed, to the cent | error | `preservation_cost_allocated_plus_unallocated` |
| Dashboard unallocated = unallocated rows | error | `preservation_kpi_unallocated_matches_rows` |
| No negative tokens; cached ≤ input | error | `business_rule_no_negative_tokens` |
| Every price lookup resolves | error | `not_null(price_effective_from)` |
| Every tenant has an active plan | error | `business_rule_every_tenant_has_active_plan` |
| Every request maps to a tenant and a feature | **warn per row**; **error if coverage < 98%** (KPI-03) | relationships / not_null / accepted_values; `business_rule_attribution_coverage_meets_kpi03` |
| Grain uniqueness and window coverage | error | `contract_unique_*`, `contract_margin_grain_covers_window` |
| Every day has usage (volume) | warn | `statistical_every_day_has_usage` |

**Error** stops the run, moves that ingest date's bronze partitions to `quarantine/` (with a `_reason_…json`), and, in AWS, uploads only the quarantine and scorecard. **Warn** lets the run finish and is listed in the scorecard for the dashboard to annotate.

"Unallocated" is computed independently of the margin fact (usage rows not matching a known tenant, a known feature, or the window), so the cost gate isn't true by construction. Each gate has a test that breaks the data on purpose and checks the gate fires (`pipelines/tests/test_quality_gates.py`).
