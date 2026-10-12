"""Reusable presentation and layout components for Lead Cleaner."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st


def render_top_navbar(
    is_connected: bool,
    portal_id: Optional[str],
    dry_run: bool,
) -> None:
    """Render the top product navbar with identity, status chips, and settings shortcut."""
    col_left, col_right = st.columns([3, 2], vertical_alignment="center")

    with col_left:
        logo_html = """
        <div style="display:flex; align-items:center; gap:12px;">
            <div style="background:#FF5C35; color:white; width:34px; height:34px; border-radius:8px; display:flex; align-items:center; justify-content:center; font-size:1.15rem; font-weight:700;">
                ✦
            </div>
            <div>
                <div style="font-size:1.15rem; font-weight:700; color:#243342; line-height:1.2;">Lead Cleaner</div>
                <div style="font-size:0.75rem; color:#617184;">HubSpot CRM Data Quality & Pipeline Hygiene</div>
            </div>
        </div>
        """
        st.markdown(logo_html, unsafe_allow_html=True)

    with col_right:
        # Status chips
        if is_connected:
            conn_chip = f'<span class="badge-chip badge-chip-green">● Connected ({portal_id or "Active"})</span>'
        else:
            conn_chip = '<span class="badge-chip badge-chip-gray">○ HubSpot Disconnected</span>'

        if dry_run:
            safety_chip = '<span class="badge-chip badge-chip-amber">🛡️ Preview Mode</span>'
        else:
            safety_chip = '<span class="badge-chip badge-chip-orange">⚠️ Live Mode</span>'

        status_html = f"""
        <div style="display:flex; justify-content:flex-end; align-items:center; gap:8px;">
            {conn_chip}
            {safety_chip}
        </div>
        """
        st.markdown(status_html, unsafe_allow_html=True)

    st.markdown("<div style='border-bottom: 1px solid #DCE3EA; margin: 12px 0 20px 0;'></div>", unsafe_allow_html=True)


def render_step_progress(steps: List[str], current_step_idx: int) -> None:
    """Render a step-by-step breadcrumb progress bar."""
    pills = []
    for i, s in enumerate(steps):
        if i < current_step_idx:
            cls = "step-pill step-pill-completed"
            icon = "✓"
        elif i == current_step_idx:
            cls = "step-pill step-pill-active"
            icon = str(i + 1)
        else:
            cls = "step-pill"
            icon = str(i + 1)

        pills.append(f'<span class="{cls}"><span class="step-num">{icon}</span> {s}</span>')

    divider = ' <span class="step-divider">→</span> '
    container_html = f"""
    <div class="step-container">
        {divider.join(pills)}
    </div>
    """
    st.markdown(container_html, unsafe_allow_html=True)


def render_safety_notice(dry_run: bool = True) -> None:
    """Render the explicit CRM safety guarantee box."""
    if dry_run:
        msg = """
        <div class="safety-banner">
            <span class="safety-banner-icon">🛡️</span>
            <div>
                <strong>Preview mode is active.</strong> Your CRM records will not be changed without explicit confirmation. Every suggested fix can be inspected and approved first.
            </div>
        </div>
        """
    else:
        msg = """
        <div class="safety-banner" style="background:#FEF2F2; border-color:#FECACA; color:#991B1B;">
            <span class="safety-banner-icon">⚠️</span>
            <div>
                <strong>Live mode is active.</strong> Approved updates will write directly to your HubSpot account. Double-check your reviewed records before applying.
            </div>
        </div>
        """
    st.markdown(msg, unsafe_allow_html=True)


def render_empty_state(
    title: str,
    description: str,
    icon: str = "🔍",
    action_label: Optional[str] = None,
    action_key: Optional[str] = None,
) -> bool:
    """Render a clean, helpful empty state card with optional CTA."""
    html = f"""
    <div style="background:#FFFFFF; border:1px dashed #DCE3EA; border-radius:12px; padding:36px 24px; text-align:center; margin:16px 0;">
        <div style="font-size:2rem; margin-bottom:8px;">{icon}</div>
        <div style="font-size:1.05rem; font-weight:600; color:#243342; margin-bottom:4px;">{title}</div>
        <div style="font-size:0.86rem; color:#617184; max-width:480px; margin:0 auto 16px auto; line-height:1.45;">{description}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    if action_label and action_key:
        c1, c2, c3 = st.columns([2, 1, 2])
        with c2:
            return st.button(action_label, key=action_key, type="primary", use_container_width=True)
    return False
