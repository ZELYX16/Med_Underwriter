# MedUnderwriter Frontend Modernization: Enterprise Design System, Step Inspectors, Document Viewer & Workflow Visualizer

*   **Author:** B_Karthikeyan
*   **Status:** Approved Draft
*   **Date:** 2026-11-16
*   **Target Branch:** `v5.2`

--------------------------------------------------------------------------------

## Overview

MedUnderwriter is an enterprise-grade medical underwriting AI system. It automates health insurance risk assessment by orchestrating a deterministic actuarial pipeline with multi-agent intelligence and reflection across seven sequential stages:
1. **Intake Stage:** Ingests applicant declarations, lifestyle attributes, and uploaded clinical documents.
2. **Agent 1 (Submission Intelligence):** Extracts table data, normalizes laboratory analytes, indexes document chunks, and identifies documentation gaps.
3. **Complexity Router:** Classifies application complexity and determines downstream routing strategies.
4. **Agent 2 (Risk Assessment & Actuarial Rating):** Cross-validates medications with declared conditions via reverse pharmacotherapy, computes Copula synergy comorbidity multipliers, calculates single-year actuarial mortality baselines using IALM 2012–14 Ultimate tables, and structures statutory Pre-Existing Disease (PED) waiting periods under IRDAI regulations.
5. **Confidence Gate:** Evaluates risk scores and layered confidence margins to decide whether adversarial reflection is required.
6. **Agent 3 (Constitutional AI & MAR Reflection):** Conducts multi-persona debate (Chief Medical Officer, Senior Actuary, Compliance Officer) to challenge underwriting decisions.
7. **Review Gate & Finalization:** Applies 4-Tier gating (Tier 0 Straight-Through Processing to Tier 3 Executive Escalation).

The existing Streamlit user interface (`frontend/app.py`, ~5,300 lines of code) provides high-level case summaries and final decisions, but does not provide adequate intermediate verification mechanisms or path explainability for human underwriters. This design modernizes the Streamlit frontend with a tokenized enterprise design system, dedicated read-only step verification modals (`@st.dialog`) with isolated execution boundaries (`@st.fragment`), an in-app interactive document viewer, and an interactive execution path visualizer rendering traversed nodes, bypassed branches, and decision criteria.

---

## The Problem

1. **Lack of Intermediate Verification for Regulatory Explainability:**
   Medical underwriting decisions require strict traceability. Currently, intermediate calculation inputs—such as individual condition debits, multivariate Copula synergy multipliers ($\Phi$), IALM 2012–14 mortality baseline rates ($q_x$), and reverse pharmacotherapy discrepancy scores—are nested inside internal JSON payloads. Underwriters cannot easily verify how a 35% premium loading was mathematically derived without manual data inspection.

2. **Inaccessible Source Documentation in Underwriting Review:**
   When an underwriter audits an intake case or flags a discrepancy, they must verify extracted facts against the original hospital discharge summaries, policy schedules, or laboratory reports. Currently, uploaded files live on disk or within SQLite tables without an in-app document viewer, forcing underwriters to download files externally.

3. **Opaque Workflow Execution Paths:**
   The multi-agent orchestrator makes branching routing decisions (e.g., whether a case bypassed Agent 3 reflection via the Confidence Gate, whether a rescore loop was triggered, or why a case was routed to Tier 2 rather than Tier 0). The interface displays an unstructured sequential text log (`workflow_trace`), lacking visual topology or explicit condition predicates.

4. **Monolithic Script Reruns & UI Lag:**
   Streamlit's default execution model re-executes the entire script on user interaction. In a 5,300-line script handling large multi-megabyte cases, expanding details or clicking tabs causes page-level re-evaluation, slow rendering (>1.5s latency), and visual jitter.

---

## Goals

