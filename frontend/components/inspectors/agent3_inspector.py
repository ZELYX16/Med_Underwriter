"""Agent 3 MAR Reflection Verification Inspector Dialog."""
from __future__ import annotations

from typing import Any
import streamlit as st

from components.inspectors.base_inspector import render_inspector_tabs, render_json_tab


@st.dialog("06. Agent 3 MAR Reflection & Constitutional AI Verification", width="large")
def open_agent3_inspector(case: dict[str, Any]) -> None:
    """Inspector for Stage 6: Agent 3 Multi-Agent Reflection & Constitutional Debate."""
    findings = case.get("reflection_findings") or []
    metrics = case.get("agent3_metrics") or {}
    round_num = case.get("reflection_round", 0)
    consensus = case.get("reflection_consensus", True)
    verdict = case.get("reflection_verdict") or ("pass" if consensus else "concern")

    st.caption("Verifying Multi-Persona Adversarial Debate (Medical, Actuarial, Compliance) & Constitutional Gating")

    tab_summary, tab_mechanics, tab_json = render_inspector_tabs(
        summary_title="Reflection Verdict & Consensus",
        mechanics_title="Persona Critiques & Directives",
        json_title="Agent 3 State JSON",
    )

    with tab_summary:
        st.markdown("### MAR Debate Outcome")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Debate Verdict", str(verdict).upper())
        with col2:
            st.metric("Consensus Reached", "YES" if consensus else "NO")
        with col3:
            st.metric("Reflection Rounds", f"Round {round_num}")

        st.markdown("---")
        if verdict == "pass":
            st.success("✓ MAR Personas reached unanimous consensus with no material objections to Agent 2 rating.")
        else:
            st.warning("⚠️ Critical concerns raised during debate. Rescore or human escalation mandated.")

    with tab_mechanics:
        st.markdown("### Persona Findings & Objections")
        if findings:
            for item in findings:
                persona = item.get("persona", "Reviewer").title()
                p_verdict = item.get("verdict", "pass").upper()
                finding_text = item.get("finding") or item.get("reasoning") or item.get("concern") or "No concerns noted."
                
                with st.expander(f"🩺 {persona} Persona Critique — {p_verdict}", expanded=True):
                    st.write(finding_text)
                    directives = item.get("rescore_directives") or []
                    if directives:
                        st.caption(f"**Rescore Directives:** {', '.join(directives)}")
        else:
            st.info("No adversarial objections logged. Reflection concluded with clean consensus.")

    with tab_json:
        render_json_tab({
            "reflection_findings": findings,
            "agent3_metrics": metrics,
            "reflection_round": round_num,
            "reflection_consensus": consensus,
        }, title="Agent 3 State")
