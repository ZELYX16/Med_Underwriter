# MedUnderwriter: Enterprise Medical Underwriting Engine Architecture Rework

* **Author:** B_Karthikeyan
* **Date:** 2026-11-16
* **Repository:** `c:\Capstone_Proj\Med_Underwriter` (branch `v5.2`)

---

## Overview

The MedUnderwriter platform v5.2 is transitioning from a heuristic localhost prototype—reliant on linear additive scores, rigid regex pattern matching, and uncalibrated human review gates—into an enterprise-grade, clinically grounded medical underwriting engine. The core objective is reconciling **deterministic actuarial precision and regulatory compliance** with **agentic clinical intelligence**:
1. **Deterministic code** strictly governs actuarial pricing, gender/age mortality baselines, comorbidity synergy multipliers, and statutory Pre-Existing Disease (PED) waiting periods.
2. **Language models (LLMs)** are restricted to unstructured clinical entity extraction, medication-to-disease reverse inference, forward explainability narratives, and adversarial multi-persona reflection (MAR) without post-hoc rationalization.
3. **Calibrated 4-Tier Review Gating** replaces queue-choking binary gates, establishing clear criteria for Straight-Through Processing (STP) on clean lives while ensuring rigorous multi-signature escalation for complex multi-morbid risks.

---

## Analysis

### 1. The Multi-Lens Goldfish Critique & Resolved Trade-Offs

Across the specialized EGM review lenses, the current codebase was evaluated against real-world underwriting operations, and three critical engineering trade-offs were explicitly resolved:

* **Domain & Regulatory Architecture (`egm-design`, `egm-comprehension`):**
  * *The Linear Additive Fallacy:* In clinical underwriting, mortality risk from co-occurring diseases is multiplicative. Under the current `agent2_risk.py`, Diabetes ($15$), Hypertension ($8$), and Obesity ($10$) sum linearly to $33$ points (triggering a modest 10% premium loading). Real clinical underwriting (e.g., Swiss Re Life Guide, Munich Re MIRA) models Metabolic Syndrome as an exponential multiplier requiring a $+150\%$ to $+200\%$ loading or deferral due to accelerated vascular and renal end-organ damage.
  * *Missing Clinical Pillars:* Real underwriting never relies solely on self-declaration. Four foundational underwriting models were entirely absent:
    1. **Family Medical History:** Early onset of cardiovascular disease or hereditary cancers in first-degree relatives before age 60.
    2. **Occupational & Avocation Hazards:** Standardized hazard classes (ISCO-08 tiers 1–4) and hazardous recreational pursuits.
    3. **Reverse Pharmacotherapy Inference (Calibrated):** Deducing undeclared pathology from active prescriptions. *Resolved Decision:* Multi-indication drugs (e.g., Metformin for PCOS vs. T2D; low-dose Aspirin for primary prevention vs. secondary CAD prophylaxis) are flagged as `requires_context` with minimal discrepancy weight rather than triggering false-positive fraud escalations. Unambiguous single-indication drugs (e.g., Insulin, Clopidogrel, Methotrexate, Chemotherapeutics) retain high-confidence inference.
    4. **Statutory PED Waiting Periods & Exclusions:** Applying IRDAI 2024 reform caps (maximum 36-month waiting period) and specific ailment exclusion schedules.
  * *Actuarial Pricing Baseline:* *Resolved Decision:* The flat base rate of $\text{Sum Insured} \times 0.03 \times \text{Years}$ is replaced by a full single-year biological age lookup table (ages 18–75 for males and females) referencing Indian Assured Lives Mortality (IALM 2012–14 Ultimate) rates ($q_x$).

