# Stage 9: Implementation Readiness Test Audit Report

**Target Document**: `docs/designs/enterprise_underwriting_engine.md` (lines 296–416)  
**Target Repository**: `c:\Capstone_Proj\Med_Underwriter` (branch `v5.2`)  
**Auditor**: Implementation Readiness Goldfish (Technical Lead & Implementing Software Engineer)

---

### Executive Summary
The proposed implementation plan lays out a vital actuarial and clinical overhaul of the MedUnderwriter platform. However, from the perspective of an implementing engineer handed this document to write code immediately, **the plan cannot be executed as written without making fundamental, uncoordinated architectural and design decisions**. 

Critical blockers exist around:
1. LangGraph TypedDict vs. Pydantic v2 serialization and dictionary-access runtime failures;
2. Undefined LangGraph routing topology for the 4-tier decision gate;
3. Numerical Rating System scale incompatibility (debits $>100$ breaking 0–100 risk score thresholds);
4. Missing invocation contracts and circular execution order between `reverse_pharmacotherapy.py`, `fraud.py`, and `agent2_risk.py`;
5. Complete omission of `backend/app/services/intake.py` from the target file list, which causes new UI intake fields to be silently dropped.

Below is the itemized technical breakdown categorized by severity.

---

### 🔴 Blocker Findings (Runtime Failures & Unexecutable Gaps)

#### 1. Pydantic v2 vs. LangGraph `UnderwritingState` Serialization & Dict Access Conflict
* **Affected Scope**: Target File 1 (`backend/app/models/state.py`), lines 300–306 & LangGraph Checkpointer (`backend/app/orchestrator/graph.py`).
* **Technical Hurdle**:
  * `UnderwritingState` is a `TypedDict(total=False)`. Nodes update state by returning Python dictionaries.
  * In LangGraph, states are checkpointed asynchronously into SQLite (`checkpoints.db`) via `AsyncSqliteSaver`, and cases are stored into `medunderwrite.db` as JSON payloads.
  * If new state channels (`family_medical_history`, `occupation_profile`, `medication_records`, `ped_waiting_periods`, `lab_analyte_records`) store raw Pydantic v2 model instances (e.g. `list[LabAnalyteRecord]`), `json.dumps()` in SQLite state storage and API JSON responses will raise `TypeError: Object of type LabAnalyteRecord is not JSON serializable`.
  * Furthermore, existing helper functions and consumers throughout the codebase (e.g., `_review_notes`, `_structured_reasoning`, `outcome.py`) access state properties via dictionary subscripting (`item.get("analyte_name")`). Passing Pydantic instances will trigger runtime `AttributeError: 'LabAnalyteRecord' object has no attribute 'get'`.
* **Actionable Guidance**:
  The plan must explicitly define the state contract: `UnderwritingState` channels must hold serialized primitive dictionaries (`list[dict[str, Any]]`), while Pydantic v2 models are strictly used at domain service boundaries with `.model_dump()` invoked before state channel assignment, OR specify custom JSON serializers/deserializers for the LangGraph checkpointer and SQLite case store.

---

#### 2. Undefined LangGraph Edge Topology for 4-Tier Routing
* **Affected Scope**: Target File 10 & 11 (`backend/app/services/review_gate.py`, `backend/app/orchestrator/graph.py`), lines 368–384.
* **Technical Hurdle**:
  * File 11 mandates: *"Update conditional edge routing to branch across Tiers 0, 1, 2, and 3. Direct Tier 0 cases directly to `finalize` and policy schedule emission."*
  * In `graph.py` (lines 1551–1658), the compiled `StateGraph` only defines nodes: `intake`, `agent1_submission`, `complexity_router`, `agent2_risk`, `confidence_gate_node`, `agent3_reflection`, `human_review`, and `finalize`.
  * If a conditional edge router returns `"tier_0"`, `"tier_1"`, `"tier_2"`, `"tier_3"`, what nodes do they connect to?
    * Do Tiers 1, 2, and 3 all route to the existing `human_review` node with an enriched `state["review_tier"]`?
    * Or must three new LangGraph nodes (`tier1_fast_track_node`, `tier2_standard_review_node`, `tier3_senior_escalation_node`) be created?
  * If they route to new nodes, their function signatures, state mutations, and edge continuations are completely missing from the plan. If they route to `human_review`, the phrase *"branch across Tiers 0, 1, 2, and 3"* is inaccurate and leaves the conditional edge map undefined.
