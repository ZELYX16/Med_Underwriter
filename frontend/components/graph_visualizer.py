"""Interactive Workflow Path Visualizer Component for MedUnderwriter."""
from __future__ import annotations

import html
from typing import Any
import streamlit as st

from components.inspectors import (
    open_intake_inspector,
    open_agent1_inspector,
    open_router_inspector,
    open_agent2_inspector,
    open_confidence_gate_inspector,
    open_agent3_inspector,
    open_review_gate_inspector,
)


def generate_mermaid_graph(case: dict[str, Any]) -> str:
    """Generate dynamic Mermaid flowchart string with traversed, bypassed, gate, and active classes."""
    trace_items = case.get("workflow_trace") or []
    
    # Extract visited node names and count repeats (for rescores)
    visited_nodes: list[str] = []
    agent2_count = 0
    for item in trace_items:
        node_name = item.get("node") if isinstance(item, dict) else str(item)
        if node_name:
            visited_nodes.append(node_name)
            if node_name == "agent2_risk":
                agent2_count += 1

    visited_set = set(visited_nodes)
    if case.get("applicant_profile") or case.get("case_id"):
        visited_set.add("intake")

    final_status = str(case.get("final_status") or case.get("status") or "").lower()
    review_tier = str(case.get("review_tier") or "Tier 2")
    overall_risk = float(case.get("overall_risk_score") or 0.0)
    confidence = float(case.get("agent2_confidence") or case.get("confidence_score") or 0.85)

    # Determine node statuses
    is_intake_traversed = "intake" in visited_set
    is_ag1_traversed = "agent1_submission" in visited_set
    is_router_traversed = "complexity_router" in visited_set
    is_ag2_traversed = "agent2_risk" in visited_set
    is_conf_traversed = "confidence_gate" in visited_set or is_ag2_traversed
    is_ag3_traversed = "agent3_reflection" in visited_set
    is_gate_traversed = "finalize" in visited_set or "human_review" in visited_set or is_ag2_traversed
    
    is_stp_traversed = final_status in {"approved", "completed", "tier 0", "stp"}
    is_review_traversed = final_status in {"human_review", "review", "tier 1", "tier 2", "tier 3", "awaiting_review", "awaiting"} or not is_stp_traversed
    is_declined_traversed = final_status in {"rejected", "declined", "failed"}

    # Rescore handling
    rescore_round = int(case.get("reflection_round") or (agent2_count - 1 if agent2_count > 1 else 0))
    rescore_edge = f"N_AG3 -.->|Rescore Loop (Round {rescore_round})| N_AG2\n" if rescore_round > 0 else ""

    # Sanitize edge condition text (avoiding <, >, & raw HTML breakages)
    conf_pct = f"{confidence * 100:.0f}%"
    risk_disp = f"{overall_risk:.1f}"

    lines = [
        "flowchart TD",
        '    N_INTAKE["01. Intake & Profile"]',
        '    N_AG1["02. Agent 1: Submission Intelligence"]',
        '    N_ROUTER{"03. Complexity Router"}',
        '    N_AG2["04. Agent 2: Actuarial Risk Engine"]',
        '    N_CONF{"05. Confidence Gate"}',
        '    N_AG3["06. Agent 3: MAR Reflection"]',
        f'    N_GATE{{"07. Review Gate & Calibrated Tiers"}}',
        '    N_STP["✓ Tier 0: Straight-Through (STP)"]',
        f'    N_REVIEW["⚠️ {review_tier}: Human Review Queue"]',
        '    N_DECLINED["🛑 Declined / Quarantine"]',
        "",
        "    N_INTAKE --> N_AG1",
        "    N_AG1 --> N_ROUTER",
        f"    N_ROUTER -->|Complexity Triage| N_AG2",
        "    N_AG2 --> N_CONF",
    ]

    if is_ag3_traversed:
        lines.append(f"    N_CONF -->|Low Confidence &lt; 0.70 ({conf_pct})| N_AG3")
        lines.append("    N_AG3 -->|Consensus Reached| N_GATE")
        if rescore_edge:
            lines.append(f"    {rescore_edge.strip()}")
    else:
        lines.append(f"    N_CONF -.->|High Confidence &gt;= 0.70 ({conf_pct})| N_GATE")
        lines.append("    N_CONF -.->|Bypassed Reflection| N_AG3")

    if is_stp_traversed:
        lines.append(f"    N_GATE -->|Tier 0 (Risk &lt; 40)| N_STP")
        lines.append(f"    N_GATE -.->|Bypassed Review| N_REVIEW")
    elif is_declined_traversed:
        lines.append(f"    N_GATE -->|Critical Risk / Fraud| N_DECLINED")
    else:
        lines.append(f"    N_GATE -->|Escalated (Risk {risk_disp} &gt;= 70)| N_REVIEW")
        lines.append(f"    N_GATE -.->|Bypassed Auto-Approve| N_STP")

    # Add classDef styles
    lines.extend([
        "",
        "    classDef traversed fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e3a8a;",
        "    classDef bypassed fill:#f8fafc,stroke:#cbd5e1,stroke-dasharray:4 4,color:#94a3b8;",
        "    classDef gate fill:#fffbeb,stroke:#d97706,stroke-width:2px,color:#92400e;",
        "    classDef active fill:#f0fdf4,stroke:#16a34a,stroke-width:2.5px,color:#14532d;",
        "",
        f"    class N_INTAKE {'traversed' if is_intake_traversed else 'bypassed'};",
        f"    class N_AG1 {'traversed' if is_ag1_traversed else 'bypassed'};",
        f"    class N_ROUTER {'gate' if is_router_traversed else 'bypassed'};",
        f"    class N_AG2 {'traversed' if is_ag2_traversed else 'bypassed'};",
        f"    class N_CONF {'gate' if is_conf_traversed else 'bypassed'};",
        f"    class N_AG3 {'traversed' if is_ag3_traversed else 'bypassed'};",
        f"    class N_GATE {'gate' if is_gate_traversed else 'bypassed'};",
        f"    class N_STP {'active' if is_stp_traversed else 'bypassed'};",
        f"    class N_REVIEW {'active' if is_review_traversed else 'bypassed'};",
        f"    class N_DECLINED {'active' if is_declined_traversed else 'bypassed'};",
    ])

    return "\n".join(lines)


