"""Streamlit Web Application for Lead Cleaner & RevOps Pipeline.

Modern Linear / Vercel Dark Mode:
- Deep charcoal slate canvas (#0E121B) and elevated surfaces (#141824)
- Hairline subtle borders (#222938 / rgba(255, 255, 255, 0.08))
- Linear indigo primary accent (#5E6AD2) with crisp typography
- Sleek, refined rectangular buttons (radius: 6px) with zero neon glow
- Minimalist status chips (Portal Connected, Dry-Run Active, Freemium Quota)
- Non-destructive safety default (dry_run=True) and SQLite audit tracking
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
from hubspot.connection import (
    HubSpotOAuthProvider,
    handle_oauth_callback,
    validate_and_connect,
)

# Page Configuration
st.set_page_config(
    page_title="Lead Cleaner & RevOps Pipeline",
    page_icon="✨",
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
    if "hubspot_domain" not in st.session_state:
        st.session_state.hubspot_domain = None
    if "hubspot_user" not in st.session_state:
        st.session_state.hubspot_user = None
    if "hubspot_token" not in st.session_state:
        st.session_state.hubspot_token = None
    if "show_marketplace_modal" not in st.session_state:
        st.session_state.show_marketplace_modal = False
    if "show_db_modal" not in st.session_state:
        st.session_state.show_db_modal = False
    if "selected_contact_id" not in st.session_state:
        st.session_state.selected_contact_id = 0


def inject_custom_css() -> None:
    """Inject Modern Linear / Vercel Dark Mode styling."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

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
            --bg-canvas: #0E121B;
            --bg-sidebar: #0A0D14;
            --bg-surface: #141824;
            --bg-surface-elevated: #181D2A;
            --border-subtle: #222938;
            --border-strong: #2D3748;
            --accent-primary: #5E6AD2;
            --accent-primary-hover: #6E7BE2;
            --accent-green: #10B981;
            --accent-amber: #F59E0B;
            --accent-red: #EF4444;
            --text-primary: #F1F5F9;
            --text-secondary: #94A3B8;
            --text-muted: #64748B;
        }

        /* Deep Charcoal Slate Canvas */
        .stApp {
            background-color: var(--bg-canvas) !important;
            color: var(--text-primary) !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background-color: var(--bg-sidebar) !important;
            border-right: 1px solid var(--border-subtle) !important;
        }
        section[data-testid="stSidebar"] > div {
            background-color: var(--bg-sidebar) !important;
        }
        section[data-testid="stSidebar"] .stMarkdown h3 {
            color: var(--text-primary) !important;
            font-size: 0.95rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.02em !important;
        }
        section[data-testid="stSidebar"] .stMarkdown h4 {
            color: var(--text-secondary) !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
            margin-top: 14px !important;
        }

        /* Linear Top Header Card */
        .linear-header-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            padding: 20px 24px;
            margin-bottom: 22px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        }
        .linear-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(94, 106, 210, 0.12);
            border: 1px solid rgba(94, 106, 210, 0.25);
            color: #A5B4FC;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            margin-bottom: 8px;
        }
        .linear-title {
            color: #FFFFFF;
            font-size: 1.6rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin: 0 0 4px 0;
            line-height: 1.25;
        }
        .linear-subtitle {
            color: var(--text-secondary);
            font-size: 0.86rem;
            margin: 0;
            line-height: 1.4;
        }

        /* Subtle Status Chips */
        .linear-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-subtle);
            color: var(--text-secondary);
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 500;
            white-space: nowrap;
        }
        .linear-chip-green {
            background: rgba(16, 185, 129, 0.08);
            border-color: rgba(16, 185, 129, 0.25);
            color: #34D399;
        }
        .linear-chip-amber {
            background: rgba(245, 158, 11, 0.08);
            border-color: rgba(245, 158, 11, 0.25);
            color: #FBBF24;
        }
        .linear-chip-indigo {
            background: rgba(94, 106, 210, 0.1);
            border-color: rgba(94, 106, 210, 0.25);
            color: #A5B4FC;
        }
        .linear-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
        }
        .linear-dot-green { background: #10B981; }
        .linear-dot-amber { background: #F59E0B; }
        .linear-dot-indigo { background: #5E6AD2; }
        .linear-dot-gray { background: #64748B; }

        /* Modern Linear Metric Cards */
        .linear-metric-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 16px 20px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18);
            transition: border-color 0.15s ease;
        }
        .linear-metric-card:hover {
            border-color: var(--border-strong);
        }
        .linear-metric-title {
            color: var(--text-secondary);
            font-size: 0.74rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }
        .linear-metric-val {
            font-size: 1.85rem;
            font-weight: 700;
            line-height: 1.15;
            color: #FFFFFF;
        }
        .linear-metric-desc {
            color: var(--text-muted);
            font-size: 0.74rem;
            margin-top: 4px;
        }

        /* Restyle st.metric */
        div[data-testid="stMetric"] {
            background-color: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: 8px !important;
            padding: 16px 18px !important;
        }
        div[data-testid="stMetricLabel"] {
            color: var(--text-secondary) !important;
            font-size: 0.74rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
        }
        div[data-testid="stMetricValue"] {
            color: #FFFFFF !important;
            font-size: 1.85rem !important;
            font-weight: 700 !important;
        }

        /* Sleek Linear Rectangular Buttons (Radius 6px) */
        button[kind="primary"], div.stButton > button[kind="primary"] {
            background: var(--accent-primary) !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            color: #FFFFFF !important;
            font-weight: 600 !important;
            font-size: 0.84rem !important;
            border-radius: 6px !important;
            padding: 7px 18px !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
            transition: all 0.15s ease !important;
        }
        button[kind="primary"]:hover, div.stButton > button[kind="primary"]:hover {
            background: var(--accent-primary-hover) !important;
            box-shadow: 0 2px 8px rgba(94, 106, 210, 0.35) !important;
        }

        button[kind="secondary"], div.stButton > button[kind="secondary"] {
            background: var(--bg-surface-elevated) !important;
            border: 1px solid var(--border-subtle) !important;
            color: var(--text-primary) !important;
            font-weight: 500 !important;
            font-size: 0.82rem !important;
            border-radius: 6px !important;
            padding: 7px 16px !important;
            transition: all 0.15s ease !important;
        }
        button[kind="secondary"]:hover, div.stButton > button[kind="secondary"]:hover {
            border-color: var(--border-strong) !important;
            background: #202738 !important;
            color: #FFFFFF !important;
        }

        div.stDownloadButton > button {
            background: var(--bg-surface-elevated) !important;
            border: 1px solid var(--border-subtle) !important;
            color: var(--text-primary) !important;
            font-weight: 500 !important;
            font-size: 0.82rem !important;
            border-radius: 6px !important;
            padding: 7px 16px !important;
            transition: all 0.15s ease !important;
        }
        div.stDownloadButton > button:hover {
            border-color: var(--accent-primary) !important;
            color: #FFFFFF !important;
        }

        /* Clean Linear Tabs */
        div[data-testid="stTabs"] {
            border-bottom: 1px solid var(--border-subtle) !important;
            margin-bottom: 18px !important;
        }
        div[data-testid="stTabs"] button {
            color: var(--text-secondary) !important;
            font-size: 0.86rem !important;
            font-weight: 500 !important;
            padding: 10px 18px !important;
            border-bottom: 2px solid transparent !important;
            transition: all 0.15s ease !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: #FFFFFF !important;
            border-bottom: 2px solid var(--accent-primary) !important;
            background: rgba(94, 106, 210, 0.05) !important;
        }
        div[data-testid="stTabs"] button:hover {
            color: #FFFFFF !important;
        }

        /* Dataframe & Tables */
        div[data-testid="stDataFrame"] {
            background-color: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: 8px !important;
            overflow: hidden !important;
        }

        /* Progress Bar */
        div[data-testid="stProgress"] > div > div > div {
            background: var(--accent-primary) !important;
        }
        div[data-testid="stProgress"] > div > div {
            background-color: #1A2130 !important;
            border-radius: 4px !important;
        }

        /* Inputs & Form Controls */
        div[data-baseweb="input"], div[data-baseweb="base-input"] {
            background-color: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            color: var(--text-primary) !important;
            border-radius: 6px !important;
        }
        div[data-baseweb="input"]:focus-within {
            border-color: var(--accent-primary) !important;
        }
        div[data-baseweb="select"] > div {
            background-color: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            color: var(--text-primary) !important;
            border-radius: 6px !important;
        }
        div[data-testid="stSegmentedControl"] {
            background-color: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: 6px !important;
            padding: 3px !important;
        }
        div[data-testid="stSegmentedControl"] button[data-checked="true"] {
            background: var(--accent-primary) !important;
            color: #FFFFFF !important;
            border-radius: 4px !important;
        }
        div[data-testid="stExpander"] {
            background-color: var(--bg-surface) !important;
            border: 1px solid var(--border-subtle) !important;
            border-radius: 8px !important;
        }

        /* Sidebar Quota Box */
        .linear-quota-box {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 12px 14px;
            margin-top: 8px;
            margin-bottom: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> Dict[str, Any]:
    """Render sidebar configuration controls, HubSpot connection, and quota viewer."""
    st.sidebar.markdown("### Settings & Preferences")

    st.sidebar.markdown("#### Matching & Quality Cutoffs")
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
    st.sidebar.markdown("#### CRM Safety Mode")
    dry_run = st.sidebar.checkbox(
        "Enable Dry-Run Safety Mode",
        value=True,
        help="When checked, simulates HubSpot API calls without modifying real CRM data.",
    )

    if dry_run:
        st.sidebar.caption("🟢 **Dry-Run Active (Simulation Mode)**")
    else:
        st.sidebar.warning("⚠️ **Live Mode Active (Real CRM Mutations)**")

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### HubSpot Authentication")
    is_connected = st.session_state.get("hubspot_connected", False)
    active_portal = st.session_state.get("hubspot_portal_id")

    env_token = get_token_from_env()
    if "hubspot_token_input_field" not in st.session_state:
        st.session_state.hubspot_token_input_field = st.session_state.get("hubspot_token") or env_token or ""

    token_input = st.sidebar.text_input(
        "HubSpot Private App Token",
        type="password",
        key="hubspot_token_input_field",
        help="HubSpot Private App Token (starts with pat-). Defaults to .env if configured.",
    )

    if not is_connected:
        if st.sidebar.button("Connect to HubSpot", type="primary", use_container_width=True, key="hs_connect_btn"):
            if not token_input.strip():
                st.sidebar.error("Please enter a token first.")
            else:
                with st.sidebar.spinner("Validating with HubSpot API..."):
                    ok, portal_id_res, err_msg = validate_and_connect(token_input.strip())
                    if ok:
                        st.session_state.hubspot_connected = True
                        st.session_state.hubspot_portal_id = str(portal_id_res)
                        st.session_state.hubspot_token = token_input.strip()
                        st.rerun()
                    else:
                        st.sidebar.error(f"❌ {err_msg}")
        st.sidebar.caption("Not connected")

        # Optional OAuth flow toggle
        with st.sidebar.expander("⚡ 1-Click HubSpot OAuth (Marketplace Flow)", expanded=False):
            client_id = os.environ.get("HUBSPOT_CLIENT_ID", "").strip()
            client_secret = os.environ.get("HUBSPOT_CLIENT_SECRET", "").strip()
            redirect_uri = os.environ.get("HUBSPOT_REDIRECT_URI", "http://localhost:8501").strip()
            if client_id:
                try:
                    provider = HubSpotOAuthProvider(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)
                    st.link_button("🟠 Connect with HubSpot OAuth", provider.get_auth_url(redirect_uri=redirect_uri), type="primary", use_container_width=True)
                except Exception as e:
                    st.caption(f"OAuth config: {e}")
            else:
                st.caption("Configure HUBSPOT_CLIENT_ID in .env for marketplace 1-click install.")
    else:
        if st.sidebar.button("Disconnect", type="secondary", use_container_width=True, key="hs_disconnect_btn"):
            st.session_state.hubspot_connected = False
            st.session_state.hubspot_portal_id = None
            st.session_state.hubspot_token = ""
            st.session_state.hubspot_token_input_field = ""
            st.rerun()
        st.sidebar.markdown(f":green[Connected to portal {active_portal}]")

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
    st.sidebar.markdown("#### Freemium AI Enrichment Quota")
    quota = get_enrichment_quota(portal_id)
    used = quota["used"]
    limit = quota["limit"]
    remaining = quota["remaining"]
    is_exceeded = quota["is_exceeded"]

    st.sidebar.markdown(
        f"""
        <div class="linear-quota-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-weight:600; font-size:0.78rem; color:#FFFFFF;">Freemium Quota</span>
                <span style="background:rgba(94,106,210,0.15); color:#A5B4FC; font-size:0.72rem; font-weight:600; padding:2px 8px; border-radius:4px;">{used}/{limit} Used</span>
            </div>
            <div style="font-size:0.75rem; color:#94A3B8;">500 Free AI Enriched Leads</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    quota_pct = min(1.0, used / limit if limit > 0 else 1.0)
    st.sidebar.progress(quota_pct)
    st.sidebar.caption(f"✨ **{remaining}** free contacts remaining")

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
    st.sidebar.markdown("#### Resources & Diagnostics")
    if st.sidebar.button("Marketplace Guide & Sync Matrix"):
        st.session_state.show_marketplace_modal = True

    if st.sidebar.button("SQLite Execution History"):
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
    """Render sleek Linear-inspired top header with status chips."""
    portal_label = config.get("portal_id", "default_portal")
    is_dry_run = config.get("dry_run", True)
    is_connected = st.session_state.get("hubspot_connected", False)
    quota = get_enrichment_quota(portal_label)
    used = quota["used"]
    limit = quota["limit"]

    if is_connected:
        portal_badge = f'<span class="linear-chip linear-chip-green"><span class="linear-dot linear-dot-green"></span> Portal: <strong>{portal_label}</strong></span>'
    else:
        portal_badge = f'<span class="linear-chip"><span class="linear-dot linear-dot-gray"></span> Portal: {portal_label}</span>'

    if is_dry_run:
        dry_badge = '<span class="linear-chip linear-chip-amber"><span class="linear-dot linear-dot-amber"></span> Dry-Run Active</span>'
    else:
        dry_badge = '<span class="linear-chip" style="color:#EF4444; border-color:rgba(239,68,68,0.3); background:rgba(239,68,68,0.1);"><span class="linear-dot" style="background:#EF4444;"></span> Live Sync Active</span>'

    quota_badge = f'<span class="linear-chip linear-chip-indigo"><span class="linear-dot linear-dot-indigo"></span> Quota: <strong>{used}/{limit} Used</strong></span>'

    st.markdown(
        f"""
        <div class="linear-header-card">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px;">
                <div>
                    <div class="linear-badge">HubSpot App Marketplace</div>
                    <h1 class="linear-title">Lead Cleaner & RevOps Pipeline</h1>
                    <p class="linear-subtitle">
                        Indian mobile standardization (+91 E.164), PIN & GST cross-verification, and native duplicate consolidation for HubSpot CRM.
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


@st.dialog("🏢 HubSpot Integration & Sync Matrix Guide", width="large")
def show_marketplace_guide_dialog() -> None:
    """Render comprehensive marketplace setup guide, shared data matrix, and security specs."""
    st.markdown(
        """
        <div style="margin-bottom:14px; display:flex; gap:8px; flex-wrap:wrap;">
            <span class="linear-chip linear-chip-indigo">HubSpot Certified Standard</span>
            <span class="linear-chip linear-chip-green">Non-Destructive Sync</span>
            <span class="linear-chip">v2.4 Enterprise Edition</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Enterprise data governance, Indian SME mobile format standardization, and rapid time-to-value.")

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
        st.markdown("### Lead Ingestion Source")
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
            st.info("🔗 **Direct HubSpot CRM Mode:** Streams live contacts directly via API, applies +91 E.164 normalization, validates PIN codes and GSTIN checksums, and detects duplicate clusters.")

            col_h1, col_h2 = st.columns([3, 1])
            with col_h1:
                fetch_limit = st.slider("Maximum Contacts to Scan", min_value=50, max_value=500, value=250, step=50)

            is_connected = st.session_state.get("hubspot_connected", False)
            with col_h2:
                if not is_connected:
                    st.button("Fetch & Clean HubSpot Contacts", type="primary", disabled=True, use_container_width=True)
                    st.caption("⚠️ Connect to HubSpot first")
                else:
                    if st.button("Fetch & Clean HubSpot Contacts", type="primary", use_container_width=True):
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
    with st.expander("🔍 Contact Profile & Inspection Telemetry", expanded=False):
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
            score_color = "#10B981" if score >= 80 else ("#F59E0B" if score >= 70 else "#EF4444")
            st.markdown(f"**Hygiene Score:** <span style='color:{score_color}; font-weight:700; font-size:1.1rem;'>{score:.0f} / 100</span>", unsafe_allow_html=True)
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
        st.markdown("#### Duplicate Clusters & Native Consolidation")
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
        st.markdown("#### Flagged Records (Requires Review)")
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
        st.markdown("#### Hygiene KPIs & Executive Summary")
        
        tot = stats["total_rows"]
        pass_pct = stats.get("cleaned_pct", 0.0)
        review_pct = stats.get("review_pct", 0.0)
        avg_score = stats.get("avg_quality_score", 0.0)

        score_color = "#10B981" if avg_score >= 80 else ("#F59E0B" if avg_score >= 70 else "#EF4444")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"""
                <div class="linear-metric-card">
                    <div class="linear-metric-title">Total Processed</div>
                    <div class="linear-metric-val">{tot}</div>
                    <div class="linear-metric-desc">Ingested lead records</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div class="linear-metric-card">
                    <div class="linear-metric-title">Hygiene Pass Rate</div>
                    <div class="linear-metric-val" style="color:#10B981;">{pass_pct}%</div>
                    <div class="linear-metric-desc">{len(cleaned_df)} approved leads</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
                <div class="linear-metric-card">
                    <div class="linear-metric-title">Review Rate</div>
                    <div class="linear-metric-val" style="color:#F59E0B;">{review_pct}%</div>
                    <div class="linear-metric-desc">{len(review_df)} flagged leads</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f"""
                <div class="linear-metric-card">
                    <div class="linear-metric-title">Avg Quality Score</div>
                    <div class="linear-metric-val" style="color:{score_color};">{avg_score:.1f}</div>
                    <div class="linear-metric-desc">Out of 100 benchmark</div>
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

    # Handle incoming HubSpot OAuth redirect callback
    if "code" in st.query_params:
        auth_code = str(st.query_params.get("code") or "")
        return_url = st.query_params.get("returnUrl")
        if auth_code:
            with st.spinner("Authorizing and connecting with HubSpot..."):
                r_uri = os.environ.get("HUBSPOT_REDIRECT_URI") or "http://localhost:8501"
                ok, details, err = handle_oauth_callback(
                    code=auth_code,
                    redirect_uri=r_uri,
                )
                if ok and details:
                    st.session_state.hubspot_connected = True
                    st.session_state.hubspot_portal_id = str(details.get("portalId") or details.get("hubId"))
                    st.session_state.hubspot_token = details.get("access_token")
                    st.session_state.hubspot_domain = details.get("hubDomain")
                    st.session_state.hubspot_user = details.get("user")
                    if return_url:
                        st.session_state.hubspot_return_url = return_url
                    st.query_params.clear()
                    st.toast(f"✅ Connected to HubSpot Portal {st.session_state.hubspot_portal_id}!")
                    st.rerun()
                else:
                    st.error(f"HubSpot OAuth Authorization Failed: {err}")
                    st.query_params.clear()

    if "error" in st.query_params:
        err_msg = st.query_params.get("error_description") or st.query_params.get("error")
        st.error(f"HubSpot OAuth Error: {err_msg}")
        st.query_params.clear()

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
