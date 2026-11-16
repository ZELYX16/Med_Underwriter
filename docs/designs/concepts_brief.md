# Concepts Brief: MedUnderwriter Enterprise HealthTech Light Visual System & Runtime Hardening

*   **Author:** B_Karthikeyan
*   **Status:** Synthesized Brainstorm Brief
*   **Date:** 2026-11-16
*   **Target Branch:** `v5.2`

--------------------------------------------------------------------------------

## 1. Executive Summary

This concept hardens MedUnderwriter's Streamlit frontend (`frontend/styles.py`, `frontend/app.py`, `frontend/components/`) by resolving critical runtime defects and upgrading the UI to a modern **Enterprise HealthTech Light** design system.

The initiative resolves three specific technical failure modes:
1. `KeyError: slice(None, 15, None)` in `agent1_inspector.py` caused by unvalidated slicing of dictionary-formatted `structured_facts`.
2. Mermaid flowchart parsing failures caused by unquoted edge labels containing parentheses `(78%)`, comparison operators (`<`, `>=`), and percentages.
3. Streamlit 1.65+ deprecation warnings regarding `use_container_width=True` in favor of `width="stretch"`.

In addition to bug fixes, the visual layer is upgraded from flat generic styling to a clinical-grade design system with elevated metric cards, category icons, interactive case cards with applicant avatars, and a refined navigation sidebar.

---

## 2. Technical Bug Fixes

### Bugfix 1: Robust Slicing & Normalization in `agent1_inspector.py`
* **Problem**: In `agent1_inspector.py#L42`, `structured_facts = case.get("structured_facts") or enrichment.get("structured_facts") or []`. The backend frequently stores `structured_facts` as a dictionary mapping categories to lists or strings (e.g. `{"diagnoses": [...], "vitals": [...], "medications": [...]}`). Slicing `structured_facts[:15]` raises `KeyError: slice(None, 15, None)`.
* **Remedy**: Implement dynamic data normalization:
  ```python
  if isinstance(structured_facts, dict):
      display_facts = [
          {"Category": k.replace("_", " ").title(), "Extracted Statement": str(v)}
          for k, v in structured_facts.items()
      ]
  elif isinstance(structured_facts, list):
      display_facts = [
          item if isinstance(item, dict) else {"Extracted Statement": str(item)}
          for item in structured_facts
      ]
  else:
      display_facts = []

  if display_facts:
      st.table(display_facts[:15])
  ```

### Bugfix 2: Mermaid Grammar Quote Encapsulation in `graph_visualizer.py`
* **Problem**: Mermaid syntax treats raw parentheses `(...)` and comparison operators inside edge pipe delimiters (`-->|text|`) as syntax errors.
* **Remedy**: Wrap all edge annotations in double quotes `-->|"..."|`:
  ```python
  if is_ag3_traversed:
      lines.append(f'    N_CONF -->|"Low Confidence < 0.70 ({conf_pct})"| N_AG3')
      lines.append('    N_AG3 -->|"Consensus Reached"| N_GATE')
      if rescore_edge:
          lines.append(f'    N_AG3 -.->|"Rescore Loop (Round {rescore_round})"| N_AG2')
  else:
      lines.append(f'    N_CONF -.->|"High Confidence >= 0.70 ({conf_pct})"| N_GATE')
      lines.append('    N_CONF -.->|"Bypassed Reflection"| N_AG3')

  if is_stp_traversed:
      lines.append('    N_GATE -->|"Tier 0 (Risk < 40)"| N_STP')
      lines.append('    N_GATE -.->|"Bypassed Review"| N_REVIEW')
  elif is_declined_traversed:
      lines.append('    N_GATE -->|"Critical Risk / Fraud"| N_DECLINED')
  else:
      lines.append(f'    N_GATE -->|"Escalated (Risk {risk_disp} >= 70)"| N_REVIEW')
      lines.append('    N_GATE -.->|"Bypassed Auto-Approve"| N_STP')
  ```

### Bugfix 3: Streamlit 1.65+ Parameter Standardization
* **Problem**: Streamlit 1.65+ deprecates `use_container_width=True` on buttons, tables, and metrics.
* **Remedy**: Replace `use_container_width=True` with `width="stretch"` across `frontend/components/graph_visualizer.py`, `frontend/components/inspectors/`, and `frontend/app.py`.

---

## 3. UI/UX Design System: Enterprise HealthTech Light

