# Modernizing MedUnderwriter Frontend: Enterprise Design System, Step Inspectors, Document Viewer & Workflow Graph Visualizer

* **Author:** B_Karthikeyan
* **Date:** 2026-11-16

---

## Overview

MedUnderwriter currently runs a Streamlit-based underwriter desktop (`frontend/app.py`, ~5,300 lines of code) backed by a FastAPI orchestrator that executes a multi-agent LangGraph pipeline:
`Intake -> Agent 1 (Submission Intelligence) -> Complexity Router -> Agent 2 (Risk & Actuarial Rating) -> Confidence Gate -> Agent 3 (Multi-Persona Reflection) -> Review Gate -> Finalize`.

While the backend engine provides actuarial copula calculations, reverse pharmacotherapy cross-validation, and 4-tier routing, the frontend interface currently lacks:
1. **Design System & Elevation:** Monolithic layout with flat `#f4f6f9` backgrounds, basic text blocks, unstyled borders, and uncalibrated visual hierarchy.
2. **Intermediate Step Auditing:** Underwriters cannot verify exact intermediate outputs, rule criteria, or formula inputs at each step (e.g., PyMuPDF table extractions, copula synergy interaction terms, extra mortality percentages, reflection persona debate transcripts, review tier triggers) without digging through raw JSON payloads.
3. **Uploaded Document Accessibility:** Underwriters cannot inspect the original uploaded PDFs, discharge summaries, or lab reports directly in the browser to verify extracted facts against the source documents.
4. **Execution Path Traceability:** No visual representation of the path an application traveled through the LangGraph state machine, leaving underwriters unaware of why specific branches were chosen or bypassed.

This proposal modernizes the Streamlit user interface without rewriting it from scratch. It introduces a modern enterprise design system tokenized in CSS, dedicated read-only step verification modals (`@st.dialog`) with `@st.fragment` boundary isolation for each of the seven pipeline stages, an in-app interactive document viewer for uploaded files under the Intake stage, and an interactive execution graph visualizer rendering traversed nodes, bypassed branches, and exact edge conditions.

---

## Analysis

### 1. Multi-Lens Architectural Findings

- **Contrarian / Complexity Minimization (`egm-zoom-out`):**
  - Completely replacing Streamlit with React/Vue would discard thousands of working lines of underwriting verification and require writing separate REST serialization layers, authentication, and state synchronization.
  - Modern Streamlit (version 1.34+) natively supports `@st.dialog` (isolated modal popups) and `@st.fragment` (isolated component reruns). Leveraging these native primitives achieves modal drill-downs without page-level rerun flickering.
  - Native Mermaid diagram blocks (`st.markdown("```mermaid ...```")`) render clean flowchart graphs directly in the browser with zero additional JavaScript dependencies or heavy third-party packages.

- **Frontend Rerun Economics & Latency (`egm-codebase-details`):**
  - In Streamlit, user interactions (such as expanding an element or clicking a button) rerun the top-level script from line 1. `frontend/app.py` is 5,306 lines long; recalculating data or re-parsing multi-megabyte PDF chunks during button clicks introduces noticeable UI lag (>1.5s).
  - *Remediation:*
    1. Wrap all step verification modals and graph visualizers inside `@st.fragment` so modal interactions do not trigger parent script reruns.
    2. Extract only targeted state slices for each inspector (e.g., passing strictly `copula_synergy_details`, `pricing_result`, and `medication_records` to Agent 2 inspector) rather than hydrating the entire multi-megabyte case dictionary.

- **Document Viewing Architecture (`egm-design` & `egm-codebase-details`):**
  - Uploaded case files are tracked in SQLite `applicant_documents` and stored on the filesystem. Currently, no endpoint streams these bytes to the frontend.
  - *Remediation:* Add a lightweight FastAPI endpoint `GET /api/case/{case_id}/documents/{document_id}/content` returning `FileResponse(path, media_type="application/pdf")`. In Streamlit, render an embedded document viewer modal (`@st.dialog`) supporting PDF preview (via base64 iframe or PyMuPDF page images) and text fallback so underwriters can verify the physical document without downloading it to their local machine.

- **Auditability & Explainable AI Governance (`egm-design` & `egm-comprehension`):**
  - Underwriters spend 60–90 seconds per routine case. Exposing raw ASTs or unprocessed state dictionaries causes cognitive fatigue.
  - Each step inspector modal must follow a standardized 3-tab progressive disclosure pattern:
    1. **Summary Tab:** Clean cards displaying decision status, key inputs, and high-level outputs.
    2. **Formula & Calculation Trace Tab:** Exact mathematical formulas and rule inputs (e.g., Copula synergy coefficient $\Phi = 1.45$, individual condition debits, IALM 2012–14 baseline mortality $q_x$, IRDAI statutory PED waiting period caps).
    3. **Raw State Snapshot Tab:** Formatted, copyable, read-only JSON.

