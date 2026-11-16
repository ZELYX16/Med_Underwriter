"""Base Inspector Layout & Utilities for MedUnderwriter."""
from __future__ import annotations

import json
from typing import Any
import streamlit as st


def render_json_tab(raw_data: Any, title: str = "State Snapshot") -> None:
    """Render formatted JSON with copy button."""
    st.subheader(f"Raw {title}")
    json_str = json.dumps(raw_data, indent=2, default=str)
    st.code(json_str, language="json")


def render_inspector_tabs(
    summary_title: str = "Executive Summary",
    mechanics_title: str = "Calculation & Rule Mechanics",
    json_title: str = "Raw State Snapshot",
    extra_tab: str | None = None,
):
    """Return standard tab containers for inspectors."""
    tab_titles = [f"📊 {summary_title}", f"⚙️ {mechanics_title}"]
    if extra_tab:
        tab_titles.append(f"📄 {extra_tab}")
    tab_titles.append(f"🔍 {json_title}")

    return st.tabs(tab_titles)