*   **Goal 1 (Enterprise Design System):** Introduce a cohesive, modern visual theme in `frontend/styles.py` featuring tokenized elevation surfaces (`--color-surface-elevated`, `--shadow-card`), professional typographic scaling (Inter and Roboto Mono), and accessible WCAG 2.1 AA status badges for review tiers and decisions.
*   **Goal 2 (Step-by-Step Verification Modals):** Provide dedicated `[🔎 Verify Step]` buttons across all seven pipeline stages (Intake, Agent 1, Router, Agent 2, Confidence Gate, Agent 3, Review Gate) opening `@st.dialog` modal inspectors with structured 3-tab layouts (Executive Summary, Formula & Calculation Trace, Raw State Snapshot).
*   **Goal 3 (In-App Document Viewer):** Allow underwriters to view all uploaded files associated with a case directly within the Intake stage and Evidence workspace via an embedded viewer modal (`@st.dialog`) with PDF and text rendering.
*   **Goal 4 (Workflow Path Visualizer):** Render an interactive Mermaid execution flowchart generated dynamically from `case["workflow_trace"]`, explicitly highlighting traversed nodes, bypassed branches, execution durations, and Boolean branch conditions.
*   **Goal 5 (Execution Boundary Isolation):** Encapsulate all step verification modals, document viewers, and graph visualizers within `@st.fragment` to prevent top-level script reruns and ensure responsive interaction.

---

## Non-Goals

*   **Non-Goal 1 (Frontend Framework Rewrite):** No rewrite into single-page application frameworks (such as React, Vue, or Angular). The interface will remain fully built on Streamlit and Python.
*   **Non-Goal 2 (Interactive State Mutation in Inspectors):** Underwriters will not be able to modify intermediate step values (e.g., altering Copula debits or modifying extracted lab analytes inside the inspection modal). All intermediate inspectors are strictly read-only; manual overrides remain confined to the authorized Human Review Action Bar.
*   **Non-Goal 3 (Database Schema Changes):** No modifications to the SQLite database schema or LangGraph checkpoint structures.

---

## Open Questions

*   **Question 1**: How should multi-page PDFs be rendered within `@st.dialog` when browser PDF plugins are disabled or restricted? (Evaluated option: fallback to rendering rendered page images via PyMuPDF alongside raw extracted text).
*   **Question 2**: For cases that underwent Agent 3 reflection rescores (`reflection_requires_rescore`), should the Agent 2 inspector display only the latest scoring snapshot or provide a revision selector across reflection rounds?

---

## Critical User Journeys (CUJs)

### CUJ 1: Underwriter Audits Actuarial Debits & Copula Synergy (Agent 2)
*   **Given**: An underwriter opens a complex case (e.g., Klaus) flagged for Human Review due to elevated medical risk.
*   **When**: The underwriter navigates to the Case Workspace and clicks the `[🔎 Verify Step]` button on the Agent 2 Risk Engine card.
*   **Then**: An isolated `@st.dialog` modal appears without rerunning the main page. The underwriter selects the "Formula & Mechanics" tab, which clearly displays the breakdown:
    - Base condition debits: T2D (20 debits) + HTN (10 debits) + Smoker (25 debits).
    - Copula Synergy: Metabolic Syndrome Triad detected ($\text{T2D} + \text{HTN} + \text{Obesity}$), applying multiplier $\Phi = 1.45$.
    - Actuarial extra mortality percentage ($EMP = 179.75\%$) and resulting premium loading ($+79.75\%$).
    - The underwriter confirms the mathematical integrity of the loading before issuing approval.

### CUJ 2: Underwriter Inspects Uploaded Medical Document (Intake)
*   **Given**: An applicant submitted a proposal declaring hypertension and uploaded a hospital discharge summary.
*   **When**: In the Intake stage inspection card, the underwriter reviews the "Uploaded Files" table and clicks `[📄 View Document]` on `discharge_summary.pdf`.
*   **Then**: A document viewer modal opens displaying the PDF document alongside extracted clinical metadata (document date, detected type, and recency status) so the underwriter can confirm that the dates and hospital diagnoses match the application.

### CUJ 3: Underwriter Explains Workflow Path & Branch Routing
*   **Given**: A regulatory auditor or senior underwriter needs to understand why an application was routed to Tier 2 Human Review instead of being auto-approved (Tier 0).
*   **When**: The underwriter clicks the dedicated `[🗺️ View Execution Path]` button on the Overview tab.
*   **Then**: A highlighted execution graph appears. Visited nodes (Intake, Agent 1, Router, Agent 2, Confidence Gate, Agent 3, Review Gate, Human Review) are highlighted in solid blue/green, while bypassed branches (Fast Finalize, Tier 0 Auto-Approve) are shown in dashed gray. Next to the Review Gate, an annotation explains: `Decision: Tier 2 (Overall Risk 74.2 >= 70.0 threshold) -> Route to Human Review`.

---

## Technical Plan (Architecture)

