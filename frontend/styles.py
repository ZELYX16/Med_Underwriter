from __future__ import annotations

import streamlit as st


def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* =========================================================
           GLOBAL
        ========================================================= */

        .stApp {
            background: #f4f6f9;
            color: #172033;
        }

        .block-container {
            max-width: 1500px;
            padding-top: 1.5rem;
            padding-bottom: 3rem;
        }

        [data-testid="stSidebar"] {
            background: #101b2d;
            border-right: 1px solid #24334a;
        }

        [data-testid="stSidebar"] * {
            color: #d9e2ef;
        }

        [data-testid="stSidebar"] .stButton > button {
            background: transparent;
            border: 1px solid transparent;
            color: #c9d4e3;
            text-align: left;
            justify-content: flex-start;
            border-radius: 7px;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background: #1c2b43;
            border-color: #2d405f;
            color: #ffffff;
        }

        /* =========================================================
           BUTTONS
        ========================================================= */

        .stButton > button {
            min-height: 38px;
            border-radius: 7px;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            color: #172033;
            font-weight: 600;
            transition: 0.15s ease;
        }

        .stButton > button:hover {
            border-color: #42658f;
            background: #f8fafc;
            color: #172033;
        }

        .stButton > button:focus,
        .stButton > button:active {
            color: #172033 !important;
            border-color: #42658f !important;
            background: #f1f5f9 !important;
            box-shadow: none !important;
        }

        /* Primary buttons */
        .primary-action .stButton > button {
            background: #17375e;
            border-color: #17375e;
            color: #ffffff !important;
        }

        .primary-action .stButton > button:hover {
            background: #214a78;
            border-color: #214a78;
            color: #ffffff !important;
        }

        /* =========================================================
           TYPOGRAPHY
        ========================================================= */

        .page-title {
            font-size: 30px;
            font-weight: 750;
            color: #13233f;
            margin-bottom: 2px;
            letter-spacing: -0.4px;
        }

        .page-subtitle {
            color: #68778c;
            font-size: 14px;
            margin-bottom: 24px;
        }

        .section-title {
            color: #172033;
            font-size: 19px;
            font-weight: 700;
            margin-top: 26px;
            margin-bottom: 12px;
        }

        .section-caption {
            color: #718096;
            font-size: 13px;
            margin-top: -7px;
            margin-bottom: 14px;
        }

        /* =========================================================
           CARDS
        ========================================================= */

        .enterprise-card {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 9px;
            padding: 18px 20px;
            margin-bottom: 14px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
        }

        .card-eyebrow {
            color: #718096;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.7px;
            margin-bottom: 5px;
        }

        .card-title {
            color: #172033;
            font-size: 17px;
            font-weight: 700;
            margin-bottom: 4px;
        }

        .card-subtitle {
            color: #68778c;
            font-size: 13px;
        }

        /* =========================================================
           METRICS
        ========================================================= */

        .metric-card {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 9px;
            padding: 16px 18px;
            min-height: 95px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
        }

        .metric-label {
            color: #718096;
            font-size: 12px;
            font-weight: 650;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .metric-value {
            color: #13233f;
            font-size: 27px;
            font-weight: 750;
            margin-top: 5px;
        }

        /* =========================================================
           STATUS
        ========================================================= */

        .status-badge {
            display: inline-block;
            padding: 4px 9px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            line-height: 1.2;
            white-space: nowrap;
        }

        .status-draft,
        .status-pending {
            background: #eef2f6;
            color: #475569;
        }

        .status-in-progress {
            background: #e8f0fb;
            color: #285a91;
        }

        .status-human-review,
        .status-review {
            background: #fff4d6;
            color: #8a5a00;
        }

        .status-completed,
        .status-approved {
            background: #e5f5ec;
            color: #17663b;
        }

        .status-failed,
        .status-rejected {
            background: #fdecec;
            color: #a33a3a;
        }

        .status-sent-back {
            background: #f3eafa;
            color: #68429a;
        }

        /* =========================================================
           APPLICANT
        ========================================================= */

        .applicant-hero {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 10px;
            padding: 22px 24px;
            margin-bottom: 18px;
        }

        .applicant-name {
            font-size: 25px;
            font-weight: 750;
            color: #13233f;
        }

        .applicant-id {
            font-size: 13px;
            color: #718096;
            margin-top: 3px;
        }

        .applicant-meta {
            font-size: 13px;
            color: #526176;
            margin-top: 10px;
        }

        /* =========================================================
           CASE HEADER
        ========================================================= */

        .case-header {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 10px;
            padding: 20px 22px;
            margin-bottom: 18px;
        }

        .case-eyebrow {
            color: #718096;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.7px;
        }

        .case-id {
            color: #13233f;
            font-size: 24px;
            font-weight: 750;
            margin-top: 3px;
        }

        .case-applicant {
            color: #44546a;
            font-size: 14px;
            margin-top: 4px;
        }

        .case-product {
            color: #68778c;
            font-size: 13px;
            margin-top: 7px;
        }

        .case-meta-block {
            padding-left: 14px;
            border-left: 1px solid #e2e8f0;
        }

        .header-risk {
            text-align: right;
        }

        .header-risk-label {
            color: #718096;
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 700;
        }

        .header-risk-value {
            color: #13233f;
            font-size: 28px;
            font-weight: 750;
        }

        .header-risk-value span {
            color: #718096;
            font-size: 12px;
            font-weight: 500;
        }

        /* =========================================================
           FIELDS
        ========================================================= */

        .field-block {
            margin-bottom: 14px;
        }

        .field-label {
            color: #718096;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.45px;
            font-weight: 700;
            margin-bottom: 3px;
        }

        .field-value {
            color: #172033;
            font-size: 14px;
            line-height: 1.45;
        }

        /* =========================================================
           TAGS
        ========================================================= */

        .tag {
            display: inline-block;
            background: #eef3f8;
            color: #34465d;
            border: 1px solid #d8e1eb;
            border-radius: 5px;
            padding: 5px 9px;
            margin: 0 5px 5px 0;
            font-size: 12px;
        }

        .tag-risk {
            background: #fff4d6;
            border-color: #f0d993;
            color: #805900;
        }

        .tag-success {
            background: #e7f5ed;
            border-color: #c7e6d3;
            color: #17663b;
        }

        /* =========================================================
           RISK
        ========================================================= */

        .risk-score-card {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 9px;
            padding: 17px;
            text-align: center;
        }

        .risk-score-label {
            color: #718096;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }

        .risk-score-value {
            color: #13233f;
            font-size: 30px;
            font-weight: 750;
            margin-top: 5px;
        }

        .risk-factor {
            border-left: 3px solid #d49a27;
            background: #fffdf7;
            padding: 10px 13px;
            margin-bottom: 8px;
            border-radius: 0 6px 6px 0;
        }

        /* =========================================================
           EVIDENCE
        ========================================================= */

        .evidence-card {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-left: 4px solid #6b7f99;
            border-radius: 7px;
            padding: 12px 15px;
            margin-bottom: 8px;
        }

        .evidence-card.applicant {
            border-left-color: #3d6f9f;
        }

        .evidence-card.knowledge {
            border-left-color: #6d63a3;
        }

        .evidence-card.regulatory {
            border-left-color: #8a6a35;
        }

        .evidence-title {
            color: #172033;
            font-size: 13px;
            font-weight: 700;
        }

        .evidence-meta {
            color: #718096;
            font-size: 11px;
            margin-top: 3px;
        }

        .evidence-text {
            color: #4b5a70;
            font-size: 12px;
            margin-top: 7px;
            line-height: 1.5;
        }

        /* =========================================================
           AGENTS
        ========================================================= */

        .agent-header {
            background: #f7f9fb;
            border: 1px solid #dce3eb;
            border-radius: 8px 8px 0 0;
            padding: 14px 16px;
        }

        .agent-eyebrow {
            color: #718096;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
        }

        .agent-title {
            color: #172033;
            font-size: 16px;
            font-weight: 700;
            margin-top: 2px;
        }

        /* =========================================================
           WORKSPACE TOC
        ========================================================= */

        .workspace-toc {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 9px;
            padding: 12px;
            margin-bottom: 18px;
        }

        .workspace-toc-title {
            color: #172033;
            font-size: 12px;
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .workspace-toc-subtitle {
            color: #7a8799;
            font-size: 11px;
            margin-bottom: 10px;
        }

        /* =========================================================
           REVIEW
        ========================================================= */

        .review-banner {
            background: #fff8e7;
            border: 1px solid #ecd79e;
            border-left: 4px solid #d29a27;
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 16px;
        }

        .review-history-card {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 8px;
            padding: 13px 15px;
            margin-bottom: 9px;
        }

        .review-history-top {
            display: flex;
            justify-content: space-between;
            gap: 12px;
        }

        .review-history-reviewer {
            color: #172033;
            font-weight: 700;
            font-size: 13px;
        }

        .review-history-decision {
            color: #526176;
            font-size: 12px;
        }

        .review-history-comment {
            color: #68778c;
            font-size: 12px;
            margin-top: 8px;
        }

        /* =========================================================
           WORKFLOW
        ========================================================= */

        .workflow-item {
            border-left: 2px solid #cbd5e1;
            padding: 3px 0 12px 16px;
            margin-left: 5px;
        }

        .workflow-item.completed {
            border-left-color: #4f8a67;
        }

        .workflow-node {
            color: #172033;
            font-size: 13px;
            font-weight: 700;
        }

        .workflow-status {
            color: #718096;
            font-size: 11px;
            margin-top: 2px;
        }

        .workflow-message {
            color: #526176;
            font-size: 12px;
            margin-top: 5px;
        }

        /* =========================================================
           TABLE
        ========================================================= */

        [data-testid="stDataFrame"] {
            border: 1px solid #dce3eb;
            border-radius: 8px;
        }

        /* =========================================================
           EXPANDERS
        ========================================================= */

        [data-testid="stExpander"] {
            background: #ffffff;
            border: 1px solid #dce3eb;
            border-radius: 8px;
        }

        /* =========================================================
           INPUTS
        ========================================================= */

        .stTextInput input,
        .stSelectbox div[data-baseweb="select"],
        .stMultiSelect div[data-baseweb="select"] {
            border-radius: 7px;
        }

        /* =========================================================
           ALERTS
        ========================================================= */

        .stAlert {
            border-radius: 8px;
        }

        /* =========================================================
           FOOTER
        ========================================================= */

        .app-footer {
            border-top: 1px solid #dce3eb;
            margin-top: 40px;
            padding-top: 15px;
            color: #8a96a8;
            font-size: 11px;
            text-align: center;
        }

        /* =========================================================
           MOBILE / NARROW
        ========================================================= */

        @media (max-width: 900px) {
            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
            }

            .page-title {
                font-size: 25px;
            }

            .case-id {
                font-size: 20px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(
    title: str,
    subtitle: str = "",
) -> None:
    st.markdown(
        f"""
        <div class="page-title">{title}</div>
        <div class="page-subtitle">{subtitle}</div>
        """,
        unsafe_allow_html=True,
    )


def section_title(
    title: str,
    caption: str = "",
) -> None:
    st.markdown(
        f'<div class="section-title">{title}</div>',
        unsafe_allow_html=True,
    )

    if caption:
        st.markdown(
            f'<div class="section-caption">{caption}</div>',
            unsafe_allow_html=True,
        )


def card_start(class_name: str = "enterprise-card") -> None:
    st.markdown(
        f'<div class="{class_name}">',
        unsafe_allow_html=True,
    )


def card_end() -> None:
    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


def metric_card(
    label: str,
    value: str | int,
) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(
    status: str,
    label: str | None = None,
) -> None:
    normalized = str(status or "unknown").strip().lower()
    class_name = normalized.replace("_", "-").replace(" ", "-")
    display_label = label if label is not None else status or "Unknown"

    st.markdown(
        f"""
        <span class="status-badge status-{class_name}">
            {display_label}
        </span>
        """,
        unsafe_allow_html=True,
    )


def evidence_card(
    title: str,
    meta: str = "",
    text: str = "",
    scope: str = "applicant",
) -> None:
    scope_class = str(scope or "applicant").lower()

    st.markdown(
        f"""
        <div class="evidence-card {scope_class}">
            <div class="evidence-title">{title}</div>
            <div class="evidence-meta">{meta}</div>
            <div class="evidence-text">{text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def risk_card(
    label: str,
    value: str | int | float,
) -> None:
    st.markdown(
        f"""
        <div class="risk-score-card">
            <div class="risk-score-label">{label}</div>
            <div class="risk-score-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def workflow_item(
    node: str,
    status: str,
    message: str = "",
    completed: bool = False,
) -> None:
    state_class = "completed" if completed else ""

    st.markdown(
        f"""
        <div class="workflow-item {state_class}">
            <div class="workflow-node">{node}</div>
            <div class="workflow-status">{status}</div>
            <div class="workflow-message">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def review_banner(
    title: str,
    message: str,
) -> None:
    st.markdown(
        f"""
        <div class="review-banner">
            <div class="card-title">{title}</div>
            <div class="card-subtitle">{message}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def footer(
    text: str = "",
) -> None:
    footer_text = (
        text
        or "MedUnderwrite AI · Medical Underwriting Workstation"
    )

    st.markdown(
        f"""
        <div class="app-footer">
            {footer_text}
        </div>
        """,
        unsafe_allow_html=True,
    )