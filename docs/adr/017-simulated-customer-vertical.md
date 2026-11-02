# ADR-017: Simulated customer vertical (BoonCore: medtech technical support, imaging flagship)

- **Status:** Accepted (2026-11-02, by the owner)
- **Date:** 2026-11-02
- **Related:** PLAN.md §2.2, §4.2 (KPI-08), §7 (`fct_quality`), §13 (EV-13), §19.3 (VER-15), Change Log v0.4

## Context

Margin Compass needs a simulated AI-SaaS customer whose data gives the models and agents labeled ground truth. The original plan used a generic customer-support platform. The owner wanted a vertical where Margin Compass shows the highest return: tenants that are very profitable and tickets that are very high value, so pricing and engineering levers act on a large margin pool.

Options compared during M0-04: generic customer support, AI coding tools, freight/trade compliance, telecom network operations, fintech support, B2B infrastructure/security support, pharma medical information, medical device support, and imaging-only support.

## Decision

BoonCore Inc. (fictional) is a B2B AI technical-support platform for **medical device and diagnostics companies**, with **medical imaging** vendors as the flagship segment. About $24M ARR and ~400 tenants are kept (a medtech-wide base makes 400 tenants plausible; imaging-only would not).

Regulation is modeled as **constraints on levers**, never as functionality Margin Compass implements:

1. Margin Compass ingests only cost, usage, and outcome metadata, never ticket content or patient data (AGENTS.md rule 16).
2. BoonCore's AI supports equipment and software only: no image interpretation, diagnosis, or clinical advice.
3. Mandatory safety screening on every ticket is a fixed compliance cost. KPI-08(b): safety-event recall ≥ 99%, hard floor, measured from `fct_quality.safety_events_labeled` / `safety_events_flagged`.
4. Scan images and DICOM metadata never reach a model; device logs are redacted of patient information first.
5. Routing is limited to providers covered by a BAA, per each tenant's approved-model list; some tenants require EU-only processing.
6. Every view states: synthetic data, not medical advice, not a validated medical system.

## Alternatives

| Option | Why not chosen |
| --- | --- |
| Generic customer support | Strong fit, but lower ticket value and less distinctive |
| AI coding tools | Deepest margin pain, but quality expectations limit cheaper-model levers |
| B2B infrastructure / security support | Very good fit; the owner preferred a healthcare vertical |
| Fintech support | Heavier regulatory framing for a similar ticket value |
| Pharma medical information | Promotion rules and adverse-event obligations add more framing than value |
| Imaging only | Too few real vendors for ~400 tenants; weaker churn-model training data |

## Consequences

- **Positive:** high-value outcome unit (remote resolution, field-engineer visit avoided); the strongest "savings only within quality and safety" demonstration (KPI-08, EV-13); contract-aware agents get real constraints (BAA, residency, response-time SLAs).
- **Negative:** a fixed compliance cost lowers recoverable margin slightly; more disclaimer and documentation work; the BoonCore specification (M0-08) needs a regulatory section.
- **Simulator parameters derived from this ADR** (labeled assumptions, not facts): see "What this changes" below.

## Cost impact

$0. Documentation and simulator-parameter decision only; no AWS resources added.

## Verified on 2026-11-02 (VER-15)

Status key: **Verified** = read on an official or primary source; **Secondary** = consistent secondary sources, primary not retrieved; **Unverified** = vendor marketing or no reliable source.