```mermaid
flowchart TD
    subgraph UI_WORKSPACE ["Streamlit Underwriter Workspace (frontend/app.py)"]
        HEADER["Case Header & Status Badge"]
        ACT_BAR["Human Review Action Bar"]
        NAV["Workspace Navigation (Overview | Evidence | Assessment | Decision | Review & Audit)"]
    end

    subgraph DESIGN_SYSTEM ["Design System (styles.py & design_system.py)"]
        CSS_TOKENS["CSS Variables & Typography (Inter / Roboto Mono)"]
        ELEV_CARD["Elevated Card Containers (Surface 1 & Surface 2)"]
        STATUS_BADGES["Semantic Badges (Tier 0..3, Approved, Review, Declined)"]
    end

    subgraph INSPECTION_LAYER ["Step Inspectors (@st.dialog + @st.fragment)"]
        direction TB
        INS_INTAKE["01. Intake & File Manifest Inspector"]
        INS_AG1["02. Agent 1 Submission Intelligence Inspector"]
        INS_ROUTER["03. Complexity Router Inspector"]
        INS_AG2["04. Agent 2 Risk & Actuarial Rating Inspector"]
        INS_CONF["05. Confidence Gate Inspector"]
        INS_AG3["06. Agent 3 MAR Reflection Inspector"]
        INS_GATE["07. Review Gate & Tier Routing Inspector"]
    end

    subgraph DOC_VIEWER ["In-App Document Viewer (@st.dialog)"]
        DOC_MODAL["Document Modal (PDF Iframe / PyMuPDF Page Images / OCR Text)"]
    end

    subgraph GRAPH_VIS ["Execution Path Visualizer (graph_visualizer.py)"]
        MERMAID_GEN["Dynamic Mermaid Generator (workflow_trace Parser)"]
        COND_ANNOT["Edge Predicate & Latency Annotator"]
        STEP_PILLS["Traversed Step Jump Pills [🔎 Verify Step]"]
    end

    subgraph BACKEND_API ["FastAPI Backend (backend/app/api)"]
        CASE_STATE["GET /api/case/{id} (State Snapshot)"]
        DOC_STREAM["GET /api/case/{id}/documents/{doc_id}/content (FileResponse)"]
        CHECKPOINTS["LangGraph Checkpoint Store"]
    end

    UI_WORKSPACE --> DESIGN_SYSTEM
    UI_WORKSPACE -->|Click [🔎 Verify Step]| INSPECTION_LAYER
    UI_WORKSPACE -->|Click [🗺️ View Execution Path]| GRAPH_VIS
    INS_INTAKE -->|Click [📄 View Doc]| DOC_VIEWER

    INSPECTION_LAYER -.->|State Slices| CASE_STATE
    DOC_VIEWER -.->|Stream PDF Bytes| DOC_STREAM
    GRAPH_VIS -.->|Parse workflow_trace| CASE_STATE
```

### 1. Enterprise Design System Tokens (`frontend/styles.py` & `frontend/components/design_system.py`)

The visual system establishes clean typography, high contrast, and accessible WCAG 2.1 AA tokenized styling:
- **Font Stack:**
  - Body & UI Controls: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
  - Financial, Numerical & Actuarial Tables: `"Roboto Mono", Menlo, Consolas, monospace`
- **Surface Elevation Hierarchy:**
  - `Surface 0 (Canvas)`: Background `#f8fafc` (light) / `#0f172a` (dark)
  - `Surface 1 (Card)`: `#ffffff` with 1px border (`#e2e8f0`) and subtle elevation `box-shadow: 0 1px 3px 0 rgba(0,0,0,0.05)`
  - `Surface 2 (Modal / Inspector Dialog)`: `#ffffff` with `box-shadow: 0 20px 25px -5px rgba(0,0,0,0.15)`
- **Semantic Status Badges:**
  - `Tier 0 (STP)`: `#ecfdf5` background, `#065f46` text, `#a7f3d0` border (Icon: `✓`)
  - `Tier 1 (Fast-Track)`: `#eff6ff` background, `#1e40af` text, `#bfdbfe` border (Icon: `⚡`)
  - `Tier 2 (Comprehensive)`: `#fffbeb` background, `#92400e` text, `#fde68a` border (Icon: `⚠️`)
  - `Tier 3 (CMO Escalation)`: `#fef2f2` background, `#991b1b` text, `#fecaca` border (Icon: `🛑`)

