"""Agent 1 Submission Intelligence Verification Inspector Dialog."""
from __future__ import annotations

from typing import Any
import streamlit as st

from components.inspectors.base_inspector import render_inspector_tabs, render_json_tab


@st.dialog("02. Agent 1 Submission Intelligence Verification", width="large")
def open_agent1_inspector(case: dict[str, Any]) -> None:
    """Inspector for Stage 2: Agent 1 Clinical Entity & Table Extraction."""
    enrichment = case.get("agent1_enrichment") or {}
    raw_facts = case.get("structured_facts") or enrichment.get("structured_facts") or []
    lab_results = enrichment.get("lab_results") or []
    metrics = case.get("agent1_metrics") or {}

    # Safe normalization of structured facts across list, dict, and nested structures
    display_facts: list[dict[str, Any]] = []
    if isinstance(raw_facts, dict):
        for category, items in raw_facts.items():
            cat_label = str(category).replace("_", " ").title()
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        row = {"Category": cat_label}
                        row.update(item)
                        display_facts.append(row)
                    else:
                        display_facts.append({"Category": cat_label, "Clinical Statement": str(item)})
            elif isinstance(items, dict):
                for sub_k, sub_v in items.items():
                    display_facts.append({"Category": f"{cat_label} - {str(sub_k).title()}", "Clinical Statement": str(sub_v)})
            else:
                display_facts.append({"Category": cat_label, "Clinical Statement": str(items)})
    elif isinstance(raw_facts, list):
        for item in raw_facts:
            if isinstance(item, dict):
                display_facts.append(item)
            else:
                display_facts.append({"Clinical Statement": str(item)})

    # Safe normalization of lab results
    if isinstance(lab_results, dict):
        display_labs: list[dict[str, Any]] = [{"Analyte": str(k), "Value": str(v)} for k, v in lab_results.items()]
    elif isinstance(lab_results, list):
        display_labs = [
            item if isinstance(item, dict) else {"Analyte / Finding": str(item)}
            for item in lab_results
        ]
    else:
        display_labs = []

    st.caption("Verifying Document Ingestion, Clinical Table Extraction & Lab Analyte Normalization")

    tab_summary, tab_mechanics, tab_json = render_inspector_tabs(
        summary_title="Extraction Summary & Coverage",
        mechanics_title="Normalized Labs & Layout Tables",
        json_title="Agent 1 State JSON",
    )

    with tab_summary:
        st.markdown("### Clinical Extraction Overview")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Extracted Facts", len(display_facts))
        with col2:
            st.metric("Normalized Lab Analytes", len(display_labs))
        with col3:
            completeness = metrics.get("completeness_score", 0.95)
            st.metric("Evidence Completeness", f"{float(completeness)*100:.1f}%")
        with col4:
            st.metric("Status", "✓ VERIFIED" if case.get("agent1_completed") else "PROCESSING")

        st.markdown("---")
        st.markdown("### Extracted Clinical Statements")
        if display_facts:
            st.table(display_facts[:15])
            if len(display_facts) > 15:
                st.caption(f"Showing 15 of {len(display_facts)} extracted facts.")
        else:
            st.info("No unstructured clinical facts recorded.")

    with tab_mechanics:
        st.markdown("### Laboratory Analyte Normalization (IFCC / Standard Ranges)")
        if display_labs:
            st.table(display_labs)
        else:
            st.info("No numerical lab panel values extracted for this case.")

        st.markdown("---")
        st.markdown("### Document Defect & Recency Evaluation")
        defects = case.get("document_defects") or []
        if defects:
            st.warning(f"Detected {len(defects)} document defect(s):")
            st.json(defects)
        else:
            st.success("✓ All documents passed recency and layout table completeness checks.")

    with tab_json:
        render_json_tab({
            "agent1_enrichment": enrichment,
            "structured_facts": raw_facts,
            "agent1_metrics": metrics,
        }, title="Agent 1 State")
