# Goldfish Annotated Review Report

**Target:** `docs/designs/enterprise_underwriting_engine.md` (Lines 296–416)  
**Status:** In Review / Ready for Resolution

---

## Prioritized Findings & AI Suggestions

### 1. Pydantic v2 vs. LangGraph Serialization Conflict [`egm-implementation-readiness`] - Severity: 🔴 Blocker
*   **Affected Scope:** [Lines 300–306](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L300-L306) (`models/state.py`)
*   **Discrepancy Description:** LangGraph `UnderwritingState` is a `TypedDict`. State is checkpointed into SQLite via `AsyncSqliteSaver` and stored in `medunderwrite.db` as JSON payloads. Storing raw Pydantic v2 instances causes `TypeError: Object of type LabAnalyteRecord is not JSON serializable` and breaks existing dictionary subscripting (`item.get(...)`).
*   **AI Suggestion:** PROPOSE FIX
*   **Justification:** State channels must hold primitive Python types (`list[dict[str, Any]]`). Pydantic models should validate inputs at domain service boundaries and serialize via `.model_dump()` prior to state assignment.
*   **Proposed Edit:**
    *   Location: Target File 1 (`backend/app/models/state.py`)
    *   Change: Explicitly specify: *"Pydantic v2 schemas (`FamilyHistoryRecord`, `OccupationHazardRecord`, `MedicationVerificationItem`, `PEDWaitingPeriod`, `LabAnalyteRecord`) are used for domain validation. `UnderwritingState` channels store primitive serialized dictionaries (`list[dict[str, Any]]`) via `.model_dump()`, ensuring zero serialization errors in SQLite checkpointers."*

---

### 2. Undefined LangGraph Routing Map for Tiers 0–3 [`egm-implementation-readiness`] - Severity: 🔴 Blocker
*   **Affected Scope:** [Lines 381–387](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L381-L387) (`orchestrator/graph.py`)
*   **Discrepancy Description:** The design mandates branching across Tiers 0–3, but `graph.py` nodes only include `human_review` and `finalize`. It is ambiguous whether new nodes are required or if Tiers 1–3 all route to `human_review`.
*   **AI Suggestion:** PROPOSE FIX
*   **Justification:** Defining the exact conditional edge dictionary removes implementer guesswork and avoids graph compilation errors.
*   **Proposed Edit:**
    *   Location: Target File 11 (`backend/app/orchestrator/graph.py`)
    *   Change: Specify the exact edge mapping:
        ```python
        {"tier_0": "finalize", "tier_1": "human_review", "tier_2": "human_review", "tier_3": "human_review", "rescore": "agent2_risk"}
        ```
        Document that `human_review_node` mutates `state["human_review_status"]` and `state["decision_level"]` based on `state["review_tier"]`.

---

### 3. Scale Incompatibility: Debits ($137.75$) vs. $0–100$ Score Engine [`egm-implementation-readiness`] - Severity: 🔴 Blocker
*   **Affected Scope:** [Lines 331–340, 350–356](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L331-L356) (`medical_synergy.py`, `agent2_risk.py`)
*   **Discrepancy Description:** Comorbidity copula calculates Extra Mortality debits ($EM = 100 + 137.75 = 237.75\%$). If assigned directly to `medical_risk_score`, it overflows the $0–100$ scale and permanently trips the $80.0/70.0$ review thresholds.
*   **AI Suggestion:** PROPOSE FIX
*   **Justification:** Actuarial extra mortality and normalized platform risk scores serve different purposes (pricing loading vs. review gating) and must be maintained in distinct channels.
*   **Proposed Edit:**
    *   Location: Target Files 5 & 7 (`medical_synergy.py`, `agent2_risk.py`)
    *   Change: Define two distinct channels: `extra_mortality_percentage` / `actuarial_debits` (unbounded float used strictly for premium loading) and `medical_risk_score` / `overall_risk_score` (calibrated $0–100$ scale: $\text{Risk} = \min(100.0, \frac{\text{Debits}}{2})$), ensuring review gates evaluate calibrated risk scores.

---

### 4. Circular Call Order in Agent 2 [`egm-implementation-readiness`] - Severity: 🔴 Blocker
*   **Affected Scope:** [Lines 324–329, 350–360](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L324-L360) (`agent2_risk.py`, `fraud.py`)
*   **Discrepancy Description:** In `agent2_risk.py`, `assess_fraud()` is called *before* `_calculate_risk()`. If `_calculate_risk` calls `reverse_pharmacotherapy.py`, `fraud.py` cannot consume its output.
*   **AI Suggestion:** PROPOSE FIX
*   **Justification:** Ordering `reverse_pharmacotherapy.verify_medications()` before `assess_fraud()` ensures discrepancy scoring has verified drug indications.
*   **Proposed Edit:**
    *   Location: Target File 7 (`agent2_risk.py`)
    *   Change: Mandate that `RiskAssessmentAgent.run()` invokes `reverse_pharmacotherapy.verify_medications(prescriptions, declared_conditions, sex)` at step 1, attaching `verified_medications` to `features` *before* invoking `assess_fraud()`.

---