* **Actionable Guidance**:
  Explicitly specify the conditional edge mapping dictionary in `graph.py`:
  ```python
  graph.add_conditional_edges(
      "agent3_reflection",
      post_reflection_router,
      {
          "tier_0": "finalize",
          "tier_1": "human_review",
          "tier_2": "human_review",
          "tier_3": "human_review",
          "rescore": "agent2_risk",
      }
  )
  ```
  And document whether `human_review_node` mutates `state["human_review_status"]` and `state["decision_level"]` based on `state["review_tier"]`.

---

#### 3. Scale Incompatibility: Numerical Rating Debits ($137.75$) vs. $0–100$ Score Engine
* **Affected Scope**: Target File 5 & 7 (`backend/app/services/medical_synergy.py`, `backend/app/agents/agent2_risk.py`), lines 328–337, 347–353.
* **Technical Hurdle**:
  * `agent2_risk.py` currently bounds `medical_risk_score = min(round(medical_score, 2), 100.0)` and computes `overall_risk_score = (medical_score * 0.60) + (claims_score * 0.30) + (coverage_gap_score * 0.10)`.
  * `review_gate.py` has hardcoded thresholds: `HUMAN_REVIEW_MEDICAL_RISK_THRESHOLD = 80.0` and `HUMAN_REVIEW_OVERALL_RISK_THRESHOLD = 70.0`.
  * Under the new actuarial model in File 5, `calculate_numerical_rating` calculates Extra Mortality debits. A Metabolic Syndrome Triad generates **$137.75$ debits** (and Extra Mortality $EM = 100 + 137.75 = 237.75\%$).
  * If `agent2_risk.py` sets `state["medical_risk_score"] = 137.75`, it will overflow the $0–100$ scale, instantly triggering `HUMAN_REVIEW_MEDICAL_RISK_THRESHOLD` ($80.0$) and making automated Tier 0/Tier 1 processing impossible for any condition with debits $> 80$.
* **Actionable Guidance**:
  The plan must define the mathematical transformation between Actuarial Debits ($0–500\%+$) and the platform's normalized Risk Score ($0–100$), OR explicitly declare that `extra_mortality_percentage` and `actuarial_debits` are distinct channels from `medical_risk_score` / `overall_risk_score`, detailing which one `review_gate.py` evaluates.

---

#### 4. Circular Call Order & Undefined Call Site for `reverse_pharmacotherapy.py`
* **Affected Scope**: Target Files 4, 7, 8 (`backend/app/services/reverse_pharmacotherapy.py`, `backend/app/agents/agent2_risk.py`, `backend/app/agents/fraud.py`), lines 321–326, 347–360.
* **Technical Hurdle**:
  * In `agent2_risk.py` (`RiskAssessmentAgent.run()`, lines 54–70):
    1. `features = self._extract_features(...)`
    2. `fraud = assess_fraud(...)` (evaluates discrepancy flags and undeclared conditions)
    3. `risk = self._calculate_risk(features)` (computes medical risk)
    4. `pricing = self._calculate_pricing(...)`
  * The plan states:
    * File 7: "Refactor `_calculate_risk` and `_calculate_pricing` to delegate to `reverse_pharmacotherapy.py`."
    * File 8: "Update discrepancy scoring to consume context-aware medication verification results from `reverse_pharmacotherapy.py`."
  * **The circularity**: `fraud.py` is called *before* `_calculate_risk`. If `_calculate_risk` invokes `reverse_pharmacotherapy.py`, `fraud.py` cannot consume its output unless `reverse_pharmacotherapy.py` is called before `assess_fraud`.
  * Furthermore, `features["medications"]` is currently a raw list of strings or unstructured dictionaries. What exact schema does `verify_medications(prescriptions, declared_conditions, applicant_sex)` expect, and what does it return?
* **Actionable Guidance**:
  Specify that `reverse_pharmacotherapy.verify_medications()` must be invoked at the top of `RiskAssessmentAgent.run()` (or in `submission_facts` during Agent 1), attaching `verified_medications: list[MedicationVerificationItem]` to `features` *before* `assess_fraud()` is called. Define the function signature:
  `verify_medications(prescriptions: list[dict[str, Any]], declared_conditions: list[str], applicant_sex: str) -> list[MedicationVerificationItem]`.

---