* **Technical Details & System Architecture (`egm-codebase-details`, `egm-structural`):**
  * *Extraction Fragility & Fallback Resilience:* Relying on single-line regex patterns with 40-character negation windows (`[^.\n]{0,40}`) creates false positives and fails on two-column diagnostic lab reports. *Resolved Decision:* PyMuPDF table detection parses structured lab panels in $<15\text{ms}$. If an unstructured clinical note triggers targeted LLM fallback and encounters a timeout or malformed JSON, the engine does not crash or retry indefinitely; it records an explicit reason tag (`fallback_reason: "LLM extraction timeout/parsing failure on page X"`) and routes the case directly to **Tier 1 Fast-Track Review** with the raw text pre-highlighted for the underwriter.
  * *Schema Fragmentation:* State dictionaries in `models/state.py` lacked typed models for family history, occupational risk, medication verification, and structured laboratory panels.
  * *Boundary Hygiene:* Orchestration logic was leaking into agent definitions, while state persistence duplicated enrichment payloads across nodes.

* **Strategic & Production Realism (`egm-zoom-out`, `egm-implementation-readiness`):**
  * *Eliminating Review Queue Choking:* Setting a rigid confidence cutoff at $0.70$ caused minor informational omissions to force 50–70% of prototype runs into manual human review. The calibrated 4-Tier model restores automated STP for clean lives while providing 1-click micro-verification for minor gaps.
  * *Post-Hoc Rationalization Prevention:* Prompting LLMs to explain an already calculated deterministic score caused models to invent convincing justifications for flawed underlying numbers. Agent 3 personas are now restricted to forward adversarial falsification tests against raw source facts.

### 2. Inventive TRIZ Contradiction Resolutions

* **Contradiction 1: Clinical Extraction Precision vs. Token Latency & Budget (TRIZ Principle 10: Prior Action & Principle 15: Dynamism)**
  * *Resolution:* The Two-Stage Gatekeeper. PyMuPDF (`fitz`) first executes table grid detection (`page.find_tables()`). If structured lab tables are found, deterministic extraction executes in $<15\text{ms}$ with zero LLM tokens. Targeted LLM fallback is triggered strictly on pages containing unstructured narrative notes, with deterministic routing to Tier 1 Fast-Track upon any failure.
* **Contradiction 2: Deterministic Auditability vs. Flexible Clinical Judgment (TRIZ Principle 24: Intermediary)**
  * *Resolution:* The Evidence-to-Debit Compiler. The LLM emits verified clinical fact flags with confidence scores (`{condition: "Type 2 Diabetes", control: "suboptimal", complications: ["microalbuminuria"]}`). These typed flags feed directly into the deterministic Actuarial Comorbidity Matrix.
* **Contradiction 3: Straight-Through Automation vs. Risk Conservatism (TRIZ Principle 1: Segmentation & Principle 3: Local Quality)**
  * *Resolution:* Calibrated 4-Tier Routing with Micro-Escalations. Replaces the binary "approve vs review" switch with a 4-tier model where atomic ambiguities are resolved via focused micro-tasks.

---

## Goals vs. Non-Goals

### In-Scope Goals

1. **Actuarial Baseline Mortality Integration:** Embed a full single-year biological age lookup table (ages 18–75, male/female) using IALM 2012–14 Ultimate mortality rates ($q_x$).
2. **Multiplicative Comorbidity Synergy Engine:** Implement an actuarial copula tensor modeling non-linear risk compounding for metabolic syndrome, cardiorenal syndrome, and respiratory multimorbidity.
3. **Four Missing Underwriting Modules:**
   * Family Medical History (first-degree premature CAD and hereditary cancer debits).
   * Occupational & Avocation Hazard Scoring (ISCO-08 tiers 1–4).
   * Context-Aware Reverse Pharmacotherapy Inference (differentiating single-indication critical drugs from multi-indication maintenance drugs).
   * Structured PED Waiting Periods & Exclusions (IRDAI 2024 compliance; max 36-month waiting period).
4. **Hybrid Extraction Pipeline & Resilient Fallback:** PyMuPDF line/text table detection for lab panels paired with targeted JSON-mode LLM fallback for unstructured records, with deterministic degradation to Tier 1 review upon timeout.
5. **Calibrated 4-Tier Review Routing:**
   * **Tier 0:** Automated Straight-Through Processing (STP) for clean lives.
   * **Tier 1:** Fast-Track Micro-Verification for single routine gaps or extraction timeouts.
   * **Tier 2:** Standard Underwriter Review for moderate multimorbidity and PED endorsements.
   * **Tier 3:** Senior Escalation / CMO Dual-Sign for severe pathology or discrepancy $\ge 60$.
