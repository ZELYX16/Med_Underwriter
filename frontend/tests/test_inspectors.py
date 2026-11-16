"""Unit tests for Inspector normalization and resilience against varying state shapes."""
from unittest.mock import patch, MagicMock
import pytest


def test_agent1_inspector_dict_structured_facts():
    """Verify open_agent1_inspector handles dictionary structured_facts without KeyError."""
    from components.inspectors.agent1_inspector import open_agent1_inspector

    case_with_dict_facts = {
        "case_id": "CASE-FACTS-DICT",
        "agent1_completed": True,
        "structured_facts": {
            "diagnoses": ["Essential hypertension (I10)", "Type 2 diabetes mellitus (E11)"],
            "vitals": ["Blood pressure: 138/86 mmHg", "BMI: 28.4 kg/m2"],
            "medications": ["Metformin 500mg BID", "Amlodipine 5mg OD"],
        },
        "agent1_enrichment": {
            "lab_results": [
                {"Analyte": "HbA1c", "Value": "6.8%"},
                {"Analyte": "Total Cholesterol", "Value": "210 mg/dL"},
            ]
        },
        "agent1_metrics": {"completeness_score": 0.94},
    }

    # Mock streamlit components to verify execution without exception
    with patch("streamlit.dialog") as mock_dialog, \
         patch("streamlit.caption"), \
         patch("streamlit.markdown"), \
         patch("streamlit.columns", return_value=[MagicMock(), MagicMock(), MagicMock(), MagicMock()]), \
         patch("streamlit.metric"), \
         patch("streamlit.table") as mock_table, \
         patch("streamlit.info"), \
         patch("streamlit.json"), \
         patch("components.inspectors.base_inspector.render_inspector_tabs", return_value=(MagicMock(), MagicMock(), MagicMock())):
        
        # open_agent1_inspector was decorated with st.dialog; unwrapped or direct call
        func = getattr(open_agent1_inspector, "__wrapped__", open_agent1_inspector)
        # Should execute cleanly without raising KeyError: slice(None, 15, None)
        func(case_with_dict_facts)
        assert mock_table.called


def test_agent1_inspector_list_structured_facts():
    """Verify open_agent1_inspector handles list structured_facts cleanly."""
    from components.inspectors.agent1_inspector import open_agent1_inspector

    case_with_list_facts = {
        "case_id": "CASE-FACTS-LIST",
        "agent1_completed": True,
        "structured_facts": [
            {"statement": "Patient diagnosed with asthma in 2019"},
            {"statement": "Controlled on salbutamol inhaler PRN"},
        ],
        "agent1_enrichment": {"lab_results": []},
    }

    with patch("streamlit.caption"), \
         patch("streamlit.markdown"), \
         patch("streamlit.columns", return_value=[MagicMock(), MagicMock(), MagicMock(), MagicMock()]), \
         patch("streamlit.metric"), \
         patch("streamlit.table") as mock_table, \
         patch("streamlit.info"), \
         patch("components.inspectors.base_inspector.render_inspector_tabs", return_value=(MagicMock(), MagicMock(), MagicMock())):

        func = getattr(open_agent1_inspector, "__wrapped__", open_agent1_inspector)
        func(case_with_list_facts)
        assert mock_table.called


def test_agent1_inspector_empty_facts():
    """Verify open_agent1_inspector handles empty structured_facts cleanly."""
    from components.inspectors.agent1_inspector import open_agent1_inspector

    case_empty = {"case_id": "CASE-EMPTY"}

    with patch("streamlit.caption"), \
         patch("streamlit.markdown"), \
         patch("streamlit.columns", return_value=[MagicMock(), MagicMock(), MagicMock(), MagicMock()]), \
         patch("streamlit.metric"), \
         patch("streamlit.info") as mock_info, \
         patch("components.inspectors.base_inspector.render_inspector_tabs", return_value=(MagicMock(), MagicMock(), MagicMock())):

        func = getattr(open_agent1_inspector, "__wrapped__", open_agent1_inspector)
        func(case_empty)
        assert mock_info.called


def test_render_dashboard_metric():
    """Verify render_dashboard_metric renders valid HTML without crashing."""
    from components.design_system import render_dashboard_metric

    with patch("streamlit.markdown") as mock_markdown:
        render_dashboard_metric(
            label="Total Cases",
            value=42,
            icon="📁",
            accent_color="#2563eb",
            bg_color="#eff6ff",
            subtext="All submissions",
        )
        assert mock_markdown.called
        html_arg = mock_markdown.call_args[0][0]
        assert "Total Cases" in html_arg
        assert "42" in html_arg
        assert "#2563eb" in html_arg
