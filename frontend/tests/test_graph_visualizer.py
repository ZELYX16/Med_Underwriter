"""Unit tests for the Mermaid Execution Path Graph Visualizer."""
import pytest
from components.graph_visualizer import generate_mermaid_graph


def test_mermaid_graph_traversal_mapping():
    # Case with complete linear pipeline to human review
    case = {
        "case_id": "CASE-123",
        "final_status": "human_review",
        "review_tier": "Tier 2",
        "overall_risk_score": 75.0,
        "workflow_trace": [
            {"node": "intake", "status": "completed"},
            {"node": "agent1_submission", "status": "completed"},
            {"node": "complexity_router", "status": "completed"},
            {"node": "agent2_risk", "status": "completed"},
            {"node": "confidence_gate", "status": "completed"},
            {"node": "human_review", "status": "awaiting"},
        ],
    }
    graph = generate_mermaid_graph(case)
    
    assert "flowchart TD" in graph
    assert "class N_INTAKE traversed;" in graph
    assert "class N_AG1 traversed;" in graph
    assert "class N_ROUTER gate;" in graph
    assert "class N_AG2 traversed;" in graph
    assert "class N_CONF gate;" in graph
    # Agent 3 was not in trace -> bypassed
    assert "class N_AG3 bypassed;" in graph
    assert "class N_REVIEW active;" in graph
    assert "class N_STP bypassed;" in graph


def test_mermaid_graph_rescore_loop_handling():
    # Case with reflection rescore loop (agent2 traversed twice)
    case = {
        "case_id": "CASE-RESCORE",
        "final_status": "human_review",
        "review_tier": "Tier 3",
        "overall_risk_score": 88.0,
        "reflection_round": 2,
        "workflow_trace": [
            {"node": "intake"},
            {"node": "agent1_submission"},
            {"node": "complexity_router"},
            {"node": "agent2_risk"},
            {"node": "confidence_gate"},
            {"node": "agent3_reflection"},
            {"node": "agent2_risk"},
            {"node": "confidence_gate"},
            {"node": "agent3_reflection"},
            {"node": "human_review"},
        ],
    }
    graph = generate_mermaid_graph(case)
    
    assert "class N_AG3 traversed;" in graph
    # Loopback edge present with rescore round indicator
    assert "Rescore Loop (Round 2)" in graph
    assert "class N_REVIEW active;" in graph


def test_mermaid_edge_condition_escaping():
    case = {
        "case_id": "CASE-ESCAPE",
        "final_status": "approved",
        "review_tier": "Tier 0",
        "overall_risk_score": 25.0,
        "agent2_confidence": 0.92,
        "workflow_trace": [
            {"node": "intake"},
            {"node": "agent1_submission"},
            {"node": "complexity_router"},
            {"node": "agent2_risk"},
            {"node": "confidence_gate"},
            {"node": "finalize"},
        ],
    }
    graph = generate_mermaid_graph(case)
    
    # Must use HTML entities &lt; and &gt; instead of raw < or > in Mermaid labels
    assert "&gt;= 0.70" in graph or "&lt; 0.70" in graph or "&lt; 40" in graph
    assert "<" not in [line.split("|")[1] for line in graph.splitlines() if "|" in line and "classDef" not in line and ">" not in line]


def test_mermaid_empty_trace_fallback():
    # Empty case state
    empty_case = {}
    graph = generate_mermaid_graph(empty_case)
    
    assert "flowchart TD" in graph
    assert "N_INTAKE" in graph
    assert "class N_INTAKE" in graph
    assert "classDef traversed" in graph