6. **Forward Adversarial Reflection (Anti-Rationalization):** Reconfigure Agent 3 personas to conduct independent falsification tests against source clinical facts.

### Out-of-Scope Non-Goals

1. **Heavy Vision OCR Models:** Deploying multi-gigabyte vision LLMs locally; the prototype remains strictly lightweight using PyMuPDF and API-based/distilled local text models.
2. **Real-Time Electronic Health Record (EHR) FHIR Connectors:** Live hospital API integration; input remains standardized PDF documents and application payloads.
3. **Direct Core Policy Administration System (PAS) Billing Integration:** The platform emits underwriting decisions, loaded premiums, and exclusion schedules, but does not handle payment gateway collection.

---

## Alternatives Weighed

1. **Pure LLM End-to-End Underwriting (Rejected):**
   * *Rejection Reason:* Disastrous lack of auditability. Regulators require deterministic replayability. Stochastic token sampling produces varying premiums for identical clinical profiles.
2. **Full Vision OCR Pipeline (Tesseract / PaddleOCR / LayoutLM) (Rejected):**
   * *Rejection Reason:* Introduces massive local compute overhead (30–60 seconds per case) and memory consumption. Over 90% of digitally generated lab reports are vector PDFs easily parsed by PyMuPDF in under 50ms.
3. **Unchecked Reverse Pharmacotherapy Inference (Rejected):**
   * *Rejection Reason:* Treating multi-indication drugs (e.g., Metformin for PCOS or pre-diabetes) as automatic Type 2 Diabetes produces high false-positive fraud escalations, damaging customer experience and underwriting trust.

---

## Key Decisions & Staging for Next Steps

### Key Architectural Decisions

1. **State Schema Evolution:** Strongly typed Pydantic v2 schemas in [`models/state.py`](file:///c:/Capstone_Proj/Med_Underwriter/backend/app/models/state.py) (`FamilyHistoryRecord`, `OccupationHazardRecord`, `MedicationVerificationItem`, `PEDWaitingPeriod`, `LabAnalyteRecord`).
2. **Deterministic Engine Segregation:** Numerical Rating System and copula interactions isolated in [`services/medical_synergy.py`](file:///c:/Capstone_Proj/Med_Underwriter/backend/app/services/medical_synergy.py) with full IALM 2012–14 mortality tables.
3. **Forward-Only Reflection Protocol:** Agent 3 personas evaluate clinical guidelines independently, prohibiting personas from modifying mathematical risk scores directly.

### Staging for Next Phase (`/egm-draft` & Implementation)

```
Phase 1: Domain Schemas & Reverse Pharmacotherapy Mapping
         ├── Define Pydantic models in models/state.py
         └── Create medication_inference_map.json with context tags (PCOS vs T2D)

Phase 2: Hybrid Extraction & Table Normalization
         ├── Integrate PyMuPDF page.find_tables() in rag/structured.py
         └── Implement schema-constrained LLM fallback with Tier 1 degradation on timeout

Phase 3: Actuarial Baseline & Multiplicative Synergy Engine
         ├── Embed full single-year biological age IALM 2012-14 Ultimate mortality table (18-75)
         ├── Build services/medical_synergy.py (Metabolic, Cardiorenal, Respiratory copulas)
         └── Refactor agent2_risk.py to Numerical Rating System (Base 100 + Debits * Synergy)

Phase 4: PED Waiting Periods & IRDAI Harmonization
         └── Implement 36-month statutory waiting period and specific ailment exclusion rules

Phase 5: Calibrated 4-Tier Review Gating & Forward MAR
         ├── Refactor services/review_gate.py into Tiers 0, 1, 2, and 3
         └── Reconfigure Agent 3 personas into forward adversarial falsification evaluators
```
