---
doc_id: policy-compliance
title: BoonCore Compliance-Constraint Policy v1
source_type: policy
tenant_id: all
effective_date: 2024-07-01
synthetic: true
---

# BoonCore Compliance-Constraint Policy v1

> Synthetic document for the Margin Compass portfolio project. BoonCore Inc. is fictional. Nothing
> here is legal or medical advice. Thresholds marked *(assumption)* are simulator parameters.

## 1. Purpose and scope
<!-- clause: scope -->

BoonCore serves manufacturers and operators of medical imaging equipment. This policy lists the
constraints that any cost lever, routing change, or pricing proposal must respect.

## 2. Safety screening floor
<!-- clause: safety_screening -->

Every ticket is screened for a possible device complaint or patient-harm event, and positives are
routed to the tenant's safety team within 24 hours *(assumption)*. Safety screening is a fixed
compliance cost. No lever may remove it, batch it, or move it to a cheaper model if detection recall
falls below 99%. A proposal that does so must be rejected.

## 3. BAA-covered providers
<!-- clause: approved_models -->

Requests that may carry health information may only use model providers covered by a HIPAA business
associate agreement and listed on the tenant's approved-model list. A cheaper model that is not on
the list is a blocked option, even if it meets quality.

## 4. Data residency
<!-- clause: data_residency -->

Some tenants require processing in the EU only. Routing, caching, and batch levers must keep each
request in the tenant's contracted region.

## 5. Patient data
<!-- clause: patient_data -->

Scan images and DICOM metadata never reach a model. Only device logs and error codes are sent, with
any patient-linked identifier redacted first.
