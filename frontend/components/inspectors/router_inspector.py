"""Complexity Router Verification Inspector Dialog."""
from __future__ import annotations

from typing import Any
import streamlit as st

from components.inspectors.base_inspector import render_inspector_tabs, render_json_tab


@st.dialog("03. Complexity Router Verification", width="large")
def open_router_inspector(case: dict[str, Any]) -> None:
    """Inspector for Stage 3: Complexity Routing Strategy."""
    routing = case.get("routing_result") or {}
    complexity = routing.get("complexity") or "standard"
    strategy = routing.get("strategy") or "linear"
    reasons = routing.get("reasons") or routing.get("routing_reasons") or []

    st.caption("Verifying Triage Level & Multi-Morbidity Routing Heuristics")

    tab_summary, tab_mechanics, tab_json = render_inspector_tabs(
        summary_title="Routing Decision",
        mechanics_title="Trigger Criteria & Score",
        json_title="Router State JSON",
    )

    with tab_summary:
        st.markdown("### Complexity Classification")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Assigned Complexity", str(complexity).upper())
        with col2:
            st.metric("Downstream Strategy", str(strategy).upper())
        with col3:
            st.metric("Multi-Morbidity Flag", "TRUE" if complexity.lower() == "complex" else "FALSE")

        st.markdown("---")
        st.markdown("### Decision Rationale")
        if reasons:
            for r in reasons:
                st.write(f"- 🧭 **{r}**")
        else:
            st.info("Standard risk routing: Single-condition or low-complexity applicant.")

    with tab_mechanics:
        st.markdown("### Rule Criteria Evaluation")
        st.write(f"- **High Sum Insured Rule (> ₹25L):** {'TRIGGERED' if 'sum_insured' in str(reasons).lower() else 'Not Triggered'}")
        st.write(f"- **Multi-Condition Synergies (> 1 condition):** {'TRIGGERED' if 'multiple' in str(reasons).lower() or complexity.lower() == 'complex' else 'Not Triggered'}")
        st.write(f"- **Critical Disease History:** {'TRIGGERED' if 'critical' in str(reasons).lower() else 'Not Triggered'}")

    with tab_json:
        render_json_tab({"routing_result": routing}, title="Complexity Router State")
