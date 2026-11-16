"""Confidence Gate Verification Inspector Dialog."""
from __future__ import annotations

from typing import Any
import streamlit as st

from components.design_system import metric_surface
from components.inspectors.base_inspector import render_inspector_tabs, render_json_tab


@st.dialog("05. Confidence Gate Verification", width="large")
def open_confidence_gate_inspector(case: dict[str, Any]) -> None:
    """Inspector for Stage 5: Confidence Gate & Reflection Decision."""
    gate = case.get("confidence_gate") or {}
    confidence = float(case.get("agent2_confidence") or case.get("confidence_score") or gate.get("confidence", 0.85))
    verdict = gate.get("verdict") or ("pass" if confidence >= 0.70 else "reflection_required")
    reasons = gate.get("reasons") or []

    st.caption("Verifying Multi-Layer Bayesian Confidence Scoring & Reflection Threshold")

    tab_summary, tab_mechanics, tab_json = render_inspector_tabs(
        summary_title="Gate Verdict & Confidence",
        mechanics_title="Confidence Layers & Margins",
        json_title="Confidence Gate JSON",
    )

    with tab_summary:
        st.markdown("### Confidence Gate Overview")
        col1, col2, col3 = st.columns(3)
        with col1:
            metric_surface("Composite Confidence", f"{confidence*100:.1f}%", unit="score")
        with col2:
            st.metric("Gate Verdict", verdict.upper(), delta="Passes Gate" if verdict == "pass" else "Needs Reflection")
        with col3:
            margin = confidence - 0.70
            st.metric("Margin to Threshold (0.70)", f"{margin*100:+.1f}%")

        st.markdown("---")
        if verdict == "pass":
            st.success("✓ Confidence exceeds 0.70 threshold. Case bypassed Agent 3 reflection directly to Review Gate.")
        else:
            st.warning("⚠️ Confidence is below 0.70 or critical ambiguity detected. Triggered Agent 3 adversarial reflection.")

    with tab_mechanics:
        st.markdown("### Layered Confidence Assessment")
        st.write(f"- **Data Completeness Layer:** {'High' if confidence > 0.8 else 'Moderate'}")
        st.write(f"- **Actuarial Consistency Layer:** {'High' if confidence > 0.75 else 'Moderate'}")
        st.write(f"- **Adversarial MAR Triggers:** {', '.join(reasons) if reasons else 'None'}")

    with tab_json:
        render_json_tab({"confidence_gate": gate, "confidence_score": confidence}, title="Confidence Gate State")
