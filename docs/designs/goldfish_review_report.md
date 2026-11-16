# Goldfish Annotated Review Report

**Target:** `docs/designs/frontend_modernization.md` (lines 256–304)

## Prioritized Findings & AI Suggestions

### [Issue 1] [egm-implementation-readiness] - Severity: Blocker
*   **Affected Scope:** [Lines 201–209, 261–262](docs/designs/frontend_modernization.md#L201-L209) (Target File 1: `backend/app/api/routes.py`)
*   **Discrepancy Description:** `state_store.get_case_document()` takes only 1 argument (`document_id`), not 2 (`case_id, document_id`), causing an immediate runtime `TypeError`. Furthermore, document ownership is not verified, creating a horizontal IDOR vulnerability where an attacker can access documents from another case.
*   **Rationale:** `StateStore.get_case_document(document_id: str)` in `backend/app/store/state_store.py#L934` does not take `case_id`. Without checking `doc.get("case_id") == case_id`, confidential documents leak across cases.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Essential runtime fix and data privacy security control.
*   ***Proposed Edit:***
    *   Location: Lines 198–209 and Phase 1 (Target File 1)
    *   Change: Update the endpoint implementation to call `state_store.get_case_document(document_id)` and verify `doc.get("case_id") == case_id`:
        ```python
        @router.get("/case/{case_id}/documents/{document_id}/content")
        async def get_case_document_content(case_id: str, document_id: str):
            doc = state_store.get_case_document(document_id)
            if not doc or str(doc.get("case_id")) != case_id or not doc.get("file_path"):
                raise HTTPException(status_code=404, detail="Document not found for this application.")
            file_path = Path(doc["file_path"]).resolve()
            storage_root = (settings.synthetic_data_directory / "uploads").resolve()
            if not file_path.is_relative_to(storage_root) or not file_path.exists():
                raise HTTPException(status_code=404, detail="Physical document file missing or inaccessible.")
            media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
            return FileResponse(path=file_path, media_type=media_type, filename=file_path.name)
        ```

### [Issue 2] [egm-implementation-readiness] - Severity: Blocker
*   **Affected Scope:** [Lines 205–207, 262](docs/designs/frontend_modernization.md#L205-L207) (Target File 1: `backend/app/api/routes.py`)
*   **Discrepancy Description:** Merely checking `file_path.exists()` does not prevent directory traversal if relative path sequences (`../../`) or paths outside the uploads directory are passed.
*   **Rationale:** Standard path traversal defense requires resolving the path and checking that it is strictly relative to the authorized storage root directory.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Essential security protection against arbitrary file read.
*   ***Proposed Edit:***
    *   Location: Phase 1 (Target File 1)
    *   Change: Mandate canonical root containment check: `file_path.resolve().is_relative_to(storage_root.resolve())`.

### [Issue 3] [egm-implementation-readiness] - Severity: Blocker
*   **Affected Scope:** [Lines 270–280](docs/designs/frontend_modernization.md#L270-L280) (Target Files 5, 6, 7, 16 vs existing `frontend/components.py`)
*   **Discrepancy Description:** Creating a directory `frontend/components/` shadows the existing 2,243-line module `frontend/components.py`, breaking all existing imports in `frontend/app.py` (`from components import ...`).
*   **Rationale:** Python's module import resolution prioritizes a directory containing `__init__.py` over a same-named `.py` file in the same directory.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Critical namespace collision that would prevent `frontend/app.py` from starting.
*   ***Proposed Edit:***
    *   Location: Phase 2 (Target File 4 & 5)
    *   Change: Explicitly specify the package migration strategy:
        1. Move existing `frontend/components.py` to `frontend/components/legacy_components.py`.
        2. In `frontend/components/__init__.py`, re-export all symbols from `legacy_components.py` (`from .legacy_components import *`) so existing imports throughout `frontend/app.py` remain 100% backward compatible without breaking.
        3. Place new modernization submodules (`design_system.py`, `document_viewer.py`, `graph_visualizer.py`, and `inspectors/`) alongside it within `frontend/components/`.

### [Issue 4] [egm-implementation-readiness] - Severity: Blocker
*   **Affected Scope:** [Lines 79, 284](docs/designs/frontend_modernization.md#L79) (Target File 6 & 9)
*   **Discrepancy Description:** `intake_inspector` (`@st.dialog`) renders `[📄 View Document]` buttons which launch `document_viewer` (also an `@st.dialog`). Streamlit 1.34+ does not support nested dialogs and raises runtime errors or terminates the parent dialog.
*   **Rationale:** Nested `@st.dialog` execution is unsupported by the Streamlit execution engine.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Eliminates runtime crashes when viewing documents during intake inspection.
*   ***Proposed Edit:***
    *   Location: Section 2.2 (`intake_inspector.py`) and Phase 4 (Target File 9)
    *   Change: Specify that `intake_inspector` embeds the document viewer directly inside a dedicated sub-tab ("Document Preview") using the reusable document renderer component, avoiding nested dialog invocation. Additionally, support a standalone `@st.dialog` document viewer triggered from the top-level Evidence tab.

### [Issue 5] [egm-implementation-readiness] - Severity: Major
*   **Affected Scope:** [Lines 263–264](docs/designs/frontend_modernization.md#L263-L264) (Target File 2: `frontend/api_client.py`)
*   **Discrepancy Description:** `APIClient._request()` decodes responses as text/json, corrupting raw binary PDF streams and throwing `UnicodeDecodeError`.
*   **Rationale:** Binary document streaming requires returning raw bytes (`response.content`).
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Prevents binary stream decoding exceptions in the frontend client.
*   ***Proposed Edit:***
    *   Location: Phase 1 (Target File 2)
    *   Change: Explicitly define `get_case_document_content(case_id: str, document_id: str) -> bytes` using direct `requests.get()` returning `response.content`.

### [Issue 6] [egm-implementation-readiness] - Severity: Major
*   **Affected Scope:** [Line 276](docs/designs/frontend_modernization.md#L276) (Target File 6: `frontend/components/document_viewer.py`)
*   **Discrepancy Description:** `pymupdf` is not declared in `frontend/requirements.txt`, leading to `ModuleNotFoundError: No module named 'fitz'` when the image fallback runs.
*   **Rationale:** Dependencies used by frontend components must be declared in the frontend environment requirements.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Ensures deterministic dependency installation.
*   ***Proposed Edit:***
    *   Location: Phase 3
    *   Change: Add `Target File: frontend/requirements.txt` to Phase 3, adding `pymupdf>=1.23.0`.

### [Issue 7] [egm-implementation-readiness] - Severity: Major
*   **Affected Scope:** [Lines 299–300](docs/designs/frontend_modernization.md#L299-L300) (Target File 16: `frontend/components/graph_visualizer.py`)
*   **Discrepancy Description:** The workflow trace lacks a `review_gate` node (gating is evaluated in router/finalize), and reflection rescore cycles repeat nodes (`agent2_risk`, `confidence_gate`, `agent3_reflection`), which could cause Mermaid syntax conflicts or unreadable loop webs.
*   **Rationale:** LangGraph nodes in `graph.py` are `agent1_submission`, `complexity_router`, `agent2_risk`, `confidence_gate_node`, `agent3_reflection`, `human_review`, `finalize`.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Ensures reliable Mermaid graph generation without syntax crashes on cyclic reflection loops.
*   ***Proposed Edit:***
    *   Location: Technical Plan (Section 4) and Phase 5 (Target File 16)
    *   Change: Define the Mermaid graph contract:
        - Generate a static 7-stage topology graph with dynamic CSS class assignments (`class node_id traversed; class node_id bypassed;`).
        - Map actual LangGraph node names (`agent1_submission`, `complexity_router`, `agent2_risk`, `confidence_gate_node`, `agent3_reflection`, `human_review`, `finalize`) to visual display labels.
        - Handle reflection loops by collapsing repeat passes into a loopback edge with a rescore round counter badge (`Rescore Round N`).

### [Issue 8] [egm-implementation-readiness] - Severity: Major
*   **Affected Scope:** [Lines 265, 303](docs/designs/frontend_modernization.md#L265) (Target Files 3 & 18: Test specifications)
*   **Discrepancy Description:** Test file rationales lack explicit enumeration of edge case test methods (directory traversal payloads, cross-case IDOR validation, binary stream integrity, Mermaid special character escaping).
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Guarantees complete unit test coverage.
*   ***Proposed Edit:***
    *   Location: Phase 1 (Target File 3) & Phase 5 (Target File 18)
    *   Change: Enumerate specific test cases: `test_document_content_streaming_success`, `test_document_content_idor_cross_case_denied`, `test_document_content_traversal_blocked`, `test_document_content_missing_404`, `test_mermaid_graph_traversal_mapping`, `test_mermaid_graph_rescore_loop_handling`, `test_mermaid_edge_condition_escaping`.

### [Issue 9] [egm-implementation-readiness] - Severity: Nit
*   **Affected Scope:** [Lines 280–296](docs/designs/frontend_modernization.md#L280-L296) (Target Files 9..15: Inspector state slicing)
*   **Discrepancy Description:** Missing exact state slicing JSON paths for inspector tabs.
*   ***AI Suggestion:*** PROPOSE FIX
*   ***Justification:*** Speeds up implementation and eliminates KeyError risks.
*   ***Proposed Edit:***
    *   Location: Phase 4
    *   Change: Add exact state key paths for each inspector module (`case["applicant_profile"]`, `case["agent1_enrichment"]`, `case["routing_result"]`, `case["risk_assessment"]`, `case["copula_synergy_details"]`, `case["ped_waiting_periods"]`, `case["reflection_findings"]`).