@st.fragment(run_every=None)
def render_workflow_visualizer(case: dict[str, Any]) -> None:
    """Render the execution path flowchart and inspector jump pill bar inside an isolated Streamlit fragment."""
    st.markdown("### 🗺️ Case Execution Path & Decision Topology")
    st.caption("Visually trace visited nodes, bypassed branches, and branch conditions evaluated for this application.")

    mermaid_str = generate_mermaid_graph(case)
    st.markdown(f"```mermaid\n{mermaid_str}\n```")

    st.markdown("##### 🔎 Drill-Down Step Verification Inspectors")
    st.caption("Audit intermediate state snapshots, formulas, and rule criteria without modifying decision state.")

    # Render pill buttons
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    with c1:
        if st.button("01. Intake", use_container_width=True, key="pill_intake", help="Verify demographics & files"):
            open_intake_inspector(case)
    with c2:
        if st.button("02. Agent 1", use_container_width=True, key="pill_ag1", help="Verify extraction & lab normalization"):
            open_agent1_inspector(case)
    with c3:
        if st.button("03. Router", use_container_width=True, key="pill_router", help="Verify triage & complexity classification"):
            open_router_inspector(case)
    with c4:
        if st.button("04. Agent 2", use_container_width=True, key="pill_ag2", help="Verify Copula synergies & actuarial rating"):
            open_agent2_inspector(case)
    with c5:
        if st.button("05. Conf Gate", use_container_width=True, key="pill_conf", help="Verify confidence scoring & reflection triggers"):
            open_confidence_gate_inspector(case)
    with c6:
        if st.button("06. Agent 3", use_container_width=True, key="pill_ag3", help="Verify multi-agent adversarial debate"):
            open_agent3_inspector(case)
    with c7:
        if st.button("07. Review Gate", use_container_width=True, key="pill_gate", help="Verify 4-tier calibration & escalation rules"):
            open_review_gate_inspector(case)