### 5. Missing Target File: `backend/app/services/intake.py` [`egm-implementation-readiness`] - Severity: 🔴 Blocker
*   **Affected Scope:** [Lines 388–394](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L388-L394) (`frontend/live_intake.py`)
*   **Discrepancy Description:** Adding family history and occupation fields to `live_intake.py` without updating `backend/app/services/intake.py` causes the submitted form data to be silently dropped during session deserialization.
*   **AI Suggestion:** PROPOSE FIX
*   **Justification:** `intake.py` is the translation layer between the HTTP session form and the LangGraph initial profile.
*   **Proposed Edit:**
    *   Location: Add Target File 14: `backend/app/services/intake.py` (Modify)
    *   Change: Update `to_profile_submission()` and `case_from_session()` to extract `family_history` and `occupation` from `form` and assign them to `applicant_profile`.

---

### 6. Synchronous RAG Blocked by Async LLM Fallback [`egm-implementation-readiness`] - Severity: 🟡 Major
*   **Affected Scope:** [Lines 342–349](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L342-L349) (`rag/structured.py`)
*   **Discrepancy Description:** `parse_pdf()` in `structured.py` is synchronous. Calling async LLM fallback with `asyncio.run()` in FastAPI raises `RuntimeError: This event loop is already running`, and per-page calls exceed `cost_guard` token budgets.
*   **AI Suggestion:** PROPOSE FIX
*   **Proposed Edit:**
    *   Location: Target File 6 (`backend/app/rag/structured.py`)
    *   Change: Specify that `extract_unstructured_clinical_notes_llm` uses a thread pool executor with a 10s timeout, and processes all narrative text in a single batched document prompt rather than per-page calls.

---

### 7. Regression Risk on Existing Review Gate Tests [`egm-implementation-readiness`] - Severity: 🟡 Major
*   **Affected Scope:** [Lines 371–380](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L371-L380) (`review_gate.py`)
*   **Discrepancy Description:** Replacing `review_level` and `requires_human_review` in `evaluate_review_gate()` will immediately break existing assertions in `backend/tests/test_review_gate.py`.
*   **AI Suggestion:** PROPOSE FIX
*   **Proposed Edit:**
    *   Location: Target File 10 (`backend/app/services/review_gate.py`)
    *   Change: Maintain backward compatibility aliases: return `review_level` alongside `review_tier` (`Tier 0` $\rightarrow$ `"straight_through"`, `Tier 1` $\rightarrow$ `"assisted_review"`, `Tiers 2-3` $\rightarrow$ `"full_review"`), and retain `requires_human_review: bool`.

---

### 8. Unspecified JSON Schemas for Actuarial Reference Data [`egm-implementation-readiness`] - Severity: 🟡 Major
*   **Affected Scope:** [Lines 310–323](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L310-L323) (`ialm_mortality_table.json`, `medication_inference_map.json`)
*   **Discrepancy Description:** Omitting the exact JSON structure forces the implementer to invent ad-hoc schemas that may fail during deserialization.
*   **AI Suggestion:** PROPOSE FIX
*   **Proposed Edit:**
    *   Location: Target Files 2 & 3
    *   Change: Provide exact schemas:
        *   `ialm_mortality_table.json`: `{"male": {"18": 0.00089, ...}, "female": {"18": 0.00075, ...}}`
        *   `medication_inference_map.json`: `{"generic_name": {"icd10_code": str, "clinical_group": str, "context_required": bool, "default_severity": str}}`

---

### 9. Undefined Mechanism for MAR Personas to Override `review_tier` [`egm-implementation-readiness`] - Severity: 🟡 Major
*   **Affected Scope:** [Lines 364–370](file:///c:/Capstone_Proj/Med_Underwriter/docs/designs/enterprise_underwriting_engine.md#L364-L370) (`llm_critic.py`, `mar_personas.py`)
*   **Discrepancy Description:** The design states that personas emit `advisory_finding` to adjust the review tier, but does not define the schema or the ingestion mechanism in `review_gate.py`.
*   **AI Suggestion:** PROPOSE FIX
*   **Proposed Edit:**
    *   Location: Target File 9 & 10
    *   Change: Define the schema: `{"finding": str, "source": str, "tier_override": "tier_2" | "tier_3" | None}`. Specify that `evaluate_review_gate()` checks `state["reflection_findings"]` and elevates `review_tier` if a valid `tier_override` is present.

---

### 10. Actuarial Boundary Handling, Identifiers, & Session Defaults [`egm-implementation-readiness`] - Severity: 🟢 Nit
*   **Affected Scope:** Lines 310–394 (Files 2, 5, 12)
*   **Discrepancy Description:** Ages $<18$ and $>75$ need explicit handling; naming of medical identifiers should be standardized; Streamlit session defaults need initialization.
*   **AI Suggestion:** PROPOSE FIX
*   **Proposed Edit:**
    *   Location: Files 2, 5, 12, and `sessions.py`
    *   Change: Document clamping for age $<18$ (age 18 rate + juvenile flag) and routing age $>75$ to Tier 3 senior escalation; standardize identifier names (`icd10_code: str`, `clinical_group: str`); add defaults to `backend/app/services/sessions.py`.