### Surface Hierarchy & Color Palette
* **Canvas (`Surface 0`)**: Light clinical slate `#f8fafc`.
* **Elevated Cards (`Surface 1`)**: `#ffffff` with 1px border `#e2e8f0` and multi-layered soft drop shadows (`box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 6px -1px rgba(0,0,0,0.03)`).
* **Modal / Inspector Drawers (`Surface 2`)**: `#ffffff` with frosted backdrop and deep elevation (`box-shadow: 0 20px 25px -5px rgba(0,0,0,0.1)`).
* **Color Accents**:
  - Medical Teal (`#0891b2`) and Actuarial Cobalt (`#2563eb`) for primary interactions and active tabs.
  - Emerald (`#10b981`) for Tier 0 (Straight-Through Processing).
  - Amber (`#f59e0b`) for Tier 2 (Comprehensive Review) and Pending queue.
  - Crimson (`#ef4444`) for Tier 3 (CMO Escalation) and Declined states.

### Component Revamp Specifications

#### 1. Elevated Metric Cards (`frontend/components/design_system.py`)
Replace flat counters with rich metric cards featuring:
- Category icon badge (e.g., 📁 Total, ⏳ Pending, ⚙️ In Progress, 👤 Review, ✅ Completed).
- Color-coded top or left accent borders.
- Monospaced typography for large numeric values (`Roboto Mono`).
- Subtitle or delta context indicators.

#### 2. Interactive Case Cards (`frontend/components/design_system.py` & `frontend/app.py`)
Replace flat tabular rows in `render_case_row` with elevated card containers:
- Left: Applicant Avatar / Initials circle + Name + Application ID.
- Middle: Product badge + Sum Insured (formatted currency) + Risk score pill.
- Right: WCAG 2.1 AA Tier Status Chip + High-contrast "Underwrite / Open Case" action button.
- Micro-interaction: Subtle hover elevation (`translateY(-2px)`).

#### 3. Modern Navigation Sidebar (`frontend/styles.py`)
- Clean deep slate navigation (`#0f172a`) with subtle border separator.
- Active item indicator with 3px accent bar (`#3b82f6`) and high-contrast text.
- Clean category grouping ("WORKSPACE", "OPERATIONS").

---

## 4. Multi-Lens Goldfish Review Summary

| Lens | Assessment | Recommendation |
| :--- | :--- | :--- |
| **UX & Ergonomics** | Current dashboard lacks visual depth and clear status hierarchy. | Implement elevated cards with category icons, micro-shadows, and distinct status color coding. |
| **Codebase Details** | Slicing dictionaries causes immediate crash; Mermaid requires quotes around parentheses. | Normalize `structured_facts` dynamically and quote all Mermaid edge labels. |
| **Skeptical Architect** | Heavy custom HTML in loops could slow down Streamlit rendering on large case sets. | Keep component HTML lightweight and paginate case lists (8-12 per page). |
| **Comprehension** | Underwriters must grasp risk level and pending actions within 2 seconds. | Use semantic color mapping (green STP, blue Fast-Track, amber Review, red Escalation). |
| **Implementation** | Fixes are well-scoped across 5 files: `styles.py`, `design_system.py`, `graph_visualizer.py`, `agent1_inspector.py`, `app.py`. | Proceed directly to targeted implementation and unit testing. |
| **Structural** | Reusable card components should be centralized in `design_system.py`. | Cleanly export all new primitives via `frontend/components/__init__.py`. |
| **Inventive Catalyst** | Solves the conflict between high data density and clean modern aesthetics. | Leverage two-layer progressive disclosure: summary card $\to$ modal drill-down inspector. |

---

## 5. Implementation Roadmap

1. **Step 1: Runtime Bug Fixes**:
   - Patch `frontend/components/inspectors/agent1_inspector.py` (dictionary normalization).
   - Patch `frontend/components/graph_visualizer.py` (quote Mermaid labels + `width="stretch"`).
2. **Step 2: CSS & Design System Upgrade**:
   - Update `frontend/styles.py` with Enterprise HealthTech Light tokens, metric card styles, and sidebar styling.
   - Add `elevated_metric_card` and `render_case_card` in `frontend/components/design_system.py`.
3. **Step 3: Dashboard & Workspace Modernization**:
   - Update `render_dashboard_metrics` and `render_case_row` in `frontend/app.py` to use modern elevated cards.
4. **Step 4: Verification & Automated Tests**:
   - Run `test_graph_visualizer.py` and `test_document_content_api.py`.
   - Verify Streamlit startup without warnings or runtime errors.
   - Commit locally on branch `v5.2`.