- **System Contradiction & Inventive Resolutions (`egm-inventive-catalyst` / TRIZ):**
  - *Contradiction:* Underwriters require exhaustive forensic auditability, but rendering complete historical state clutters the UI and slows rendering.
  - *Resolution (TRIZ Principle 1 - Segmentation & Principle 2 - Extraction):* The primary case workspace remains elevated and compact. Granular forensic audits are segmented into dedicated `@st.dialog` modal inspectors that load intermediate state slices on demand.
  - *Contradiction:* Dynamic visual graphs in Streamlit either require heavy third-party canvas libraries (`streamlit-agraph`) that break responsive themes or static Markdown diagrams that lack click callbacks.
  - *Resolution (TRIZ Principle 10 - Prior Action & Combining):* Render a Mermaid graph highlighting traversed nodes and bypassed branches, paired directly with an adjacent grid of inspection buttons (`[🔎 Verify Step]`) mapped directly to the corresponding `@st.dialog` functions.

---

## Goals vs. Non-Goals

### In-Scope Goals

1. **Enterprise Design System & Tokenized Styling (`frontend/styles.py` & `frontend/components/design_system.py`):**
   - Modern typographic scale using Inter and Roboto Mono for numerical and financial figures.
   - Three-level surface elevation (`--color-surface-elevated`, `--shadow-card`, `--shadow-elevated`).
   - Semantic status badge system for review tiers (`Tier 0` to `Tier 3`), decisions (`Approved`, `Approved with Loading`, `Human Review`, `Declined`), and node execution states (`Completed`, `Active`, `Bypassed`).
   - WCAG 2.1 AA accessible color contrast ratios.

2. **Dedicated Step Verification Modals (`@st.dialog`):**
   - Provide dedicated audit buttons across all 7 pipeline steps:
     1. **Intake Stage:** Applicant profile, KYC parameters, declared ailments, file manifest, and interactive document viewer trigger.
     2. **Agent 1 (Intelligence):** PyMuPDF table structures, normalized lab analytes, evidence recency flags, declared vs. documented discrepancies.
     3. **Complexity Router:** Multi-morbidity score breakdown, high-sum-insured threshold checks, and selected routing strategy.
     4. **Agent 2 (Risk & Actuarial Engine):** Reverse pharmacotherapy verification, Copula synergy multiplier ($\Phi$), individual actuarial debits, IALM 2012–14 mortality baseline, and IRDAI 2024 PED waiting periods.
     5. **Confidence Gate:** Bayesian confidence layer breakdown, score margin from review thresholds, and reflection depth trigger.
     6. **Agent 3 (Reflection):** Persona debate records (Medical Director, Chief Actuary, Compliance Officer), constitutional compliance checks, and rescore mandates.
     7. **Review Gate:** 4-Tier classification logic, mandatory review triggers, and escalation reason codes.
   - All modals operate in strictly read-only mode to prevent uncommitted state mutation.

3. **Uploaded Document Viewer:**
   - Listing of all uploaded files associated with the case under the Intake stage and Evidence workspace.
   - Interactive document viewer modal (`@st.dialog`) displaying PDF pages, scanned reports, and OCR text side-by-side with extracted clinical attributes.
   - Backend endpoint `GET /api/case/{case_id}/documents/{document_id}/content` delivering file bytes safely via FastAPI `FileResponse`.

4. **Interactive Workflow Graph Visualizer (`frontend/components/graph_visualizer.py`):**
   - Render a high-fidelity Mermaid execution graph generated dynamically from `case["workflow_trace"]`.
   - Visually distinguish traversed nodes (solid border, elevated fill), bypassed branches (dashed border, muted gray), active nodes (pulsing green/amber), and decision gates (hexagonal/diamond yellow).
   - Display node latency, execution timestamps, and exact Boolean edge conditions (e.g., `Confidence < 0.70 => Route to Agent 3`).

5. **Component Modularization & Performance:**
   - De-monolithize `frontend/app.py` by organizing inspectors into `frontend/components/inspectors/`.
   - Protect modal interactions using `@st.fragment` to prevent full page script reruns.

### Out-of-Scope Non-Goals

1. **Complete Single-Page App Framework Rewrite:** No migration to React, Next.js, or Angular; the solution remains fully within Python and Streamlit.
2. **Interactive Intermediate State Mutation:** Underwriters cannot edit intermediate calculations (e.g. manually tampering with Copula debits or changing extracted lab values inside the modal); manual overrides remain strictly reserved for the final human review action bar.
3. **Database Migration:** No modifications to SQLite checkpoint storage or schema models.