| Claim | Result | Status | Source |
| --- | --- | --- | --- |
| US device QMS rule now in force | QMSR effective 2026-02-02; incorporates ISO 13485:2016 by reference; finished-device makers must still keep complaint files | Verified | [FDA: QMSR](https://www.fda.gov/medical-devices/postmarket-requirements-devices/quality-management-system-regulation-qmsr) (content current as of 2026-02-02) |
| US adverse-event reporting deadlines | Manufacturers report deaths, serious injuries, and likely-harmful malfunctions within 30 calendar days of awareness; 5 work days when remedial action is needed or FDA requests it | Verified | [21 CFR 803.50](https://www.law.cornell.edu/cfr/text/21/803.50), [21 CFR 803.53](https://www.law.cornell.edu/cfr/text/21/803.53) (LII mirror of eCFR; eCFR blocked automated access) |
| EU serious-incident deadlines | 15 days default; 10 days for death or unanticipated serious deterioration; 2 days for a serious public-health threat | Secondary | [MDCG 2024-1](https://titck.gov.tr/storage/Archive/2024/contentFile/MDCG%202024-1-4_en_5e91017f-712f-40f7-87a9-542e6ff1be87.pdf), [IGJ (NL regulator)](https://english.igj.nl/medical-technology/market-supervision/vigilance-reporting-incidents-and-corrective-actions/report-incidents-and-field-safety-corrective-actions); EUR-Lex text of Reg. (EU) 2017/745 Art. 87 not retrieved |
| Model providers handling PHI need a BAA | A person that creates, receives, maintains, or transmits PHI on behalf of a covered entity (or a business associate, as subcontractor) is a business associate | Verified | [45 CFR 160.103](https://www.law.cornell.edu/cfr/text/45/160.103) |
| Cloud providers have no "conduit" exemption; holding no key doesn't exempt them | As stated | Secondary | HHS cloud guidance (hhs.gov returned 403); [Hunton summary](https://huntonak.com/privacy-and-information-security-law/hhs-releases-guidance-hipaa-cloud-computing) |
| De-identified data is outside HIPAA | Yes, via expert determination or safe harbor. **Safe-harbor identifiers include device identifiers/serial numbers and full-face or comparable images** | Verified | [45 CFR 164.514](https://www.law.cornell.edu/cfr/text/45/164.514) |
| DICOM de-identification is not guaranteed by header profiles | Annex E profiles don't guarantee removal of all identifying information; identifying text can be burned into pixel data | Verified | [DICOM PS3.15 2026d, Annex E](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/chapter_E.html) |
| Software that analyzes medical images is regulated device software | Under FDA's CDS guidance, software that processes or analyzes a medical image fails non-device Criterion 1 | Secondary | [Duane Morris](https://www.duanemorris.com/alerts/fda_issues_final_guidance_clinical_decision_support_software_1022.html), [Goodwin](https://goodwinlaw.com/publications/2022/10/10_17-fda-issues-final-clinical-decision); a reported 2026-01-06 guidance update is unconfirmed |
| Bedrock can be used under a BAA | Amazon Bedrock and Bedrock AgentCore are listed as HIPAA-eligible; S3 Vectors is not named separately | Verified | [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) (updated 2026-10-15) |
| Imaging vendors are highly profitable | Siemens Healthineers Imaging adjusted EBIT margin 18.7%–22.4% per quarter in FY2025; group 16.5% | Secondary | [Siemens Healthineers press releases](https://www.siemens-healthineers.com/press/releases/2025q4) (via search summary, not read directly) |
| Imaging downtime is very costly | MRI ~$1,500–$9,000/hour; CT ~$4,200/hour | **Unverified** | Single predictive-maintenance vendor's marketing ([Oxmaint](https://oxmaint.com/industries/healthcare/hospital-downtime-economics-mri-ct-icu-failure)) |
| Imaging OEMs monitor and fix scanners remotely | Practice confirmed by vendor product pages; remote fix rates ~30% (GE, undated) to "up to 50%" (Siemens, 2006) | Practice: Verified. Rates: **Unverified** | [GE OnWatch](https://www.gehealthcare.com/en-us/services/digital-solutions/onwatch), [Siemens Guardian](https://www.siemens-healthineers.com/ba/services/customer-services/upspeed-services/guardian-program), [DOTmed](https://www.dotmed.com/news/story/24870) |

### What this changes

- **Plan wording holds.** No claim in PLAN.md §2.2 was contradicted.
- **Redaction scope (clarification for M0-08):** safe harbor lists device identifiers and serial numbers. A scanner's serial identifies equipment, not a patient, but logs can carry patient IDs, accession numbers, or implant serials. The simulated redaction step removes all patient-linked identifiers; scanner serials may stay.
- **Simulator parameters (labeled assumptions):**
  - Safety-screening routing deadline: well inside the shortest reporting window (EU 2 days, US 5 work days); use 24 hours.
  - Remote-resolution share for F2 at baseline: sample from 30%–50%.
  - Avoided field-visit and downtime value: use wide ranges, never point estimates, and label them unverified in the case study.
- **Still open:** EUR-Lex Art. 87 text; HHS cloud guidance (primary); current FDA CDS guidance version; Siemens Healthineers FY2025 annual report segment table. Re-check before the case study is published (M6-04).
