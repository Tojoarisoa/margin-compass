# Data contract: gold marts (M2)

- **Producer:** `pipelines/transform/models/m2/` (dbt-duckdb). Enabled only when var `m2_landing_path` is set, so the M1 build is unchanged. Synthetic data only (PLAN.md rule 10).
- **Owner:** data platform (the project owner). **SLA:** ready by 07:00 UTC once the nightly run exists. **PII:** none; all data is synthetic.
- **Gates (var `m2_gates`):** four preservation tests in `pipelines/transform/tests/m2_*.sql`, severity `error`: infra cost (allocated + unallocated = FOCUS billed), LLM cost (marts = priced telemetry), revenue per invoice line, revenue per tenant and period. `pipelines/tests/test_m2_silver.py` runs them green, then breaks each on purpose.
- **Metrics:** every ratio below is defined once in `metrics/metrics.yml` (`mc_pipelines.metrics`) and is a ratio of sums. Roll up by summing the count columns, never by averaging a ratio column.
- **Currency units:** revenue `DECIMAL(18,2)`; LLM cost `DECIMAL(18,6)`; allocated infrastructure `DECIMAL(18,4)`; counts integers.

## Marts

| Mart | Grain | Consumers |
| --- | --- | --- |
| `fct_infra_cost_allocated` | day × tenant × feature × rule | `fct_cost_to_serve`, attribution coverage (KPI-03), allocation audit |
| `fct_cost_to_serve` | day × tenant × feature | Cost-to-Serve Explorer, `fct_m2_tenant_margin`, AG-03 |
| `fct_unit_cost` | day × feature × model | unit-cost metric, leak detector (M3), AG-03 |
| `fct_quality` | day × tenant | safety-event recall, quality guardrail (KPI-08), `agg_m2_cost_per_outcome` |
| `fct_m2_tenant_margin` | day × tenant | PG-1 (M2-04), margin KPIs (KPI-01), AG-03, AG-05 |
| `agg_m2_cost_per_outcome` | day × tenant | cost per outcome (KPI-05), PG-1 (M2-04) |
| `dim_tenant` | tenant × plan version (SCD2) | all tenant joins |
| `dim_feature` | feature | feature joins |
| `dim_model_price` | model × effective-dated price | price audit, pricing and lever simulators |

## Columns and rules

### `fct_infra_cost_allocated`
`cost_date`, `tenant_id`, `feature_id`, `rule_id`, `service_name`, `allocated_cost_usd`.
- Unique on the grain. `allocated_cost_usd` ≥ 0.
- Allocated + `UNALLOCATED` rows equal the landed FOCUS billed cost exactly, in 0.0001 USD units (gate).
- `rule_id = 'UNALLOCATED'` rows have NULL `tenant_id` and `feature_id`; they are shown, never hidden.

### `fct_cost_to_serve`
`cost_date`, `tenant_id`, `feature_id`, `requests`, `llm_cost_usd`, `agent_compute_usd`, vector, network/observability and third-party components, `infra_cost_usd`, `cost_to_serve_usd`.
- Unique on the grain. `cost_to_serve_usd = llm_cost_usd + infra_cost_usd`.
- LLM total equals the priced telemetry (gate); infra total equals the allocated, non-`UNALLOCATED` rows.
- Unallocated infrastructure is not here.

### `fct_unit_cost`
`cost_date`, `feature_id`, `model_id`, token and request sums, `llm_cost_usd`, `cost_per_request_usd`, `cost_per_1k_tokens_usd`, `cache_hit_share`.
- Unique on the grain. Ratio columns are NULL when the denominator is 0. Cached input is part of input (ADR-015).

### `fct_quality`
`outcome_date`, `tenant_id`, outcome sums (`tickets`, `f2_tickets`, `resolved_remotely`, `field_visits_booked`, `escalated`, safety counts), `safety_event_recall`, `remote_resolution_rate`, `csat_avg`, `eval_score_avg`.
- Unique on the grain. `safety_event_recall` is NULL on days with no labeled event; roll up from `safety_events_flagged` / `safety_events_labeled`.

### `fct_m2_tenant_margin`
`margin_date`, `tenant_id`, `revenue_usd`, `discount_usd`, `llm_cost_usd`, `infra_cost_usd`, `cost_to_serve_usd`, `margin_usd`, `margin_pct`.
- Unique on the grain. `margin_usd = revenue_usd - cost_to_serve_usd`. `margin_pct` is NULL on days without revenue.
- Revenue per invoice line and per tenant and period equals the invoices (gates). Overage revenue is not simulated (0).

### `agg_m2_cost_per_outcome`
`metric_date`, `tenant_id`, `cost_to_serve_usd`, `resolved_remotely`.
- Unique on the grain; full outer join of the margin and quality marts, so totals equal both sources (test).
- Cost is the tenant's whole fully loaded cost (all features); the outcome is a ticket resolved remotely (PLAN.md §3).

### Dimensions
- `dim_tenant`: exactly one current row per tenant (`valid_to` NULL); versions contiguous (`valid_from` inclusive, `valid_to` exclusive).
- `dim_feature`, `dim_model_price`: `effective_to` exclusive; open-ended = 9999-12-31.

## Change control
Changing a column, type, grain, or metric definition changes this contract: update this file, the registry and the parity tests in the same PR, and ask the owner (AGENTS.md §7; auto-decided under §8.2 only inside the plan).
