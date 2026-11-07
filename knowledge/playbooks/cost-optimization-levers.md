---
doc_id: playbook-cost-levers
title: AI Cost-Optimization Playbook v1
source_type: playbook
tenant_id: all
effective_date: 2025-04-01
synthetic: true
---

# AI Cost-Optimization Playbook v1

> Synthetic document for the Margin Compass portfolio project. BoonCore Inc. is fictional.
> Savings ranges are labeled assumptions, not measurements.

## 1. Model routing
<!-- clause: lever_routing -->

Route easy, high-volume requests (short Reply Copilot drafts, knowledge search rewrites) to a cheaper
model and keep the stronger model for hard cases. Replay the routing change on historical traffic before
proposing it. Expected saving: 20-40% of the routed feature's LLM cost *(assumption)*. Guardrail: the
resolution score must stay within 1 point of baseline.

## 2. Prompt caching
<!-- clause: lever_caching -->

Move static instructions and device manuals to the front of the prompt so they are cached. Watch the
cache hit share in `fct_unit_cost`. Expected saving: 10-30% on input cost for features with long fixed
prefixes *(assumption)*. No quality risk if the prompt content is unchanged.

## 3. Context trimming and batching
<!-- clause: lever_context -->

Send fewer retrieved passages (top 3 instead of top 8) and batch non-urgent summaries (F4) overnight.
Expected saving: 5-15% *(assumption)*. Guardrail: retrieval recall and answer quality must not drop.

## 4. Levers that are never allowed
<!-- clause: lever_forbidden -->

Safety screening (F0) cannot be removed, batched, or moved to a cheaper model if safety-event recall
drops below 99%. A lever that fails the quality or recall guardrail is rejected, whatever it saves.

## 5. Renewal playbook for unprofitable tenants
<!-- clause: playbook_renewal -->

For a tenant with negative AI margin at renewal: (1) show the tenant's margin and usage; (2) replace an
"unlimited AI" clause with a capped allowance plus overage pricing; (3) offer a discount only within the
approver's authority in the discount-authority matrix; (4) check the churn-risk score before choosing
how firm to be; (5) record the decision and rationale for approval.
