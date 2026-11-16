"""Enterprise Design System Components for MedUnderwriter."""
from __future__ import annotations

import html
from typing import Any
import streamlit as st


def render_tier_badge(tier: str | int | None) -> None:
    """Render a WCAG 2.1 AA compliant semantic status badge for review tiers."""
    t_str = str(tier if tier is not None else "0").strip().lower()
    if t_str in {"0", "tier 0", "tier_0", "stp"}:
        label = "✓ Tier 0: Straight-Through (STP)"
        cls = "status-tier-0"
    elif t_str in {"1", "tier 1", "tier_1", "fast_track", "fast-track"}:
        label = "⚡ Tier 1: Fast-Track Human Review"
        cls = "status-tier-1"
    elif t_str in {"2", "tier 2", "tier_2", "comprehensive"}:
        label = "⚠️ Tier 2: Comprehensive Human Review"
        cls = "status-tier-2"
    elif t_str in {"3", "tier 3", "tier_3", "escalated", "cmo"}:
        label = "🛑 Tier 3: Executive CMO Escalation"
        cls = "status-tier-3"
    else:
        label = f"Tier: {tier}"
        cls = "status-pending"

    st.markdown(
        f'<span class="status-badge {cls}" style="font-size: 13px; padding: 6px 12px; font-weight: 700;">{html.escape(label)}</span>',
        unsafe_allow_html=True,
    )


def elevated_card(title: str, subtitle: str = "", level: int = 1) -> None:
    """Render an elevated card header."""
    cls = "elevated-surface-2" if level > 1 else "elevated-card"
    sub = f'<div style="color: #64748b; font-size: 13px; margin-top: 2px;">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="{cls}" style="margin-bottom: 12px; padding: 14px 18px;">
            <div style="font-size: 16px; font-weight: 700; color: #1e293b;">{html.escape(title)}</div>
            {sub}
        </div>
        """,
        unsafe_allow_html=True,
    )


def formula_callout(formula: str, title: str = "", notes: str = "") -> None:
    """Render a styled actuarial/rule formula callout box."""
    header = f'<div style="font-weight: 700; font-size: 13px; color: #1e3a8a; margin-bottom: 6px;">{html.escape(title)}</div>' if title else ""
    footer = f'<div style="color: #475569; font-size: 12px; margin-top: 6px; font-style: italic;">{html.escape(notes)}</div>' if notes else ""
    st.markdown(
        f"""
        <div class="formula-callout">
            {header}
            <div style="font-family: 'Roboto Mono', Menlo, monospace; font-size: 13px; color: #0f172a;">{html.escape(formula)}</div>
            {footer}
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_surface(label: str, value: Any, unit: str = "", help_text: str = "") -> None:
    """Render a numeric or actuarial metric in tabular/mono typography."""
    help_attr = f'title="{html.escape(help_text)}"' if help_text else ""
    st.markdown(
        f"""
        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;" {help_attr}>
            <div style="font-size: 11px; text-transform: uppercase; font-weight: 700; color: #64748b; letter-spacing: 0.5px;">{html.escape(label)}</div>
            <div class="metric-surface" style="font-size: 20px; color: #0f172a; margin-top: 4px;">
                {html.escape(str(value))} <span style="font-size: 12px; color: #64748b; font-weight: 500;">{html.escape(unit)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_metric(
    label: str,
    value: Any,
    icon: str,
    accent_color: str = "#2563eb",
    bg_color: str = "#eff6ff",
    subtext: str = "",
) -> None:
    """Render an Enterprise HealthTech Light elevated metric card with top accent and category icon."""
    sub_html = f'<div style="font-size: 11px; color: #64748b; margin-top: 5px;">{html.escape(subtext)}</div>' if subtext else ""
    st.markdown(
        f"""
        <div class="elevated-metric-card" style="border-top: 3.5px solid {accent_color};">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                <span class="elevated-metric-label">
                    {html.escape(label)}
                </span>
                <span class="metric-icon-badge" style="background: {bg_color}; width: 28px; height: 28px; font-size: 14px; margin-bottom: 0;">
                    {icon}
                </span>
            </div>
            <div class="elevated-metric-val">
                {html.escape(str(value))}
            </div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
