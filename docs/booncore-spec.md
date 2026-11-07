# BoonCore Specification (M0-08)

- **Status:** Approved by the owner on 2026-11-02 (all four items in §12 approved as recommended)
- **Date:** 2026-11-02
- **Governs:** `simulator/` (PLAN.md §16), sources S1–S6 (PLAN.md §6.2 Stage 1)
- **Decisions it implements:** ADR-017 (vertical and regulatory constraints), PLAN.md §2.2, KPI-08(b)

> **Everything in this document is synthetic.** BoonCore Inc., its tenants, contracts, prices, and events are fictional. Numbers here are simulator parameters, not facts. Nothing here is medical advice or describes a validated medical system. Parameters marked *(assumption)* are unverified and must be labeled as such wherever they surface.

## 1. Company

| Attribute | Value |
| --- | --- |
| Business | B2B AI technical-support platform for medical device and diagnostics companies; medical imaging is the flagship segment |
| ARR at simulation end | $24.0M |
| Tenants | 400 |
| Fiscal year | Starts April 1; named by its start year (FY2025 = 2025-04-01 → 2026-03-31). Owner decision 2026-11-06 |
| Simulation window | 2025-04-01 → 2026-10-31 (19 months, 579 days): FY2025 in full plus FY2026 through the last full month before the project started; backfilled in monthly chunks |
| Determinism | Every run takes a seed; same seed + same config ⇒ byte-identical output |
| Labeling | Every generated file carries `synthetic = true` in its metadata |

## 2. Tenants

### 2.1 Plans

| Plan | Tenants | Avg ARR per tenant | Plan ARR | Tickets / tenant / weekday | Telemetry grain |
| --- | --- | --- | --- | --- | --- |
| Starter | 200 | $15,000 | $3.0M | 5 | Daily |
| Growth | 150 | $60,000 | $9.0M | 25 | Daily |
| Enterprise | 50 | $240,000 | $12.0M | 150 | Hourly |
| **Total** | **400** | | **$24.0M** | **12,250 / weekday** | |

Each tenant's ARR is drawn from a log-normal around its plan average, then rescaled so the totals match.

**Revenue components:** seat subscription + flat **AI add-on**. The AI add-on is **35% of ARR** (≈ $8.4M/yr) and is the "AI-feature revenue" in KPI-01. Overage and per-resolution components appear only after an approved ACT-2.

### 2.2 Segments

| Segment | Tenants | Plan skew | Ticket complexity | Safety-event base rate *(assumption)* | Price sensitivity |
| --- | --- | --- | --- | --- | --- |
| **Medical imaging** (CT, MRI, ultrasound, X-ray, PACS) — flagship | 60 | Mostly Enterprise | Highest: long logs, integrations | 1.0% | Low |
| In-vitro diagnostics and lab analyzers | 100 | Growth / Enterprise | High | 0.8% | Medium |
| Patient monitoring and respiratory | 80 | Growth | Medium | 1.5% | Medium |
| Surgical and interventional | 60 | Growth / Starter | Medium | 1.2% | Medium |
| Other devices (infusion, home care, dental) | 100 | Starter | Low | 0.5% | High |

Imaging tenants are 15% of tenants but should carry ≈ 40% of ARR and the largest share of F2 cost.

## 3. AI features

Tokens are per request, drawn from a log-normal with the given median *(assumption; calibrated in M2 so baseline AI gross margin ≈ 50%, PLAN.md §4.1)*.

| ID | Feature | Requests per ticket | Median input / output tokens | Default tier | Notes |
| --- | --- | --- | --- | --- | --- |
| **F0** | **Safety Screening** | 1 | 1,500 / 50 | Mid | Mandatory on every ticket; fixed compliance cost; KPI-08(b) |
| F1 | Reply Copilot | 3 | 2,000 / 300 | Mid | High volume, short prompts; cacheable system prompt |
| F2 | Device Troubleshooting Agent | 40% of tickets × 6 steps | 12,000 / 600 per step (imaging ×1.8) | Frontier | Long log-heavy prompts; retries; outcome = remote resolution |
| F3 | Service Knowledge Search | 2 | 300 / 0 (embedding) + retrieval | Embedding model | Vector storage is a shared-infra cost line |
| F4 | Case & Complaint Summaries | 1 per closed ticket | 6,000 / 400 | Frontier (over-served) | Batch-eligible unless the case is Sev-1 |

At baseline ≈ 115,000 LLM requests per weekday. To land near 50% AI gross margin, blended AI cost must average ≈ $11,500/day, i.e. ≈ $0.10 per request (planning estimate).

**Outcomes per ticket (S4):** `resolved_remotely`, `field_visit_booked`, `escalated`, `csat` (1–5), `severity` (Sev-1/2/3), `safety_event_label` (ground truth), `safety_flag` (F0 output), `eval_score` (offline evaluation).
Baseline remote-resolution share for F2 tickets: drawn per tenant from **30%–50%** *(assumption, ADR-017)*.

## 4. Models and price catalog v1

Providers are fictional. Prices are **synthetic and illustrative**; they will be recalibrated to real price ratios after VER-05 / ADR-003, but stay labeled synthetic.