#### 5. Missing Target File: `backend/app/services/intake.py` (Data Drop Hazard)
* **Affected Scope**: Target File 12 (`frontend/live_intake.py`), lines 385–391.
* **Technical Hurdle**:
  * File 12 proposes adding form sections for **Family Medical History** and **Occupation (ISCO-08)** in `frontend/live_intake.py`.
  * However, `frontend/live_intake.py` does not speak directly to the workflow engine; it serializes the form to `PUT /api/live/sessions/{token}`.
  * When submitted, `backend/app/api/live_routes.py` calls `backend/app/services/intake.py` (`intake.case_from_session()`), which extracts known fields into `applicant_profile` and `submission`.
  * `backend/app/services/intake.py` is **omitted from the 13 target files**. If `intake.py` is not updated to map `family_history` and `occupation` from `session["form"]` into `applicant_profile`, the data will be silently dropped before LangGraph ever initializes.
* **Actionable Guidance**:
  Add `backend/app/services/intake.py` to the implementation plan as Target File 14, specifying updates to `intake.open_items()` and `intake.case_from_session()` to map `family_history` and `occupation_hazard` into `applicant_profile`.

---

### 🟡 Major Findings (Design Ambiguities & Missing Error Handling)

#### 1. Synchronous RAG Pipeline Blocked by Async LLM Fallback in `structured.py`
* **Affected Scope**: Target File 6 (`backend/app/rag/structured.py`), lines 339–346.
* **Technical Explanation**:
  * `parse_pdf(path)` in `structured.py` (lines 549–629) is a **synchronous function** called during indexing and Agent 1 document facts generation.
  * Proposing `extract_unstructured_clinical_notes_llm(page_text)` with a 10-second timeout guard inside `structured.py` introduces LLM network I/O into a synchronous parser.
  * If implemented with `asyncio.run()` inside synchronous code running under FastAPI's async event loop, it will raise `RuntimeError: This event loop is already running`.
  * Additionally, `backend/app/services/cost_guard.py` enforces `llm_calls_per_case: 8`. If an applicant uploads a 5-page narrative report, running per-page LLM extraction will consume 5 of the 8 allowed calls in Layer 1, causing Agent 2 or Agent 3 to fail with `call budget used`.
* **Guidance**:
  1. Specify how `extract_unstructured_clinical_notes_llm` is executed (e.g. via `asyncio.to_thread` or thread pool executor with `concurrent.futures.wait(timeout=10)`).
  2. Implement a single batch prompt for the entire document rather than per-page calls to preserve the `cost_guard` budget.

#### 2. Regression Failure on Existing Test Suite via Schema Erasure in `review_gate.py`
* **Affected Scope**: Target File 10 & Existing Test Suite (`backend/tests/test_review_gate.py`).
* **Technical Explanation**:
  * File 10 refactors `evaluate_review_gate(state)` to output `review_tier` across `Tier 0` to `Tier 3`.
  * The existing test suite (`backend/tests/test_review_gate.py`, lines 22, 35, 48, 60, 73, 86) explicitly asserts:
    * `assert gate["review_level"] == "straight_through"`
    * `assert gate["review_level"] == "full_review"`
    * `assert gate["review_level"] == "assisted_review"`
    * `assert gate["requires_human_review"] is True / False`
  * If `evaluate_review_gate` replaces `review_level` with `review_tier`, or removes `requires_human_review`, existing tests in `test_review_gate.py` will immediately fail with `KeyError`.
* **Guidance**:
  Maintain backward compatibility in `evaluate_review_gate`: retain `review_level` as an alias alongside `review_tier`, and preserve the boolean `requires_human_review` (`True` for Tiers 1–3, `False` for Tier 0).

#### 3. Unspecified JSON Schemas for Actuarial Reference Files
* **Affected Scope**: Target Files 2 & 3 (`backend/app/data/ialm_mortality_table.json`, `backend/app/data/medication_inference_map.json`), lines 307–320.
* **Technical Explanation**:
  * Neither file has an explicit JSON schema provided.
  * For `ialm_mortality_table.json`: Is it nested by gender then age (`{"male": {"18": 0.00089}, "female": {...}}`) or a list of objects (`[{"age": 18, "male": 0.00089, "female": 0.00075}]`)?
  * For `medication_inference_map.json`: How are dosage strengths, brand-to-generic mappings, and multiple ICD-10 codes keyed?
