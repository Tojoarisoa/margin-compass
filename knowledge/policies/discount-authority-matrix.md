---
doc_id: policy-discount-authority
title: BoonCore Discount Authority Matrix v1
source_type: policy
tenant_id: all
effective_date: 2024-07-01
synthetic: true
---

# BoonCore Discount Authority Matrix v1

> Synthetic document for the Margin Compass portfolio project. BoonCore Inc. is fictional.
> All thresholds are *(assumption)* values for the simulation.

## 1. Purpose and scope
<!-- clause: scope -->

This matrix says which role may approve which discount or contract change on the AI add-on. A
proposal outside the approver's authority must go to the next role. Agents only draft proposals; a
person with authority approves them.

## 2. Discount approval limits
<!-- clause: discount_authority -->

Discount is measured against list price of the AI add-on for the renewal term.

| Role | May approve a discount of up to *(assumption)* |
| --- | --- |
| Account manager | 5% |
| RevOps or customer-success lead | 15% |
| Head of revenue | 25% |
| Finance and CEO jointly | above 25% |

## 3. Contract changes
<!-- clause: contract_change_authority -->

| Change | Approver *(assumption)* |
| --- | --- |
| Replace an "unlimited AI" clause with a fair-use cap at renewal | RevOps or customer-success lead |
| Raise or lower an included-ticket allowance by up to 20% | RevOps or customer-success lead |
| Change an approved-model list or data-residency term | Head of revenue, with the compliance owner |
| Weaken a response-time SLA | Head of revenue and finance |

## 4. Limits that no role can waive
<!-- clause: non_waivable -->

No discount or contract change may remove safety screening, lower its recall floor, or move
processing outside a tenant's approved-model list or data residency. Those limits come from the
compliance-constraint policy.