| Model | Provider | Tier | Input $/M | Output $/M | Cached input | Batch | BAA | EU region |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `a-small` | Provider A | Small | 0.25 | 1.25 | 10% of input | −50% | Yes | Yes |
| `a-mid` | Provider A | Mid | 3.00 | 15.00 | 10% of input | −50% | Yes | Yes |
| `a-frontier` | Provider A | Frontier | 15.00 | 75.00 | 10% of input | −50% | Yes | Yes |
| `b-mid` | Provider B | Mid | 2.00 | 10.00 | 25% of input | −50% | Yes | No |
| `c-small` | Provider C | Small | 0.10 | 0.40 | none | none | **No** | No |
| `emb-1` | Provider A | Embedding | 0.02 | — | — | — | Yes | Yes |

Catalog entries are effective-dated. Scheduled changes in the window: a **`b-mid` price cut of 40% on 2026-03-01** (feeds the "unused cheaper option" pattern).

**Quality by tier** (mean `eval_score` relative to frontier = 1.00; F0 recall on labeled safety events) *(assumption)*:

| Tier | F1 / F4 quality | F2 remote-resolution multiplier | F0 safety recall |
| --- | --- | --- | --- |
| Frontier | 1.00 | 1.00 | 99.6% |
| Mid | 0.99 | 0.90 | 99.3% |
| Small | 0.96 | 0.70 | 97.5% (**below the 99% floor**) |

## 5. Contracts

Every tenant has one active contract (SCD2 history in `dim_tenant`).

| Clause | Distribution | Effect |
| --- | --- | --- |
| Term | Annual; renewal dates spread uniformly across the year | Renewal calendar (PG-7) |
| Negotiated discount | 0–25%, higher for Enterprise | Revenue |
| **"Unlimited AI"** legacy clause | 15% of tenants, skewed to older Growth/Enterprise | Source of power tenants |
| **Approved-model list** | 30% of tenants: BAA-covered providers only (excludes Provider C); 5%: Provider A only | Blocks some ACT-1 routing levers |
| **Data residency** | 20% of tenants: EU-only (Provider A only, EU region) | Blocks some ACT-1 routing levers |
| **Response-time SLA** | Sev-1: 15 min; Sev-2: 2 h; Sev-3: 1 business day | Batching F4 is allowed only for Sev-2/3 cases |
| Severity mix | Sev-1 5%, Sev-2 25%, Sev-3 70% (imaging: Sev-1 10%) | Drives SLA constraints |

**Discount-authority matrix:**

| Approver | Max discount at renewal |
| --- | --- |
| CS lead | 10% |
| VP Sales | 20% |
| CFO | > 20% |

## 6. Regulatory constraints in the simulator (ADR-017)

1. **F0 runs on every ticket** and routes positives to the tenant's safety team within **24 hours** (well inside the shortest reporting windows recorded in ADR-017).
2. **KPI-08(b):** a lever that drops F0 safety recall below **99%** is rejected. The simulator must make this observable: moving F0 to the small tier must breach the floor.
3. No model ever receives images or DICOM data. Device logs pass through a simulated redaction step that removes patient-linked identifiers (patient IDs, accession numbers, implant serials); scanner serials may remain.
4. Routing may only use models allowed by the tenant's approved-model list and residency terms.
5. Margin Compass receives only metadata, token counts, costs, and outcomes; no ticket text exists in any generated file.

## 7. Seasonality and growth

| Effect | Parameter *(assumption)* |
| --- | --- |
| Weekly | Weekend volume = 20% of weekday (Sev-1 unaffected) |
| Daily (Enterprise hourly grain) | Business-hours peak, overnight floor 15% |
| Respiratory season | Nov–Feb: +25% ticket volume for patient monitoring/respiratory and in-vitro diagnostics |
| Hospital fiscal year-end | Configurable per tenant (default Jun 30): +15% in the final 3 weeks |
| Growth | +2% tenants per month net; onboarding waves in Jan and Sep |

## 8. Injected pattern catalog (labeled ground truth)

Each injected pattern writes a row to `labels/patterns` with: `pattern_id`, `type`, `tenant_ids`, `feature`, `model`, `start_date`, `end_date`, `affected_metric`, `magnitude`, `expected_impact_usd_per_day` (computed by the simulator, never estimated), and `detectable_by` (leak detector, forecaster, churn model, agent).