### 2. Modular Step Verification Inspector Architecture (`frontend/components/inspectors/`)

To prevent bloating `frontend/app.py`, inspection logic is partitioned into dedicated modules inside `frontend/components/inspectors/`:
1. `base_inspector.py`: Base helper rendering the standardized 3-tab layout (`tab_summary`, `tab_mechanics`, `tab_raw_json`).
2. `intake_inspector.py`:
   - Tab 1: Profile attributes (age, sex, BMI), declarations, and uploaded file manifest.
   - Tab 2: KYC check results, validation rules, and document type classifications.
   - Tab 3: Raw `applicant_profile` and `submission` JSON.
   - Includes embedded `[📄 View Document]` buttons for each uploaded file.
3. `agent1_inspector.py`:
   - Tab 1: Extracted tables summary, total facts, evidence completeness score.
   - Tab 2: PyMuPDF layout tables, lab analyte normalized values against reference ranges, recency evaluation (recent/acceptable/stale), and confirmed vs. unconfirmed coverage gaps.
   - Tab 3: Raw `agent1_enrichment` and `structured_facts` JSON.
4. `router_inspector.py`:
   - Tab 1: Selected complexity level (`standard` vs `complex`) and routing strategy.
   - Tab 2: Multi-morbidity score breakdown, high sum insured check, and rule triggers.
   - Tab 3: Raw `routing_result` JSON.
5. `agent2_inspector.py`:
   - Tab 1: Actuarial debits, Copula synergy multiplier ($\Phi$), extra mortality percentage ($EMP$), premium loading %, and calculated baseline premium ($P_{\text{base}}$).
   - Tab 2:
     - *Reverse Pharmacotherapy Table:* Drug name, inferred condition, declaration match, discrepancy points, context exception tags.
     - *Copula Synergy Matrix:* Active syndromic pairs/triads (Metabolic, Cardiorenal, Respiratory), multiplier coefficients.
     - *Actuarial Mortality Table:* Biological age baseline mortality ($q_x$) from IALM 2012–14 Ultimate.
     - *PED Waiting Periods:* Ailment clauses with 24/36 month caps and permanent exclusion tags.
   - Tab 3: Raw `risk_assessment`, `copula_synergy_details`, `medication_records`, and `pricing_result` JSON.
6. `confidence_gate_inspector.py`:
   - Tab 1: Composite confidence score, gate verdict (`pass` vs `reflection_required`).
   - Tab 2: Bayesian confidence layer breakdown, margin to threshold (0.70), and assigned reflection depth.
   - Tab 3: Raw confidence state snapshot.
7. `agent3_inspector.py`:
   - Tab 1: Multi-Agent Reflection verdict (`pass`, `concern`, `rescore`), consensus status.
   - Tab 2: Individual persona critique transcripts (Chief Medical Officer, Senior Actuary, Regulatory Compliance Officer), constitutional evaluations, and rescore directives.
   - Tab 3: Raw `reflection_findings` and `agent3_metrics` JSON.
8. `review_gate_inspector.py`:
   - Tab 1: Assigned review tier (`Tier 0` to `Tier 3`), human review requirement boolean.
   - Tab 2: Rule evaluation audit: Medical risk threshold (80.0), overall risk threshold (70.0), fraud discrepancy threshold (50.0), security quarantine checks, and mandatory reason list.
   - Tab 3: Raw review gate decision package JSON.

### 3. Backend Document Streaming Endpoint & Frontend Document Viewer

- **FastAPI Endpoint (`backend/app/api/routes.py`):**
  ```python
  @router.get("/case/{case_id}/documents/{document_id}/content")
  async def get_case_document_content(case_id: str, document_id: str):
      doc = state_store.get_case_document(case_id, document_id)
      if not doc or not doc.get("file_path"):
          raise HTTPException(status_code=404, detail="Document content not found.")
      file_path = Path(doc["file_path"])
      if not file_path.exists():
          raise HTTPException(status_code=404, detail="Physical document file missing on disk.")
      media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
      return FileResponse(path=file_path, media_type=media_type, filename=file_path.name)
  ```
- **Streamlit In-App Viewer Modal (`frontend/components/document_viewer.py`):**
  - Defines `@st.dialog("Document Viewer - {filename}", width="large")`.
  - For PDF documents: Renders an embedded `<iframe>` with base64 encoded PDF bytes, or page-by-page visualizer via PyMuPDF image rendering if iframes are restricted.
  - Side pane shows extracted document date, detected document type, document recency status, and SHA-256 fingerprint.

