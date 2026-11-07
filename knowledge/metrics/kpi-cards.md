---
doc_id: metric-kpi-cards
title: Metric Cards v1
source_type: metric
tenant_id: all
effective_date: 2025-04-01
synthetic: true
---

# Metric Cards v1

> Synthetic document for the Margin Compass portfolio project.

## 1. AI gross margin (KPI-01)
<!-- clause: metric_gross_margin -->

AI gross margin % = (AI-feature revenue - AI cost to serve) / AI-feature revenue, blended and per
feature. Source: fct_m2_tenant_margin. Target: at least 8 points above baseline by the end of the
simulation.

## 2. Attribution coverage (KPI-03)
<!-- clause: metric_attribution -->

Share of LLM spend attributed to a tenant and feature, and share of shared infrastructure allocated.
Targets: at least 98% for LLM spend and 95% for infrastructure.

## 3. Cost per outcome (KPI-05)
<!-- clause: metric_cost_per_outcome -->

AI cost to serve divided by tickets resolved remotely (F2), and per assisted reply (F1). Source:
agg_m2_cost_per_outcome. Target: down 20% within the quality guardrail.

## 4. Safety-event recall (KPI-08b)
<!-- clause: metric_safety_recall -->

Share of labeled device-complaint or patient-harm tickets that safety screening flags. A hard floor of
99%: any recommendation that drops it below 99% is rejected regardless of savings.