| ID | Pattern | Where / when | Magnitude | Primary detector |
| --- | --- | --- | --- | --- |
| PT-01 | Prompt regression | F1, all tenants, from 2025-09-15 | +40% input tokens per request | Leak detector |
| PT-02 | Agent retry loop | F2, one imaging tenant, 9 days after a remote-monitoring connector outage (2026-01-20) | Retries ×4 | Leak detector |
| PT-03 | Silent model upgrade | F4 moved mid → frontier on 2025-11-03 | No quality gain | Leak detector + Cost–Quality Lab |
| PT-04 | Cache-hit collapse | F1 system-prompt change 2026-04-07 | Cache-hit rate 70% → 15% | Leak detector |
| PT-05 | Re-index storm | F3 after a simulated recall notice, 2026-02-10 | 30× embedding volume for 3 days | Leak detector |
| PT-06 | Fleet update surge | F2, one imaging tenant, 2026-06-02 | 6× near-identical tickets for 5 days | Leak detector; caching opportunity |
| PT-07 | Integration flood | F2, three imaging tenants, 2026-08-18 | Log tokens ×3 for 7 days | Leak detector |
| PT-08 | Blocked cheaper option | Tenants with approved-model or EU constraints | `c-small` / `b-mid` would pass quality but are forbidden | AG-07 constraint check |
| PT-09 | Safety-screening downgrade | A seeded ACT-1 proposal: F0 → small tier | Recall 97.5% < 99% | Verifier (EV-13) must reject |
| PT-10 | Power tenants | 12 "unlimited AI" tenants, 3× median usage | Negative AI margin | Cost-to-Serve Explorer, AG-07 |
| PT-11 | Unused cheaper option | `b-mid` price cut not adopted from 2026-03-01 | Savings available on F1 | AI Efficiency Engineer |
| PT-12 | Shared-infra waste | Idle staging GPU, 2025-12-01 → 2026-02-28; oversized vector tier throughout | Fixed $/day | Allocation + leak detector |
| PT-13 | Seasonality and growth | §7 | — | Forecaster (not a leak; must not alert) |
| PT-14 | Churn behavior | Function in §9 | — | Churn model |

PT-01 is the only pattern in M1 (M1-01).

## 9. Churn and closed-loop behavior

**Churn at renewal** (logistic; coefficients are *assumptions*, labeled in output):
`p_churn = σ(β0 + β1·price_change_% + β2·(csat − 3) + β3·tenure_years + β4·segment_sensitivity + β5·unresolved_sev1_rate)`
Downgrade (plan or seats) is a separate outcome with the same inputs.
The churn coefficients are scaled to the spread of the simulated inputs (tenant mean CSAT varies by only about 0.05, unresolved Sev-1 rate by about 0.016), so the true probabilities separate churners with AUC about 0.83 and mean churn is about 8% (changed 2026-11-07 under AGENTS.md §8.2; earlier values gave AUC 0.58, which no model could lift to the EV-11 bar of 0.75). Every churn and downgrade event is labeled with its true probability, for calibration tests.

**Closed loop** (PLAN.md §8.4): approved actions change future days.

| Action | Effect | Randomized and labeled |
| --- | --- | --- |
| ACT-1 engineering | Model mix, tokens, cache rate, quality per §4 | Adoption lag 3–14 days; realization 60–100%; quality noise ±1 pt |
| ACT-2 pricing | New price components from the effective date | Churn and downgrade per the model above |
| ACT-3 account | That tenant's terms at renewal | Acceptance probability falls with price increase |

A counterfactual run (same seed, no action) is always produced, for KPI-02.

## 10. Data volume check (PLAN.md §7.5)

| Item | Estimate | Budget | OK |
| --- | --- | --- | --- |
| Aggregated telemetry: Enterprise hourly + others daily | **2.71M rows** over 19 months (measured, seed 42, 2026-11-06; was 2.59M over 18 months) | 1.5–3M | Yes |
| Same, but hourly for all tenants | ≈ 13.9M rows (estimate scaled to 579 days) | 1.5–3M | **No** (reason for the split grain) |
| 1% raw request sample | **0.44M rows** (measured) | — | Yes |
| Tickets / outcomes, one row per ticket | ≈ 5.5M rows (414 weekdays × 12,250 + 165 weekend days × 2,450) | < 1M | **No** (rejected; see §12 item 3) |
| Outcomes, approved storage (§12 item 3a) | **0.68M rows** (measured: 0.18M tenant-day + 0.51M ticket rows) | < 1M | Yes |

## 11. M1 subset (M1-01)

20 tenants (10 imaging, 10 other; mixed plans), F1 only, tiers `a-small` and `a-mid`, 90 days (2025-08-01 → 2025-10-29), PT-01 only, daily grain, same seed rules and labels.

## 12. Owner decisions (approved 2026-11-02, as recommended)

1. **F0 Safety Screening as its own feature.** Recommended: it makes the compliance cost visible in `fct_cost_to_serve` and gives KPI-08(b) a clean home in `fct_quality`. It adds a fifth feature (F0–F4) to `dim_feature`; no mart schema changes.
2. **Split telemetry grain** (Enterprise hourly, others daily) to stay inside §7.5.
3. **Outcome volume exceeds the < 1M row budget.** Options: (a) store outcomes aggregated to tenant × day (severity and feature counts as columns, ≈ 0.22M rows), plus per-ticket rows for a 10% sample (≈ 0.52M) and for every labeled safety event (≈ 0.05M): ≈ 0.79M rows in total (recommended; a tenant × feature × day × severity grain alone would be ≈ 3.3M); (b) raise the outcome budget in §7.5.
4. **All parameters marked *(assumption)*** are accepted as simulator inputs, to be labeled in the dashboard and case study.