### 4. Interactive Execution Path Visualizer (`frontend/components/graph_visualizer.py`)

- **Dynamic Mermaid Generator:**
  - Reads `case.get("workflow_trace", [])` and `case.get("audit_trail", [])`.
  - Builds a topology graph of the LangGraph execution.
  - Determines node state:
    - `traversed`: Node executed and recorded in `workflow_trace`.
    - `bypassed`: Alternative conditional branch never executed (e.g. `fast_finalize` bypassed when `confidence < 0.70`).
    - `active`: Current terminal state (e.g., `human_review` awaiting underwriter action).
  - Annotates edges with evaluated Boolean predicates (e.g., `Tier 2 Escalation (Risk 74 >= 70)`).
  - Below the graph, renders a responsive pill bar allowing the underwriter to click `[🔎 Inspect Intake]`, `[🔎 Inspect Agent 1]`, ..., `[🔎 Inspect Review Gate]` to trigger the respective inspector modal directly.

### 5. Execution Boundary Isolation (`@st.fragment`)

- To maintain sub-second response times and prevent full-page script reruns:
  - The workflow visualizer is wrapped in `@st.fragment(run_every=None)`.
  - Inspector triggers and document modals execute inside isolated dialog contexts.
  - Sliced state payloads prevent copying multi-megabyte text chunks across session state.

---

## Alternatives Considered

### Alternative A: Full Single-Page Application (SPA) Rewrite (React / TypeScript / Vite)
*   **Pros**: Full control over DOM manipulation, zero-lag client-side state rendering, rich drag-and-drop animation libraries, and deep integration with canvas graphing tools (e.g., React Flow).
*   **Cons**: Requires discarding over 5,000 lines of verified underwriter desktop code, developing a separate TypeScript/React build pipeline, building custom REST client state sync layers, and duplicating server-side data models.
*   **Reason for Rejection**: Rejected by author: Unnecessary engineering overhead and operational complexity for an enterprise underwriting desktop prototype when Streamlit 1.34+ natively provides `@st.dialog` modal overlays, `@st.fragment` boundary isolation, and native Mermaid support.

### Alternative B: Third-Party Embedded Graph Canvas (`streamlit-agraph` / `pyvis`)
*   **Pros**: Allows bi-directional Python event listeners directly on node clicks inside the graph canvas.
*   **Cons**: Introduces heavy, unvetted external JavaScript packages that break Streamlit's dark/light theme CSS variables, causes layout reflows on high-DPI displays, and adds fragile iframe sandbox boundaries.
*   **Reason for Rejection**: Rejected by author: Dependency bloat and cross-origin iframe styling breakages. Native Streamlit Mermaid rendering combined with adjacent step inspection pills achieves high visual fidelity with zero additional third-party dependencies.

### Alternative C: Inline Expandable Accordions Instead of Modal Dialogs
*   **Pros**: Simple to build using standard `st.expander()`.
*   **Cons**: Results in extreme vertical page bloat (>8,000 pixels tall when inspecting multiple agents), clutters the core review workspace, and causes full script reruns whenever an expander is opened or closed.
*   **Reason for Rejection**: Rejected by author: Fails to isolate visual clutter and causes page-level re-evaluation, degrading underwriter focus and response times.

---

## Detailed Implementation Plan

The implementation is structured into 5 sequential phases across 18 enumerated target files.

### Phase 1: Backend Document Streaming Endpoint
*   **Target File 1: `backend/app/api/routes.py`**
    *   *Rationale:* Implement `GET /case/{case_id}/documents/{document_id}/content` returning `FileResponse` with media type `"application/pdf"` or `"application/octet-stream"`. Validates that the document belongs to the case, resolves the physical file path via `state_store.get_case_document()`, and verifies file existence to prevent arbitrary directory traversal.
*   **Target File 2: `frontend/api_client.py`**
    *   *Rationale:* Add `get_case_document_content(case_id, document_id) -> bytes` and helper `get_document_content_url(case_id, document_id) -> str` to enable the frontend to stream document bytes.
*   **Target File 3: `backend/tests/test_document_content_api.py`**
    *   *Rationale:* Write unit tests verifying successful document content streaming, 404 for missing documents, and security validation for invalid document IDs.

