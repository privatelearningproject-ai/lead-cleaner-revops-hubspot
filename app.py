"""Streamlit Web Application for RevOpsBolt Lead Hygiene & HubSpot Pipeline.

RevOpsBolt Obsidian & Neon Orange Design System:
- Dark obsidian base (#0B0E14) for body and sidebar
- Dark gray container surfaces (#12161F) and subtle borders (#212836)
- Electric orange gradient accents (linear-gradient(135deg, #FF6A00, #FF8800))
- Monospace subheadings and diagnostic tags (// DIAGNOSTIC SUITE 02 - LEAD ENGINE)
- High-contrast KPI metric cards with colored rating numbers (Green #00A389, Orange #FF8800, Red #FF4D4D)
- Glowing rounded orange pill buttons and status pills ("PORTAL CONNECTED", "DRY-RUN ACTIVE", "FREEMIUM QUOTA")
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st

from cleaner.db import (
    DEFAULT_DB_PATH,
    get_connection,
    get_enrichment_quota,
    list_portals,
    log_merge_proposals,
    log_record_audits,
    log_run,
)
from cleaner.dedupe import deduplicate_leads
from cleaner.enrich import enrich_dataframe, get_gemini_api_key
from cleaner.hubspot import ConfigurationError, HubSpotClient, get_token_from_env
from cleaner.loader import load_and_map
from cleaner.report import generate_markdown_report, generate_summary_stats
from cleaner.validate import FATAL_ISSUES, validate_dataframe
from components.mixed_dashboard import render_mixed_dashboard
from hubspot.connection import validate_and_connect

# Page Configuration
st.set_page_config(
    page_title="RevOpsBolt | Lead Hygiene & CRM Pipeline",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_session_state() -> None:
    """Initialize Streamlit session state variables."""
    if "pipeline_results" not in st.session_state:
        st.session_state.pipeline_results = None
    if "sync_results" not in st.session_state:
        st.session_state.sync_results = None
    if "active_file_name" not in st.session_state:
        st.session_state.active_file_name = None
    if "hubspot_connected" not in st.session_state:
        st.session_state.hubspot_connected = False
    if "hubspot_portal_id" not in st.session_state:
        st.session_state.hubspot_portal_id = None
    if "hubspot_token" not in st.session_state:
        st.session_state.hubspot_token = None
    if "show_marketplace_modal" not in st.session_state:
        st.session_state.show_marketplace_modal = False
    if "show_db_modal" not in st.session_state:
        st.session_state.show_db_modal = False
    if "selected_contact_id" not in st.session_state:
        st.session_state.selected_contact_id = 0


def inject_custom_css() -> None:
    """Inject RevOpsBolt Obsidian & Neon Orange Design System CSS."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&display=swap');

        /* Hide standard Streamlit header and footer chrome */
        header[data-testid="stHeader"] {
            display: none !important;
        }
        footer {
            display: none !important;
        }
        #MainMenu {
            visibility: hidden !important;
        }
        div[data-testid="stDecoration"] {
            display: none !important;
        }

        :root {
            --bolt-obsidian: #0B0E14;
            --bolt-surface: #12161F;
            --bolt-surface-hover: #171C27;
            --bolt-border: #212836;
            --bolt-border-light: #2A3447;
            --bolt-neon-orange: #FF6A00;
            --bolt-electric-orange: #FF8800;
            --bolt-green: #00A389;
            --bolt-red: #FF4D4D;
            --bolt-text-primary: #E6EDF3;
            --bolt-text-secondary: #94A3B8;
            --bolt-text-muted: #64748B;
        }

        /* Dark Obsidian Base */
        .stApp {
            background-color: var(--bolt-obsidian) !important;
            color: var(--bolt-text-primary) !important;
            font-family: 'Inter', -apple-system, sans-serif !important;
        }

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background-color: var(--bolt-obsidian) !important;
            border-right: 1px solid var(--bolt-border) !important;
        }
        section[data-testid="stSidebar"] > div {
            background-color: var(--bolt-obsidian) !important;
        }
        section[data-testid="stSidebar"] .stMarkdown h3, 
        section[data-testid="stSidebar"] .stMarkdown h4 {
            color: #FFFFFF !important;
            font-family: 'JetBrains Mono', monospace !important;
            letter-spacing: 0.04em !important;
        }

        /* RevOpsBolt Top Header */
        .bolt-header-card {
            background: var(--bolt-surface);
            border: 1px solid var(--bolt-border);
            border-radius: 14px;
            padding: 22px 28px;
            margin-bottom: 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
            position: relative;
            overflow: hidden;
        }
        .bolt-header-card::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, #FF6A00, #FF8800, #00A389, transparent);
        }
        .bolt-diagnostic-tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            color: var(--bolt-electric-orange);
            text-transform: uppercase;
            margin-bottom: 6px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .bolt-title {
            color: #FFFFFF;
            font-size: 1.8rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 0 0 6px 0;
            line-height: 1.2;
        }
        .bolt-subtext {
            color: var(--bolt-text-secondary);
            font-size: 0.88rem;
            font-family: 'JetBrains Mono', monospace;
            margin: 0;
            line-height: 1.4;
        }

        /* Pill Status Badges ("PORTAL CONNECTED", "DRY-RUN ACTIVE", "FREEMIUM QUOTA") */
        .bolt-pill-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.74rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            padding: 6px 14px;
            border-radius: 9999px;
            text-transform: uppercase;
            white-space: nowrap;
        }
        .bolt-pill-connected {
            background: rgba(0, 163, 137, 0.12);
            border: 1px solid rgba(0, 163, 137, 0.45);
            color: var(--bolt-green);
            box-shadow: 0 0 12px rgba(0, 163, 137, 0.2);
        }
        .bolt-pill-disconnected {
            background: rgba(148, 163, 184, 0.08);
            border: 1px solid var(--bolt-border);
            color: var(--bolt-text-secondary);
        }
        .bolt-pill-dryrun {
            background: rgba(255, 136, 0, 0.12);
            border: 1px solid rgba(255, 136, 0, 0.45);
            color: var(--bolt-electric-orange);
            box-shadow: 0 0 12px rgba(255, 136, 0, 0.2);
        }
        .bolt-pill-live {
            background: rgba(255, 77, 77, 0.12);
            border: 1px solid rgba(255, 77, 77, 0.45);
            color: var(--bolt-red);
            box-shadow: 0 0 12px rgba(255, 77, 77, 0.25);
        }
        .bolt-pill-quota {
            background: rgba(255, 106, 0, 0.12);
            border: 1px solid rgba(255, 106, 0, 0.45);
            color: var(--bolt-neon-orange);
            box-shadow: 0 0 12px rgba(255, 106, 0, 0.2);
        }
        .bolt-pulse-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            display: inline-block;
        }
        .bolt-dot-green { background: #00A389; box-shadow: 0 0 8px #00A389; }
        .bolt-dot-orange { background: #FF8800; box-shadow: 0 0 8px #FF8800; }
        .bolt-dot-red { background: #FF4D4D; box-shadow: 0 0 8px #FF4D4D; }
        .bolt-dot-neon { background: #FF6A00; box-shadow: 0 0 8px #FF6A00; }
        .bolt-dot-gray { background: #64748B; }

        /* High-Contrast KPI Metric Cards */
        .bolt-kpi-card {
            background: var(--bolt-surface);
            border: 1px solid var(--bolt-border);
            border-radius: 12px;
            padding: 18px 22px;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
        }
        .bolt-kpi-card:hover {
            border-color: var(--bolt-border-light);
            box-shadow: 0 6px 24px rgba(0, 0, 0, 0.5);
            transform: translateY(-1px);
        }
        .bolt-kpi-title {
            color: var(--bolt-text-secondary);
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-family: 'JetBrains Mono', monospace;
            margin-bottom: 8px;
        }
        .bolt-kpi-val {
            font-size: 2.1rem;
            font-weight: 800;
            line-height: 1.1;
            font-family: 'Inter', sans-serif;
        }
        .bolt-kpi-desc {
            color: var(--bolt-text-muted);
            font-size: 0.74rem;
            font-family: 'JetBrains Mono', monospace;
            margin-top: 6px;
        }

        /* Restyle st.metric to dark obsidian cards */
        div[data-testid="stMetric"] {
            background-color: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            border-radius: 12px !important;
            padding: 18px 20px !important;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35) !important;
        }
        div[data-testid="stMetricLabel"] {
            color: var(--bolt-text-secondary) !important;
            font-size: 0.74rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.08em !important;
            font-family: 'JetBrains Mono', monospace !important;
        }
        div[data-testid="stMetricValue"] {
            color: var(--bolt-text-primary) !important;
            font-size: 1.95rem !important;
            font-weight: 800 !important;
        }

        /* Glowing Rounded Orange Pill Buttons */
        button[kind="primary"], div.stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #FF6A00, #FF8800) !important;
            border: none !important;
            color: #FFFFFF !important;
            font-weight: 700 !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 0.85rem !important;
            letter-spacing: 0.04em !important;
            border-radius: 9999px !important;
            padding: 9px 24px !important;
            box-shadow: 0 0 18px rgba(255, 106, 0, 0.42) !important;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
            text-transform: uppercase !important;
        }
        button[kind="primary"]:hover, div.stButton > button[kind="primary"]:hover {
            background: linear-gradient(135deg, #FF7700, #FF9900) !important;
            box-shadow: 0 0 28px rgba(255, 136, 0, 0.75) !important;
            transform: translateY(-1px) scale(1.01) !important;
        }
        button[kind="primary"]:active, div.stButton > button[kind="primary"]:active {
            transform: translateY(0) scale(0.99) !important;
        }

        /* Secondary Pill Buttons */
        button[kind="secondary"], div.stButton > button[kind="secondary"] {
            background: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            color: var(--bolt-text-primary) !important;
            font-weight: 600 !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 0.82rem !important;
            letter-spacing: 0.03em !important;
            border-radius: 9999px !important;
            padding: 8px 20px !important;
            transition: all 0.2s ease !important;
        }
        button[kind="secondary"]:hover, div.stButton > button[kind="secondary"]:hover {
            border-color: var(--bolt-electric-orange) !important;
            color: var(--bolt-electric-orange) !important;
            box-shadow: 0 0 14px rgba(255, 136, 0, 0.3) !important;
            background: var(--bolt-surface-hover) !important;
        }

        /* Download Buttons */
        div.stDownloadButton > button {
            background: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            color: var(--bolt-text-primary) !important;
            font-weight: 600 !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 0.82rem !important;
            letter-spacing: 0.03em !important;
            border-radius: 9999px !important;
            padding: 8px 20px !important;
            transition: all 0.2s ease !important;
        }
        div.stDownloadButton > button:hover {
            border-color: var(--bolt-green) !important;
            color: var(--bolt-green) !important;
            box-shadow: 0 0 14px rgba(0, 163, 137, 0.35) !important;
            background: var(--bolt-surface-hover) !important;
        }

        /* Restyle st.tabs */
        div[data-testid="stTabs"] {
            border-bottom: 1px solid var(--bolt-border) !important;
            margin-bottom: 20px !important;
        }
        div[data-testid="stTabs"] button {
            color: var(--bolt-text-secondary) !important;
            font-size: 0.88rem !important;
            font-weight: 600 !important;
            font-family: 'JetBrains Mono', monospace !important;
            padding: 12px 22px !important;
            border-bottom: 2px solid transparent !important;
            transition: all 0.15s ease !important;
            letter-spacing: 0.03em !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--bolt-electric-orange) !important;
            border-bottom: 2px solid var(--bolt-neon-orange) !important;
            background: rgba(255, 106, 0, 0.08) !important;
            border-radius: 8px 8px 0 0 !important;
        }
        div[data-testid="stTabs"] button:hover {
            color: #FFFFFF !important;
        }

        /* Restyle st.dataframe to match dark obsidian */
        div[data-testid="stDataFrame"] {
            background-color: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            border-radius: 10px !important;
            padding: 4px !important;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25) !important;
        }

        /* Neon Orange Progress Bar */
        div[data-testid="stProgress"] > div > div > div {
            background: linear-gradient(90deg, #FF6A00, #FF8800) !important;
            box-shadow: 0 0 12px rgba(255, 106, 0, 0.6) !important;
        }
        div[data-testid="stProgress"] > div > div {
            background-color: #1A2130 !important;
            border-radius: 9999px !important;
        }

        /* Inputs & Form Controls */
        div[data-baseweb="input"], div[data-baseweb="base-input"] {
            background-color: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            color: var(--bolt-text-primary) !important;
            border-radius: 8px !important;
        }
        div[data-baseweb="input"]:focus-within {
            border-color: var(--bolt-electric-orange) !important;
            box-shadow: 0 0 10px rgba(255, 136, 0, 0.3) !important;
        }
        div[data-baseweb="select"] > div {
            background-color: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            color: var(--bolt-text-primary) !important;
            border-radius: 8px !important;
        }
        div[data-testid="stSegmentedControl"] {
            background-color: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            border-radius: 9999px !important;
            padding: 4px !important;
        }
        div[data-testid="stSegmentedControl"] button[data-checked="true"] {
            background: linear-gradient(135deg, #FF6A00, #FF8800) !important;
            color: #FFFFFF !important;
            border-radius: 9999px !important;
            box-shadow: 0 0 12px rgba(255, 106, 0, 0.4) !important;
        }
        div[data-testid="stExpander"] {
            background-color: var(--bolt-surface) !important;
            border: 1px solid var(--bolt-border) !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25) !important;
        }

        /* Quota Box */
        .bolt-quota-box {
            background: var(--bolt-surface);
            border: 1px solid var(--bolt-border);
            border-radius: 10px;
            padding: 14px 16px;
            margin-top: 10px;
            margin-bottom: 12px;
        }

        /* Inspection Card */
        .bolt-flyout-card {
            background: var(--bolt-surface);
            border: 1px solid var(--bolt-border);
            border-radius: 12px;
            padding: 20px;
            margin-top: 14px;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> Dict[str, Any]:
    """Render sidebar configuration controls, HubSpot connection, and quota viewer."""
    st.sidebar.markdown("### // CONFIGURATION ENGINE")

    st.sidebar.markdown("#### // MATCHING & QUALITY CUTOFFS")
    fuzzy_thresh = st.sidebar.slider(
        "Fuzzy Name Match Threshold",
        min_value=75,
        max_value=100,
        value=90,
        step=1,
        help="rapidfuzz token_sort_ratio cutoff for flagging same-city name duplicates for review.",
    )

    quality_cutoff = st.sidebar.slider(
        "Quality Score Cutoff",
        min_value=50,
        max_value=90,
        value=70,
        step=5,
        help="Minimum quality score (0-100) required to route a lead to cleaned contacts.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### // CRM SAFETY MODE")
    dry_run = st.sidebar.checkbox(
        "Enable Dry-Run Safety Mode",
        value=True,
        help="When checked, simulates HubSpot API calls without modifying real CRM data.",
    )

    if dry_run:
        st.sidebar.caption("🟢 **DRY-RUN ACTIVE (Safe Non-Destructive Simulation)**")
    else:
        st.sidebar.warning("⚠️ **LIVE SYNC ACTIVE (CRM Mutations Enabled)**")

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### // HUBSPOT AUTHENTICATION")
    env_token = get_token_from_env()
    stored_token = st.session_state.get("hubspot_token")
    token_display = stored_token if stored_token is not None else (env_token or "")

    token_input = st.sidebar.text_input(
        "HubSpot Private App Token",
        value=token_display,
        type="password",
        help="HubSpot token (starts with pat-). Defaults to .env if configured.",
    )

    is_connected = st.session_state.get("hubspot_connected", False)
    active_portal = st.session_state.get("hubspot_portal_id")

    col_conn_btn, col_conn_status = st.sidebar.columns([1, 1])
    if not is_connected:
        with col_conn_btn:
            if st.button("🔗 Connect", type="primary", use_container_width=True, key="hs_connect_btn"):
                if not token_input.strip():
                    st.sidebar.error("Please enter a token first.")
                else:
                    with st.sidebar.spinner("Validating with HubSpot API..."):
                        ok, portal_id_res, err_msg = validate_and_connect(token_input.strip())
                        if ok:
                            st.session_state.hubspot_connected = True
                            st.session_state.hubspot_portal_id = portal_id_res
                            st.session_state.hubspot_token = token_input.strip()
                            st.rerun()
                        else:
                            st.sidebar.error(f"❌ {err_msg}")
        with col_conn_status:
            st.sidebar.caption("⚪ **Not connected**")
    else:
        with col_conn_btn:
            if st.button("🔌 Disconnect", type="secondary", use_container_width=True, key="hs_disconnect_btn"):
                st.session_state.hubspot_connected = False
                st.session_state.hubspot_portal_id = None
                st.session_state.hubspot_token = ""
                st.rerun()
        st.sidebar.markdown(f":green[**Connected: {active_portal}**]")

    # Portal ID Resolution
    if is_connected and active_portal:
        portal_id = active_portal
    else:
        portal_id = st.sidebar.text_input(
            "Connected Portal ID",
            value="default_portal",
            help="HubSpot Account (Portal) ID. Governs OAuth credentials and tenant quota isolation.",
        )

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### // FREEMIUM ENRICHMENT QUOTA")
    quota = get_enrichment_quota(portal_id)
    used = quota["used"]
    limit = quota["limit"]
    remaining = quota["remaining"]
    is_exceeded = quota["is_exceeded"]

    st.sidebar.markdown(
        f"""
        <div class="bolt-quota-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-weight:700; font-size:0.8rem; color:#FFFFFF; font-family:'JetBrains Mono', monospace;">FREEMIUM QUOTA</span>
                <span class="bolt-pill-badge bolt-pill-quota" style="font-size:0.7rem; padding:2px 8px;">{used}/{limit} USED</span>
            </div>
            <div style="font-size:0.75rem; color:#94A3B8; font-family:'JetBrains Mono', monospace;">500 Free AI Enriched Leads</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    quota_pct = min(1.0, used / limit if limit > 0 else 1.0)
    st.sidebar.progress(quota_pct)
    st.sidebar.caption(f"⚡ **{remaining}** free contacts remaining")

    if is_exceeded:
        st.sidebar.error("Freemium quota reached (500/500). Upgrade plan to continue.")
        enrich_enabled = False
    else:
        enrich_enabled = st.sidebar.checkbox(
            "Enable Cloud LLM Note Enrichment",
            value=False,
            help="Extracts structured budget, product intent, and city using Gemini 1.5 Flash.",
        )

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### // PLATFORM DIAGNOSTICS")
    if st.sidebar.button("📖 RevOps & Sync Matrix Guide"):
        st.session_state.show_marketplace_modal = True

    if st.sidebar.button("📜 SQLite Execution History"):
        st.session_state.show_db_modal = True

    ui_mode = st.sidebar.selectbox(
        "Dashboard View Mode",
        options=["classic", "mixed"],
        index=0,
        help="Switch between Classic Leadfeeder Tabs and Mixed High-Density view.",
    )

    return {
        "fuzzy_threshold": fuzzy_thresh,
        "quality_cutoff": quality_cutoff,
        "dry_run": dry_run,
        "token": token_input,
        "portal_id": portal_id,
        "enrich": enrich_enabled,
        "ui_mode": ui_mode,
    }


def render_header_and_tenant_bar(config: Dict[str, Any]) -> None:
    """Render RevOpsBolt top header with monospace diagnostic tags and status pills."""
    portal_label = config.get("portal_id", "default_portal")
    is_dry_run = config.get("dry_run", True)
    is_connected = st.session_state.get("hubspot_connected", False)
    quota = get_enrichment_quota(portal_label)
    used = quota["used"]
    limit = quota["limit"]

    # Status Pill Badges
    if is_connected:
        portal_badge = f'<span class="bolt-pill-badge bolt-pill-connected"><span class="bolt-pulse-dot bolt-dot-green"></span> PORTAL CONNECTED: {portal_label}</span>'
    else:
        portal_badge = f'<span class="bolt-pill-badge bolt-pill-disconnected"><span class="bolt-pulse-dot bolt-dot-gray"></span> PORTAL: {portal_label}</span>'

    if is_dry_run:
        dry_badge = '<span class="bolt-pill-badge bolt-pill-dryrun"><span class="bolt-pulse-dot bolt-dot-orange"></span> DRY-RUN ACTIVE</span>'
    else:
        dry_badge = '<span class="bolt-pill-badge bolt-pill-live"><span class="bolt-pulse-dot bolt-dot-red"></span> LIVE SYNC ACTIVE</span>'

    quota_badge = f'<span class="bolt-pill-badge bolt-pill-quota"><span class="bolt-pulse-dot bolt-dot-neon"></span> FREEMIUM QUOTA: {used}/{limit} USED</span>'

    st.markdown(
        f"""
        <div class="bolt-header-card">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px;">
                <div>
                    <div class="bolt-diagnostic-tag">// DIAGNOSTIC SUITE 02 - LEAD ENGINE</div>
                    <h1 class="bolt-title">RevOpsBolt // Lead Hygiene & CRM Pipeline</h1>
                    <p class="bolt-subtext">
                        // REVOPS SYSTEM KERNEL v2.4 // INDIAN SME ENGINE (+91 E.164, PIN & GST VERIFICATION)
                    </p>
                </div>
                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:8px;">
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        {portal_badge}
                        {dry_badge}
                        {quota_badge}
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_audit_modal() -> None:
    """Render SQLite audit database runs in an expander/dialog."""
    if st.session_state.get("show_db_modal"):
        st.info("### 📜 SQLite Execution History (`leads_audit.db`)")
        try:
            if Path(DEFAULT_DB_PATH).exists():
                with get_connection(DEFAULT_DB_PATH) as conn:
                    runs_df = pd.read_sql_query(
                        "SELECT run_id, timestamp, file_name, total_rows, cleaned_rows, review_rows, dry_run, status FROM runs ORDER BY timestamp DESC LIMIT 10",
                        conn,
                    )
                if not runs_df.empty:
                    st.dataframe(runs_df, use_container_width=True)
                else:
                    st.write("No previous runs logged yet.")
            else:
                st.write("Audit database not yet created.")
        except Exception as e:
            st.error(f"Error accessing database: {e}")

        if st.button("Close Audit Inspector"):
            st.session_state.show_db_modal = False
            st.rerun()


@st.dialog("🏢 RevOpsBolt Data Sync & Architecture Guide", width="large")
def show_marketplace_guide_dialog() -> None:
    """Render comprehensive marketplace setup guide, shared data matrix, and security specs."""
    st.markdown(
        """
        <div style="margin-bottom:14px; display:flex; gap:8px; flex-wrap:wrap;">
            <span class="bolt-pill-badge bolt-pill-quota">REVOPS ARCHITECTURE</span>
            <span class="bolt-pill-badge bolt-pill-connected">NON-DESTRUCTIVE SYNC</span>
            <span class="bolt-pill-badge bolt-pill-dryrun">v2.4 ENTERPRISE KERNEL</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("// DIAGNOSTIC TELEMETRY: Enterprise RevOps data governance, E.164 standardization, and sub-10-minute time-to-value.")

    guide_tab1, guide_tab2, guide_tab3, guide_tab4 = st.tabs(
        [
            "⚡ Quickstart Workflow",
            "🔄 Shared Data Matrix",
            "🔑 API Permissions",
            "🛡️ Overwrite Policy",
        ]
    )

    with guide_tab1:
        st.markdown("#### ⚡ 10-Minute Time-to-Value Setup")
        st.markdown(
            """
            1. **Step 1: Connect your HubSpot Account**  
               - Enter your **Private App Token** and click **Connect**.
               - The app securely calls `GET /account-info/v3/details` to fetch and verify your Portal ID.
            2. **Step 2: Choose Data Ingestion Source**  
               - **Option A (Vendor Spreadsheets):** Upload pre-CRM CSV/Excel files from WhatsApp, expos, or lead ads.
               - **Option B (Direct CRM Sync):** Pull live contacts, companies, and deals directly from HubSpot via API.
            3. **Step 3: Run Pre-Flight Diagnostics & Hygiene**  
               - Standardizes Indian mobile numbers into E.164 `+91XXXXXXXXXX`.
               - Validates 6-digit postal PIN codes and cross-matches GSTIN state codes.
               - Identifies fuzzy duplicates using RapidFuzz Token-Sort ratio with auto-merge backfills.
            4. **Step 4: Non-Destructive Push & Native Duplicate Merge**  
               - Test with **Dry-Run Mode Enabled** (zero real mutations) to inspect simulated payloads.
               - Push clean leads to HubSpot or merge duplicates via native `POST /crm/v3/objects/contacts/merge`.
            """
        )

    with guide_tab2:
        st.markdown("#### 🔄 Shared Data & Property Mapping Matrix")
        shared_data = [
            {"Data Object": "Contact Mobile", "Source Field": "phone / mobile", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "phone (+91 E.164)", "Policy": "Enrich if blank / Standardize"},
            {"Data Object": "Contact Email", "Source Field": "email", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "email (RFC 5322)", "Policy": "Primary deduplication key"},
            {"Data Object": "First & Last Name", "Source Field": "full_name / first_name", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "firstname, lastname", "Policy": "Auto-split & title-case"},
            {"Data Object": "Company Name", "Source Field": "company", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "company", "Policy": "Associated or created"},
            {"Data Object": "City & State", "Source Field": "city, state", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "city, state", "Policy": "Standardized alias map"},
            {"Data Object": "Postal Code", "Source Field": "pin_code", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "zip", "Policy": "Validated 6-digit prefix"},
            {"Data Object": "GSTIN Tax ID", "Source Field": "gst_number", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "gst_number (custom)", "Policy": "State checksum verified"},
            {"Data Object": "AI Extracted Intent", "Source Field": "notes_structured", "Sync Direction": "Ingest ➔ HubSpot CRM", "HubSpot Property": "hs_note_body / notes", "Policy": "Gemini Flash budget/intent"},
            {"Data Object": "Duplicate Merges", "Source Field": "proposals_df", "Sync Direction": "Two-way (Native API)", "HubSpot Property": "contacts/merge endpoint", "Policy": "Consolidates secondary into primary"},
        ]
        st.dataframe(pd.DataFrame(shared_data), use_container_width=True)

    with guide_tab3:
        st.markdown("#### 🔑 Required HubSpot Account Scopes & Permissions")
        st.markdown(
            """
            | Scope | Permission Type | Rationale |
            | :--- | :---: | :--- |
            | `crm.objects.contacts.read` | Read | Fetch contacts to scan hygiene and deduplicate |
            | `crm.objects.contacts.write` | Write | Push standardized numbers, emails, and GSTINs |
            | `crm.objects.companies.read` | Read | Read associated company details for B2B accounts |
            | `crm.objects.companies.write` | Write | Link contacts to existing company records |
            | `crm.schemas.custom.read` | Read | Inspect custom fields like `gst_number` |
            """
        )

    with guide_tab4:
        st.markdown("#### 🛡️ Non-Destructive Safety & Overwrite Policy")
        st.markdown(
            """
            - **Never Overwrites Existing Valid Data:** If a contact already has a valid phone or email in HubSpot, our engine preserves it unless `overwrite=True` is explicitly instructed.
            - **Fills Property Gaps:** Blank fields are enriched and backfilled non-destructively.
            - **Safety-First Dry-Run Default:** All CRM sync operations simulate the exact API payloads in Dry-Run mode before live execution.
            - **Native CRM Merges:** Duplicate pairs use HubSpot's official merge endpoint (`/crm/v3/objects/contacts/merge`), preserving sales history, email engagements, and deal associations.
            """
        )

    if st.button("Close Guide", type="primary"):
        st.session_state.show_marketplace_modal = False
        st.rerun()


def run_dataframe_pipeline(
    df: pd.DataFrame,
    source_name: str,
    fuzzy_thresh: int,
    quality_cutoff: int,
    dry_run: bool,
    enrich: bool = False,
    portal_id: Optional[str] = "default_portal",
) -> Dict[str, Any]:
    """Execute pipeline on an ingested DataFrame (from either CSV or direct HubSpot API)."""
    run_id = str(uuid.uuid4())
    total_loaded = len(df)

    # Step 2 & 3: Normalization and Validation
    validated_df = validate_dataframe(df)

    # Step 4: Deduplication & Exact Merge
    deduped_df, proposals_df = deduplicate_leads(
        validated_df,
        fuzzy_threshold=fuzzy_thresh,
        auto_merge_exact=True,
    )

    # Step 4.5: Optional Cloud LLM Enrichment with Quota Guard
    deduped_df, quota_summary = enrich_dataframe(
        deduped_df,
        enabled=enrich,
        portal_id=portal_id or "default_portal",
    )

    # Step 5: Routing with custom quality score cutoff
    for idx in deduped_df.index:
        issues = deduped_df.at[idx, "issues"] or []
        if isinstance(issues, str):
            issue_list = [i.strip() for i in issues.split(",") if i.strip()]
        elif isinstance(issues, list):
            issue_list = list(issues)
        else:
            issue_list = []

        score = deduped_df.at[idx, "quality_score"]
        has_fatal = any(f in issue_list for f in FATAL_ISSUES)
        is_fuzzy = "duplicate_fuzzy_review" in issue_list

        if score < quality_cutoff or has_fatal or is_fuzzy:
            deduped_df.at[idx, "route"] = "review"
            deduped_df.at[idx, "needs_review"] = True
        else:
            deduped_df.at[idx, "route"] = "cleaned"
            deduped_df.at[idx, "needs_review"] = False

    cleaned_df = deduped_df[deduped_df["route"] == "cleaned"].copy()
    review_df = deduped_df[deduped_df["route"] == "review"].copy()

    # Step 6: Batch stats and Report
    batch_stats = generate_summary_stats(deduped_df)
    report_md = generate_markdown_report(batch_stats, output_path=None)

    # Step 7: Audit Logging
    try:
        log_run(
            run_id=run_id,
            file_name=source_name,
            file_hash="",
            total_rows=total_loaded,
            cleaned_rows=len(cleaned_df),
            review_rows=len(review_df),
            dry_run=dry_run,
            status="completed",
            portal_id=portal_id,
        )
        log_record_audits(run_id=run_id, records=deduped_df, portal_id=portal_id)
        if not proposals_df.empty:
            log_merge_proposals(run_id=run_id, proposals=proposals_df, portal_id=portal_id)
    except Exception as e:
        st.warning(f"Note: Could not log to SQLite audit database: {e}")

    return {
        "run_id": run_id,
        "portal_id": portal_id,
        "file_name": source_name,
        "raw_df": df,
        "deduped_df": deduped_df,
        "cleaned_df": cleaned_df,
        "review_df": review_df,
        "proposals_df": proposals_df,
        "stats": batch_stats,
        "report_md": report_md,
        "quota_summary": quota_summary,
    }


def run_in_memory_pipeline(
    file_bytes: bytes,
    file_name: str,
    fuzzy_thresh: int,
    quality_cutoff: int,
    dry_run: bool,
    enrich: bool = False,
    portal_id: Optional[str] = "default_portal",
) -> Dict[str, Any]:
    """Execute pipeline from uploaded file bytes."""
    raw_df = load_and_map(file_bytes, filename=file_name)
    return run_dataframe_pipeline(
        df=raw_df,
        source_name=file_name,
        fuzzy_thresh=fuzzy_thresh,
        quality_cutoff=quality_cutoff,
        dry_run=dry_run,
        enrich=enrich,
        portal_id=portal_id,
    )


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convert dataframe to downloadable CSV bytes."""
    export_df = df.copy()
    if "issues" in export_df.columns:
        export_df["issues"] = export_df["issues"].apply(
            lambda x: ", ".join(x) if isinstance(x, (list, tuple, set)) else str(x or "")
        )
    return export_df.to_csv(index=False).encode("utf-8")


def _execute_hubspot_sync(
    cleaned_df: pd.DataFrame,
    config: Dict[str, Any],
    is_dry_run: bool,
) -> None:
    """Execute HubSpot synchronization with progress bar and summary table."""
    try:
        client = HubSpotClient(
            token=config.get("token"),
            portal_id=config.get("portal_id"),
            dry_run=is_dry_run,
            overwrite=False,
        )

        progress_bar = st.progress(0)
        status_text = st.empty()

        results_list = []
        counts = {"created": 0, "updated": 0, "no_op": 0, "failed": 0}

        total = len(cleaned_df)
        for i, (_, row) in enumerate(cleaned_df.iterrows()):
            status_text.text(f"Syncing contact {i+1} of {total}: {row.get('first_name', '')} ({row.get('email', '')})...")
            res = client.upsert_contact(row)
            action = res.get("action", "")
            if "CREATE" in action:
                counts["created"] += 1
            elif "UPDATE" in action:
                counts["updated"] += 1
            elif action == "NO_OP":
                counts["no_op"] += 1

            results_list.append(res)
            progress_bar.progress((i + 1) / total)

        status_text.empty()
        progress_bar.empty()

        st.success(f"🎉 HubSpot sync completed ({'Dry-Run Simulation' if is_dry_run else 'Live Push'})!")

        col_c, col_u, col_n, col_f = st.columns(4)
        col_c.metric("Created", counts["created"])
        col_u.metric("Updated (Non-destructive)", counts["updated"])
        col_n.metric("Already Up-to-date (No-op)", counts["no_op"])
        col_f.metric("Failed", counts["failed"])

        if client.audit_log:
            with st.expander("🔍 View CRM Sync Audit Log", expanded=False):
                st.dataframe(pd.DataFrame(client.audit_log), use_container_width=True)

    except ConfigurationError as ce:
        st.error(f"Configuration error: {ce}")
    except Exception as e:
        st.error(f"HubSpot sync failed: {e}")


def _render_ingestion_controls(config: Dict[str, Any]) -> None:
    """Render Dual-Mode Ingestion (Option A: Vendor Spreadsheets vs Option B: Direct CRM Sync)."""
    with st.container():
        st.markdown("### // LEAD INGESTION SUBSYSTEM")
        intake_mode = st.segmented_control(
            "Select Ingestion Pipeline:",
            options=["📂 Ingest Vendor Leads (CSV / Excel)", "🔄 Direct CRM Hygiene (Fetch from HubSpot)"],
            default="📂 Ingest Vendor Leads (CSV / Excel)",
            help="Choose between staging vendor spreadsheets or running hygiene directly on your HubSpot database.",
        )
        if not intake_mode:
            intake_mode = "📂 Ingest Vendor Leads (CSV / Excel)"

        if intake_mode == "📂 Ingest Vendor Leads (CSV / Excel)":
            uploaded_file = st.file_uploader(
                "Upload Raw Leads Spreadsheet (.csv, .xlsx, .xls)",
                type=["csv", "xlsx", "xls"],
                help="Drop pre-CRM exports from trade expos, WhatsApp, Meta Lead Ads, or offline sales reps.",
            )

            if uploaded_file is not None:
                file_bytes = uploaded_file.getvalue()
                file_size_kb = round(len(file_bytes) / 1024, 1)

                if st.session_state.active_file_name != uploaded_file.name:
                    st.session_state.pipeline_results = None
                    st.session_state.sync_results = None
                    st.session_state.active_file_name = uploaded_file.name

                col_meta1, col_meta2 = st.columns([3, 1])
                with col_meta1:
                    st.caption(f"📄 **Staged File:** `{uploaded_file.name}` ({file_size_kb} KB)")
                with col_meta2:
                    if st.session_state.pipeline_results is None:
                        if st.button("🚀 Audit & Clean File", type="primary", use_container_width=True):
                            with st.spinner("Processing through normalization, validation, and deduplication..."):
                                try:
                                    results = run_in_memory_pipeline(
                                        file_bytes=file_bytes,
                                        file_name=uploaded_file.name,
                                        fuzzy_thresh=config["fuzzy_threshold"],
                                        quality_cutoff=config["quality_cutoff"],
                                        dry_run=config["dry_run"],
                                        enrich=config.get("enrich", False),
                                        portal_id=config.get("portal_id", "default_portal"),
                                    )
                                    st.session_state.pipeline_results = results
                                    st.success("✅ File hygiene analysis complete!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Processing failed: {e}")

        else:
            # Direct HubSpot CRM Sync Mode
            st.info("🔗 **DIRECT CRM MODE:** Live stream contacts via API, apply E.164 normalization, PIN validation, GST checksums, and detect duplicate clusters.")

            col_h1, col_h2 = st.columns([3, 1])
            with col_h1:
                fetch_limit = st.slider("Maximum Contacts to Scan", min_value=50, max_value=500, value=250, step=50)

            is_connected = st.session_state.get("hubspot_connected", False)
            with col_h2:
                if not is_connected:
                    st.button("Fetch & Audit CRM Contacts", type="primary", disabled=True, use_container_width=True)
                    st.caption("⚠️ Connect to HubSpot in sidebar first")
                else:
                    if st.button("Fetch & Audit CRM Contacts", type="primary", use_container_width=True):
                        with st.spinner("Fetching live contacts from HubSpot and running hygiene engine..."):
                            try:
                                client = HubSpotClient(
                                    token=config.get("token"),
                                    portal_id=config.get("portal_id"),
                                    dry_run=config["dry_run"],
                                )
                                raw_contacts = client.fetch_contacts(max_records=fetch_limit)
                                if not raw_contacts:
                                    st.warning("No contacts found in HubSpot or mock empty.")
                                else:
                                    crm_df = client.contacts_to_dataframe(raw_contacts)
                                    source_label = f"HubSpot_Portal_{config.get('portal_id', 'CRM')}_Contacts"
                                    results = run_dataframe_pipeline(
                                        df=crm_df,
                                        source_name=source_label,
                                        fuzzy_thresh=config["fuzzy_threshold"],
                                        quality_cutoff=config["quality_cutoff"],
                                        dry_run=config["dry_run"],
                                        enrich=config.get("enrich", False),
                                        portal_id=config.get("portal_id", "default_portal"),
                                    )
                                    st.session_state.pipeline_results = results
                                    st.session_state.active_file_name = source_label
                                    st.success(f"✅ Successfully fetched {len(raw_contacts)} contacts and executed pipeline!")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"❌ Failed to fetch from HubSpot: {e}")


def render_contact_inspection_flyout(df: pd.DataFrame, config: Dict[str, Any]) -> None:
    """Render the HubSpot Contact Inspection Flyout Card (Raw vs Canonical, Link, & AI Intent)."""
    with st.expander("🔍 // CONTACT INSPECTION TELEMETRY", expanded=False):
        if df.empty:
            st.info("No records to inspect.")
            return

        contact_options = []
        for idx, row in df.head(100).iterrows():
            name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip() or "Unnamed"
            email = row.get("email") or "No email"
            phone = row.get("phone") or "No phone"
            contact_options.append(f"{name} | {email} | {phone} [Idx: {idx}]")

        selected_opt = st.selectbox("Select Contact to Inspect:", options=contact_options, key="flyout_selector")
        sel_idx = int(selected_opt.split("[Idx: ")[-1].replace("]", ""))
        rec = df.loc[sel_idx]

        portal_id = config.get("portal_id", "default_portal")
        hs_id = rec.get("hubspot_contact_id") or rec.get("id") or "1001"

        col_f1, col_f2 = st.columns([1, 1])
        with col_f1:
            st.markdown(f"#### 👤 {rec.get('first_name', '')} {rec.get('last_name', '')}")
            st.markdown(f"🔗 **HubSpot Contact ID:** `{hs_id}` &nbsp;&nbsp; [Open in HubSpot](https://app.hubspot.com/contacts/{portal_id}/contact/{hs_id})")

            # Field comparison table
            comp_rows = [
                {"Field": "Phone Number", "Raw Value": rec.get("raw_phone") or rec.get("raw_Mobile Number") or "-", "Canonical Value": rec.get("phone") or "-"},
                {"Field": "Email Address", "Raw Value": rec.get("raw_email") or rec.get("raw_Email") or "-", "Canonical Value": rec.get("email") or "-"},
                {"Field": "City / Location", "Raw Value": rec.get("raw_city") or "-", "Canonical Value": rec.get("city") or "-"},
                {"Field": "GSTIN Tax ID", "Raw Value": rec.get("raw_gst_number") or "-", "Canonical Value": rec.get("gst_number") or "-"},
            ]
            st.dataframe(pd.DataFrame(comp_rows), use_container_width=True)

        with col_f2:
            st.markdown("#### 🤖 AI Note Extraction")
            notes_struct = rec.get("notes_structured")
            if notes_struct:
                st.json(notes_struct if isinstance(notes_struct, dict) else str(notes_struct))
            else:
                st.info("No AI extracted note attributes for this contact. Enable Cloud LLM Enrichment to extract budget and buying intent.")

            # Quality Score
            score = rec.get("quality_score", 0)
            score_color = "#00A389" if score >= 80 else ("#FF8800" if score >= 70 else "#FF4D4D")
            st.markdown(f"**Hygiene Score:** <span style='color:{score_color}; font-weight:800; font-size:1.1rem;'>{score:.0f} / 100</span>", unsafe_allow_html=True)
            issues = rec.get("issues", [])
            if issues:
                st.caption(f"Issues: `{', '.join(issues) if isinstance(issues, list) else issues}`")


def render_leadfeeder_tabs(results: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Render the primary 4-tab workspace."""
    stats = results["stats"]
    cleaned_df = results["cleaned_df"]
    review_df = results["review_df"]
    proposals_df = results["proposals_df"]
    deduped_df = results["deduped_df"]

    tab_contacts, tab_merges, tab_review, tab_audit = st.tabs(
        [
            f"Contacts & Leads ({len(cleaned_df)})",
            f"Duplicate Clusters & Merges ({len(proposals_df)})",
            f"Review Queue ({len(review_df)})",
            "Audit & Executive Summary",
        ]
    )

    with tab_contacts:
        # Toolbar actions
        col_t1, col_t2, col_t3 = st.columns([2, 1, 1])
        with col_t1:
            score_filter = st.radio(
                "Filter Quality:",
                options=["All Ready", "High Confidence (>=85)", "Standard (70-84)"],
                horizontal=True,
            )
        with col_t2:
            st.download_button(
                "📥 Export Cleaned CSV",
                data=to_csv_bytes(cleaned_df),
                file_name="cleaned_leads.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_t3:
            sync_btn_label = "⚡ Sync Patches (Dry-Run)" if config["dry_run"] else "⚡ Sync Patches (Live)"
            if st.button(sync_btn_label, type="primary", use_container_width=True):
                _execute_hubspot_sync(cleaned_df, config, is_dry_run=config["dry_run"])

        display_cleaned = cleaned_df
        if score_filter == "High Confidence (>=85)":
            display_cleaned = display_cleaned[display_cleaned["quality_score"] >= 85]
        elif score_filter == "Standard (70-84)":
            display_cleaned = display_cleaned[(display_cleaned["quality_score"] >= 70) & (display_cleaned["quality_score"] < 85)]

        if not display_cleaned.empty:
            cols_to_show = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "gst_number", "quality_score"] if c in display_cleaned.columns]
            st.dataframe(display_cleaned[cols_to_show], use_container_width=True)
        else:
            st.info("No leads match the selected filter.")

        # Inspection Flyout
        render_contact_inspection_flyout(cleaned_df, config)

    with tab_merges:
        st.markdown("#### // DUPLICATE CLUSTERS & NATIVE MERGE CONSOLIDATION")
        st.caption("Exact phone/email duplicates are consolidated automatically into the primary record with backfilled properties. Fuzzy name matches require confirmation.")

        if not proposals_df.empty:
            # Action bar
            col_m_info, col_m_btn = st.columns([3, 1])
            with col_m_info:
                st.markdown(f"Detected **{len(proposals_df)} duplicate clusters**.")
            with col_m_btn:
                merge_label = "⚡ Consolidate / Merge in HubSpot"
                if st.button(merge_label, type="primary", use_container_width=True):
                    with st.spinner("Executing HubSpot native contact merges..."):
                        try:
                            client = HubSpotClient(
                                token=config.get("token"),
                                portal_id=config.get("portal_id"),
                                dry_run=config["dry_run"],
                            )
                            merge_records = proposals_df.to_dict(orient="records")
                            res_list = client.merge_duplicate_clusters(merge_records, portal_id=config.get("portal_id"))
                            successful = sum(1 for r in res_list if r.get("status") in {"success", "dry_run"})
                            st.success(f"🎉 Processed {successful} merge pairs ({'Dry-Run Simulation' if config['dry_run'] else 'Executed'})!")
                            with st.expander("View Merge Audit", expanded=True):
                                st.dataframe(pd.DataFrame(res_list), use_container_width=True)
                        except Exception as e:
                            st.error(f"Failed to merge contacts: {e}")

            st.dataframe(proposals_df, use_container_width=True)
        else:
            st.success("🎉 Zero duplicate clusters found in this dataset!")

    with tab_review:
        st.markdown("#### // FLAGGED RECORDS (REQUIRES REVIEW)")
        st.caption("Leads routed here due to invalid mobile formats, unmapped cities, GST state code mismatches, or missing marketing consent.")

        col_r1, col_r2 = st.columns([3, 1])
        with col_r2:
            st.download_button(
                "📥 Export Review Queue CSV",
                data=to_csv_bytes(review_df),
                file_name="review_queue.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if not review_df.empty:
            review_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "issues", "quality_score"] if c in review_df.columns]
            st.dataframe(review_df[review_cols], use_container_width=True)
            render_contact_inspection_flyout(review_df, config)
        else:
            st.success("🎉 Zero leads flagged for review! 100% passed hygiene.")

    with tab_audit:
        st.markdown("#### // HYGIENE KPIS & EXECUTIVE SUMMARY")
        
        tot = stats["total_rows"]
        pass_pct = stats.get("cleaned_pct", 0.0)
        review_pct = stats.get("review_pct", 0.0)
        avg_score = stats.get("avg_quality_score", 0.0)

        # High-Contrast KPI Metric Cards with colored rating numbers
        score_color = "#00A389" if avg_score >= 80 else ("#FF8800" if avg_score >= 70 else "#FF4D4D")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"""
                <div class="bolt-kpi-card">
                    <div class="bolt-kpi-title">TOTAL PROCESSED</div>
                    <div class="bolt-kpi-val" style="color:#E6EDF3;">{tot}</div>
                    <div class="bolt-kpi-desc">Ingested lead records</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div class="bolt-kpi-card">
                    <div class="bolt-kpi-title">HYGIENE PASS RATE</div>
                    <div class="bolt-kpi-val" style="color:#00A389;">{pass_pct}%</div>
                    <div class="bolt-kpi-desc">{len(cleaned_df)} approved leads</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
                <div class="bolt-kpi-card">
                    <div class="bolt-kpi-title">REVIEW RATE</div>
                    <div class="bolt-kpi-val" style="color:#FF8800;">{review_pct}%</div>
                    <div class="bolt-kpi-desc">{len(review_df)} flagged leads</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f"""
                <div class="bolt-kpi-card">
                    <div class="bolt-kpi-title">AVG QUALITY SCORE</div>
                    <div class="bolt-kpi-val" style="color:{score_color};">{avg_score:.1f}</div>
                    <div class="bolt-kpi-desc">Out of 100 benchmark</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.markdown("#### Analytical Markdown Audit Report")
        st.markdown(results["report_md"])


def main() -> None:
    init_session_state()
    inject_custom_css()

    config = render_sidebar()
    render_audit_modal()
    if st.session_state.get("show_marketplace_modal"):
        show_marketplace_guide_dialog()

    # Top Header & Tenant Utility Bar
    render_header_and_tenant_bar(config)

    ui_mode = config.get("ui_mode", "classic")

    if ui_mode == "mixed":
        render_mixed_dashboard(
            results=st.session_state.pipeline_results,
            config=config,
            run_pipeline_fn=run_in_memory_pipeline,
        )

        st.markdown("---")
        with st.expander("📥 Ingest Leads & Direct CRM Sync", expanded=(st.session_state.pipeline_results is None)):
            _render_ingestion_controls(config)
        return

    # Classic / Leadfeeder Primary Views
    _render_ingestion_controls(config)

    results = st.session_state.pipeline_results
    if results is not None:
        st.markdown("---")
        render_leadfeeder_tabs(results, config)


if __name__ == "__main__":
    main()
