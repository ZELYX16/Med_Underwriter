"""Agent 2 Risk & Actuarial Rating Verification Inspector Dialog."""
from __future__ import annotations

from typing import Any
import streamlit as st

from components.design_system import formula_callout, metric_surface
from components.inspectors.base_inspector import render_inspector_tabs, render_json_tab


@st.dialog("04. Agent 2 Risk Engine & Actuarial Rating Verification", width="large")
def open_agent2_inspector(case: dict[str, Any]) -> None:
    """Inspector for Stage 4: Agent 2 Risk Assessment, Actuarial Mortality & Copula Synergy."""
    risk_assessment = case.get("risk_assessment") or {}
    copula = case.get("copula_synergy_details") or risk_assessment.get("actuarial_rating", {}).get("copula_synergy", {})
    pricing = case.get("pricing_result") or risk_assessment.get("pricing", {})
    medications = case.get("medication_records") or risk_assessment.get("reverse_pharmacotherapy", {}).get("records", [])
    ped_periods = case.get("ped_waiting_periods") or risk_assessment.get("ped_waiting_periods", [])
    
    actuarial = risk_assessment.get("actuarial_rating") or {}
    base_debits = actuarial.get("base_debits", 0)
    synergy_multiplier = copula.get("synergy_multiplier", copula.get("multiplier", 1.0))
    emp = actuarial.get("extra_mortality_percentage", 0.0)
    loading_pct = actuarial.get("final_loading_percentage", pricing.get("loading_percentage", 0.0))
    base_premium = pricing.get("base_premium") or pricing.get("calculated_premium") or 0.0

    st.caption("Verifying Deterministic Actuarial Calculations, Comorbidity Synergies & Pharmacotherapy Cross-Validation")

    tab_summary, tab_mechanics, tab_json = render_inspector_tabs(
        summary_title="Actuarial Summary & Rating",
        mechanics_title="Formulas, Synergies & Pharmacotherapy",
        json_title="Agent 2 State JSON",
    )

    with tab_summary:
        st.markdown("### Actuarial Pricing & Loading Breakdown")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_surface("Base Debits", f"+{base_debits}", unit="debits", help_text="Sum of individual condition clinical debits")
        with col2:
            metric_surface("Copula Synergy (Φ)", f"{float(synergy_multiplier):.2f}x", unit="multiplier", help_text="Multivariate Clayton Copula comorbidity interaction")
        with col3:
            metric_surface("Extra Mortality (EMP)", f"{float(emp):.1f}%", unit="loading", help_text="EMP = Base Debits × Synergy Multiplier")
        with col4:
            metric_surface("Final Premium Loading", f"+{float(loading_pct):.1f}%", unit="premium", help_text="Actuarial premium loading percentage applied to policy")

        st.markdown("---")
        formula_callout(
            r"EMP = \sum(\text{Condition Debits}) \times \Phi_{\text{copula}} = "
            f"{base_debits} \\times {float(synergy_multiplier):.2f} = {float(emp):.2f}\\%",
            title="Actuarial Extra Mortality Equation",
            notes="Derived deterministically under IALM 2012–14 Ultimate mortality assumptions.",
        )

        st.markdown("### Risk Scores")
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            st.metric("Medical Risk Score", f"{float(case.get('medical_risk_score', 0)):.1f} / 100")
        with col_r2:
            st.metric("Overall Risk Score", f"{float(case.get('overall_risk_score', 0)):.1f} / 100")
        with col_r3:
            st.metric("Underwriting Recommendation", str(case.get("underwriting_decision") or "ACCEPT_WITH_LOADING").upper())

    with tab_mechanics:
        st.markdown("### 1. Reverse Pharmacotherapy (Drug-Disease Cross-Validation)")
        if medications:
            st.table(medications)
        else:
            st.info("No prescription medications recorded for reverse pharmacotherapy checking.")

        st.markdown("---")
        st.markdown("### 2. Multivariate Copula Synergy Comorbidity Matrix")
        synergies_detected = copula.get("synergies_detected") or copula.get("active_synergies") or []
        if synergies_detected:
            for syn in synergies_detected:
                st.write(f"- ⚡ **{syn.get('name', 'Synergy')}:** Multiplier `+{syn.get('multiplier', 1.0)}x` · *{syn.get('description', '')}*")
        else:
            st.caption("No multivariate syndromic comorbidities detected. Linear multiplier Φ = 1.00 applied.")

        st.markdown("---")
        st.markdown("### 3. Pre-Existing Disease (PED) Waiting Periods & Exclusions (IRDAI 2024)")
        if ped_periods:
            st.table(ped_periods)
        else:
            st.caption("Standard statutory waiting periods apply.")

    with tab_json:
        render_json_tab({
            "risk_assessment": risk_assessment,
            "copula_synergy_details": copula,
            "pricing_result": pricing,
            "medication_records": medications,
            "ped_waiting_periods": ped_periods,
        }, title="Agent 2 Risk & Actuarial State")
