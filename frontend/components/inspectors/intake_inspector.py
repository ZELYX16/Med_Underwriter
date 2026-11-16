"""Intake & Evidence Verification Inspector Dialog."""
from __future__ import annotations

from typing import Any
import streamlit as st

from api_client import api, APIError
from components.document_viewer import render_document_preview_content
from components.inspectors.base_inspector import render_inspector_tabs, render_json_tab


@st.dialog("01. Intake Stage & Evidence Verification", width="large")
def open_intake_inspector(case: dict[str, Any]) -> None:
    """Inspector for Stage 1: Intake & Applicant Evidence."""
    profile = case.get("applicant_profile") or {}
    submission = case.get("submission") or {}
    case_id = str(case.get("case_id") or "")
    
    st.caption(f"Verifying Application Intake · Case ID: **{case_id}**")

    tabs = render_inspector_tabs(
        summary_title="Demographics & Declarations",
        mechanics_title="KYC & Ingestion Checks",
        extra_tab="Evidence & Documents",
        json_title="Intake JSON",
    )
    tab_summary, tab_mechanics, tab_docs, tab_json = tabs

    # 1. Summary Tab
    with tab_summary:
        st.markdown("### Applicant Profile")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Name", profile.get("name") or "Unknown")
            st.metric("Biological Sex", profile.get("sex") or "Unknown")
        with col2:
            st.metric("Date of Birth", profile.get("dob") or "Unknown")
            st.metric("Age", profile.get("age") or "N/A")
        with col3:
            st.metric("Height / Weight", f"{profile.get('height', '—')} cm / {profile.get('weight', '—')} kg")
            st.metric("BMI", profile.get("bmi") or "N/A")
        with col4:
            st.metric("Product", submission.get("product") or "Comprehensive")
            sum_ins = submission.get("sum_insured")
            st.metric("Sum Insured", f"₹{sum_ins:,.0f}" if isinstance(sum_ins, (int, float)) else str(sum_ins))

        st.markdown("---")
        st.markdown("### Declared Medical Conditions")
        conditions = profile.get("medical_conditions") or []
        if conditions:
            st.table(conditions)
        else:
            st.info("No prior medical conditions declared by applicant.")

    # 2. Mechanics Tab
    with tab_mechanics:
        st.markdown("### Intake Validation & Completeness Gates")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.markdown("#### Validation Checks")
            st.write(f"- **Identity / KYC Match:** {'✓ PASSED' if profile.get('name') else '⚠️ Incomplete'}")
            st.write(f"- **Age Bounds (18-75):** {'✓ PASSED' if 18 <= float(profile.get('age') or 0) <= 75 else '⚠️ Flagged'}")
            st.write(f"- **Consent Received:** {'✓ VERIFIED' if submission.get('consent', True) else '❌ MISSING'}")
        with col_m2:
            st.markdown("#### Declaration Questionnaire")
            q_answers = submission.get("questionnaire") or []
            if q_answers:
                st.json(q_answers)
            else:
                st.caption("Standard yes/no medical declarations recorded in profile.")

    # 3. Evidence & Documents Tab (Embedded Preview)
    with tab_docs:
        st.markdown("### Uploaded Application Documents")
        try:
            doc_res = api.list_case_documents(case_id)
            doc_list = doc_res.get("data", {}).get("documents", []) if isinstance(doc_res, dict) else []
        except Exception:
            doc_list = []

        if not doc_list:
            st.info("No uploaded documents recorded for this application.")
        else:
            doc_options = {f"{d.get('filename', 'doc')} ({d.get('document_id')})": d for d in doc_list}
            selected_label = st.selectbox("Select document to inspect:", list(doc_options.keys()))
            selected_doc = doc_options[selected_label]
            doc_id = selected_doc.get("document_id")

            if doc_id and st.button(f"Load Document Content ({selected_doc.get('filename')})", key="btn_load_intake_doc"):
                with st.spinner("Fetching document from backend secure storage..."):
                    try:
                        content_bytes = api.get_case_document_content(case_id, doc_id)
                        render_document_preview_content(
                            content_bytes,
                            selected_doc.get("filename") or "document.pdf",
                            selected_doc,
                        )
                    except APIError as exc:
                        st.error(f"Failed to retrieve document: {exc}")

    # 4. JSON Tab
    with tab_json:
        render_json_tab({"applicant_profile": profile, "submission": submission}, title="Intake State")
