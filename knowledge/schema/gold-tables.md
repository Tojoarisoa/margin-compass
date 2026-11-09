---
doc_id: schema-gold-tables
title: Gold Table Schema Cards v1
source_type: schema
tenant_id: all
effective_date: 2025-04-01
synthetic: true
---

# Gold Table Schema Cards v1

> Synthetic document for the Margin Compass portfolio project. Tables are in the Parquet gold layer.

## 1. fct_unit_cost
<!-- clause: schema_unit_cost -->

Grain: day x feature x model. Columns: cost_date, feature_id, model_id, requests, input_tokens,
cached_input_tokens, output_tokens, llm_cost_usd, cost_per_request_usd, cost_per_1k_tokens_usd,
cache_hit_share. Unit costs are recomputed from sums, never averaged across rows. Cached input is part
of input tokens.

## 2. fct_cost_to_serve
<!-- clause: schema_cost_to_serve -->

Cost to serve per tenant and feature: LLM cost plus allocated shared infrastructure. Column
cost_to_serve_usd. Every row has a tenant_id. Shared infrastructure is allocated by named rules (rule_id).

## 3. fct_m2_tenant_margin
<!-- clause: schema_tenant_margin -->

AI margin per tenant: revenue minus cost to serve. Columns include tenant_id and margin_usd. Use it to
rank unprofitable tenants. Margin is negative when cost to serve exceeds AI revenue.

## 4. fct_margin_leaks
<!-- clause: schema_margin_leaks -->

Detected margin leaks: the feature, the tenant (set only for tenant-level surges), the start of the anomaly and its estimated dollar impact. Scored
against injected leak labels (EV-03).