### Phase 2: Design System Tokens & Modern UI Components
*   **Target File 4: `frontend/styles.py`**
    *   *Rationale:* Add CSS variables for 3-surface elevation (`--color-surface-elevated`, `--shadow-card`, `--shadow-elevated`), font families (Inter and Roboto Mono), and accessible WCAG 2.1 AA status badge styles for review tiers (`Tier 0` to `Tier 3`).
*   **Target File 5: `frontend/components/design_system.py`**
    *   *Rationale:* Create reusable UI primitives: `status_badge(text, level)`, `elevated_card()`, `formula_callout()`, and `metric_surface()`.

### Phase 3: In-App Document Viewer Component
*   **Target File 6: `frontend/components/document_viewer.py`**
    *   *Rationale:* Implement `@st.dialog("Document Viewer - {filename}", width="large")` supporting PDF preview (via base64 encoded iframe with fallback to page-by-page PyMuPDF rendering) and raw text preview side-by-side with document metadata.

### Phase 4: Modular Step Verification Inspectors Package
*   **Target File 7: `frontend/components/inspectors/__init__.py`**
    *   *Rationale:* Package initialization exposing inspector modal trigger functions.
*   **Target File 8: `frontend/components/inspectors/base_inspector.py`**
    *   *Rationale:* Implement base layout wrapper rendering the standardized 3-tab structure (`Executive Summary`, `Formula & Rule Mechanics`, `Raw State Snapshot`) and copy buttons.
*   **Target File 9: `frontend/components/inspectors/intake_inspector.py`**
    *   *Rationale:* Implement `render_intake_inspector(case)` with applicant demographics, declarations, and file manifest table with `[📄 View Document]` buttons.
*   **Target File 10: `frontend/components/inspectors/agent1_inspector.py`**
    *   *Rationale:* Implement `render_agent1_inspector(case)` detailing PyMuPDF layout tables, normalized lab analytes, evidence recency flags, and confirmed coverage gaps.
*   **Target File 11: `frontend/components/inspectors/router_inspector.py`**
    *   *Rationale:* Implement `render_router_inspector(case)` displaying complexity scoring breakdown, multi-morbidity flags, and routing strategy selection rules.
*   **Target File 12: `frontend/components/inspectors/agent2_inspector.py`**
    *   *Rationale:* Implement `render_agent2_inspector(case)` displaying reverse pharmacotherapy drug-disease matches, Copula synergy comorbidity matrix ($\Phi$), individual actuarial debits, IALM 2012–14 baseline mortality lookup ($q_x$), and IRDAI 2024 PED waiting periods.
*   **Target File 13: `frontend/components/inspectors/confidence_gate_inspector.py`**
    *   *Rationale:* Implement `render_confidence_gate_inspector(case)` showing Bayesian confidence layers, distance to threshold (0.70), and reflection trigger justification.
*   **Target File 14: `frontend/components/inspectors/agent3_inspector.py`**
    *   *Rationale:* Implement `render_agent3_inspector(case)` rendering multi-persona debate transcripts (Chief Medical Officer, Actuary, Compliance Officer), constitutional check matrix, and rescore directive history.
*   **Target File 15: `frontend/components/inspectors/review_gate_inspector.py`**
    *   *Rationale:* Implement `render_review_gate_inspector(case)` displaying 4-Tier classification logic (Tier 0 to Tier 3), mandatory human escalation triggers, and business gate rules.

### Phase 5: Workflow Visualizer & Case Workspace Integration
*   **Target File 16: `frontend/components/graph_visualizer.py`**
    *   *Rationale:* Implement pure function `generate_mermaid_graph(case: dict) -> str` that parses `case["workflow_trace"]`, highlights traversed nodes and bypassed branches, annotates Boolean edge predicates, and renders adjacent `[🔎 Verify Step]` pills within an `@st.fragment`.
*   **Target File 17: `frontend/app.py`**
    *   *Rationale:* Integrate the elevated design system, embed `render_workflow_visualizer(case)` in the Case Workspace Overview tab, and inject dedicated `[🔎 Verify Step]` action buttons onto each agent card.
*   **Target File 18: `frontend/tests/test_graph_visualizer.py`**
    *   *Rationale:* Write unit tests verifying Mermaid string generation, node traversal classes, and edge condition annotations across sample cases.