* **Guidance**:
  Provide the canonical JSON structure in the document so the implementer does not invent an ad-hoc dictionary schema that fails during deserialization in `reverse_pharmacotherapy.py` and `medical_synergy.py`.

#### 4. Missing Implementation Mechanism for MAR Personas to Adjust `review_tier`
* **Affected Scope**: Target File 9 (`backend/app/agents/reflection/llm_critic.py`, `mar_personas.py`), lines 361–367.
* **Technical Explanation**:
  * File 9 states: *"Restrain personas from modifying mathematical risk scores; any verified contradiction emits an `advisory_finding` adjusting review tier."*
  * However, personas in `mar_personas.py` return `outputs[persona]["concerns"]` and a boolean `requires_rescore`.
  * There is no existing channel or mechanism for an `advisory_finding` to directly alter the `review_tier` computed by `review_gate.py`. Does it emit a flag string added to `mandatory_review_reasons`? Does it set `target_tier: "tier_2"`?
* **Guidance**:
  Define the schema of `advisory_finding`:
  `{"finding": str, "source": str, "severity": "escalation" | "caution", "tier_override": "tier_2" | "tier_3" | None}`
  and document how `evaluate_review_gate()` inspects `state["reflection_findings"]` to apply this override.

---

### 🟢 Nit Findings (Minor Naming & Documentation Polish)

1. **IALM Mortality Table Boundary Handling (Ages $<18$ and $>75$)**:
   * *Scope*: File 2 & 5 (`ialm_mortality_table.json`, `medical_synergy.py`).
   * *Finding*: The table covers ages 18–75. The design does not specify fallback behavior for juvenile applications (age $<18$) or senior applications (age $>75$).
   * *Guidance*: Explicitly document clamping or routing: ages $<18$ clamp to age 18 rate with mandatory juvenile rider flag; ages $>75$ automatically route to Tier 3 Senior Escalation / Decline.

2. **Inconsistent Naming of Medical Identifiers**:
   * *Scope*: File 1 (`models/state.py`) vs File 6 (`rag/structured.py`).
   * *Finding*: `FamilyHistoryRecord` uses `condition_code`, `MedicationVerificationItem` uses `inferred_conditions`, while `diagnoses` in `structured.py` uses `icd` and `group`.
   * *Guidance*: Standardize terminology across models: specify ICD-10 code as `icd10_code: str` and diagnostic category as `clinical_group: str`.

3. **Streamlit UI Version Keying (`frontend/live_intake.py`)**:
   * *Scope*: File 12 (`frontend/live_intake.py`).
   * *Finding*: Streamlit inputs in `live_intake.py` use `f"live_..._{ver}"` keys. Adding new fields without registering their defaults in `intake.py`'s `DEFAULT_FORM` causes session reload flickers.
   * *Guidance*: Add the new field defaults (`family_history: []`, `occupation: "desk"`) to `backend/app/services/sessions.py` default session state.

---

### Implementation Readiness Verdict

| Audit Dimension | Status | Notes |
|---|---|---|
| **Actionability** | ⚠️ **Conditional** | High-level intent is clear, but critical data flow, call sequences, and signatures are missing. |
| **State Compatibility** | 🔴 **Fail** | Pydantic v2 objects directly in `UnderwritingState` will break SQLite checkpointing and dict lookups. |
| **Pipeline Integration** | 🔴 **Fail** | Missing `intake.py` target; circular invocation order between `reverse_pharmacotherapy`, `fraud`, and `agent2_risk`. |
| **Actuarial Calibration** | 🔴 **Fail** | Numerical Rating debits ($>100$) will trigger hardcoded 80.0/70.0 review gate tripwires. |
| **Regression Safety** | 🟡 **At Risk** | `test_review_gate.py` and `test_structured.py` will break without backward compatibility aliases. |

**Tech Lead Recommendation**:
Halt implementation until the 5 Blocker items are addressed in `docs/designs/enterprise_underwriting_engine.md`. Specifically:
1. Define channel serialization rules for `UnderwritingState`;
2. Add `backend/app/services/intake.py` as Target File 14;
3. Fix the execution order in `agent2_risk.py` so `reverse_pharmacotherapy` runs before `fraud.py`;
4. Provide the exact LangGraph conditional edge routing map for Tiers 0–3;
5. Define the scale mapping between Actuarial Debits and normalized Risk Scores.
