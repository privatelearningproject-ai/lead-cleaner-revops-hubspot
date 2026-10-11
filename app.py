"""Streamlit Web Application for Lead Cleaner (HubSpot Canvas & Leadfeeder Marketplace Aesthetic).

Features:
- Native HubSpot Canvas Design Tokens (#F5F8FA canvas, #FF5C35 coral, #00A389 sprocket green)
- Embedded HubSpot App Header with Connected Tenant Chip & Quota Pill
- Dual-Mode Ingestion: Vendor Spreadsheets (CSV/Excel) vs Direct HubSpot CRM API Sync
- Primary Leadfeeder Data Views:
    1. Contacts & Leads (with Quality Score badges & non-destructive patch sync)
    2. Duplicate Clusters & Merges (Side-by-side comparison & native CRM merge API)
    3. Review Queue (Clean issue pills for human inspection)
    4. Audit & Executive Summary (High-density KPI tiles & executive report)
- Contact Inspection Flyout (HubSpot contact profile view with raw vs canonical comparison)
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
from hubspot.connection import validate_and_connect

# Page Configuration
st.set_page_config(
    page_title="Lead Cleaner & RevOps Hygiene | HubSpot App",
    page_icon="🟠",
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
    if "selected_contact_id" not in st.session_state:
        st.session_state.selected_contact_id = 0


def inject_custom_css() -> None:
    """Inject HubSpot Canvas Design Tokens and Leadfeeder-inspired styling."""
    st.html(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

        /* Hide standard Streamlit header and footer chrome for native embedded app look */
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
            --hs-coral: #FF5C35;
            --hs-coral-hover: #E04B28;
            --hs-sprocket-green: #00A389;
            --hs-green-tint: #EAF7F4;
            --hs-canvas-bg: #F5F8FA;
            --hs-white: #FFFFFF;
            --hs-border-subtle: #CBD6E2;
            --hs-border-light: #EAF0F6;
            --hs-header-dark: #2D3E50;
            --hs-slate: #33475B;
            --hs-muted: #516F90;
            --hs-amber: #D97706;
            --hs-amber-tint: #FEF3C7;
            --hs-red: #DC2626;
            --hs-red-tint: #FEE2E2;
        }

        /* Canvas Background */
        .stApp {
            background-color: var(--hs-canvas-bg) !important;
            font-family: 'Plus Jakarta Sans', 'Inter', -apple-system, sans-serif !important;
            color: var(--hs-slate) !important;
        }

        /* Top Header Utility Bar */
        .hs-canvas-header {
            background: var(--hs-white);
            border: 1px solid var(--hs-border-subtle);
            border-radius: 8px;
            padding: 18px 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 4px rgba(45, 62, 80, 0.06);
        }
        .hs-sprocket-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #FFF1EE;
            border: 1px solid #FFD3C7;
            color: var(--hs-coral);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 8px;
        }
        .hs-canvas-title {
            color: var(--hs-header-dark);
            font-size: 1.65rem;
            font-weight: 800;
            margin: 0 0 4px 0;
            line-height: 1.2;
        }
        .hs-canvas-subtitle {
            color: var(--hs-muted);
            font-size: 0.88rem;
            margin: 0;
            line-height: 1.4;
        }

        /* Utility Chips & Pills */
        .hs-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #EDF2F7;
            border: 1px solid var(--hs-border-subtle);
            color: var(--hs-header-dark);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .hs-chip-green {
            background: var(--hs-green-tint);
            border-color: #BBE7DF;
            color: var(--hs-sprocket-green);
        }
        .hs-chip-amber {
            background: var(--hs-amber-tint);
            border-color: #FDE68A;
            color: var(--hs-amber);
        }

        /* Quality Score Badges */
        .qs-badge-green {
            background: #EAF7F4;
            color: #00A389;
            border: 1px solid #BBE7DF;
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.76rem;
            display: inline-block;
        }
        .qs-badge-amber {
            background: #FEF3C7;
            color: #B45309;
            border: 1px solid #FDE68A;
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.76rem;
            display: inline-block;
        }
        .qs-badge-red {
            background: #FEE2E2;
            color: #DC2626;
            border: 1px solid #FECACA;
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 0.76rem;
            display: inline-block;
        }

        /* Leadfeeder Metric Tiles */
        .lf-metric-card {
            background: var(--hs-white);
            border: 1px solid var(--hs-border-subtle);
            border-radius: 8px;
            padding: 16px 20px;
            box-shadow: 0 1px 3px rgba(45, 62, 80, 0.05);
            transition: all 0.2s ease;
        }
        .lf-metric-card:hover {
            box-shadow: 0 4px 12px rgba(45, 62, 80, 0.08);
            border-color: #99ACC2;
        }
        .lf-metric-title {
            color: var(--hs-muted);
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 6px;
        }
        .lf-metric-val {
            color: var(--hs-header-dark);
            font-size: 1.9rem;
            font-weight: 800;
            line-height: 1.1;
        }
        .lf-metric-desc {
            color: var(--hs-muted);
            font-size: 0.76rem;
            margin-top: 4px;
        }

        /* HubSpot Buttons */
        button[kind="primary"] {
            background: var(--hs-coral) !important;
            border: none !important;
            color: #FFFFFF !important;
            font-weight: 600 !important;
            border-radius: 4px !important;
            padding: 8px 18px !important;
            box-shadow: 0 2px 4px rgba(255, 92, 53, 0.2) !important;
            transition: all 0.15s ease !important;
        }
        button[kind="primary"]:hover {
            background: var(--hs-coral-hover) !important;
            box-shadow: 0 4px 8px rgba(255, 92, 53, 0.3) !important;
        }
        button[kind="secondary"] {
            background: var(--hs-white) !important;
            border: 1px solid var(--hs-border-subtle) !important;
            color: var(--hs-header-dark) !important;
            font-weight: 600 !important;
            border-radius: 4px !important;
            transition: all 0.15s ease !important;
        }
        button[kind="secondary"]:hover {
            border-color: var(--hs-coral) !important;
            color: var(--hs-coral) !important;
        }

        /* Leadfeeder Tabs */
        div[data-testid="stTabs"] button {
            color: var(--hs-muted) !important;
            font-size: 0.92rem !important;
            font-weight: 600 !important;
            padding: 12px 18px !important;
            border-bottom: 3px solid transparent !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--hs-header-dark) !important;
            border-bottom: 3px solid var(--hs-coral) !important;
        }

        /* Contact Inspection Flyout Card */
        .hs-flyout-card {
            background: var(--hs-white);
            border: 1px solid var(--hs-border-subtle);
            border-radius: 8px;
            padding: 20px;
            margin-top: 14px;
            box-shadow: 0 2px 8px rgba(45, 62, 80, 0.06);
        }

        /* Quota Box */
        .hs-quota-box {
            background: #FFFFFF;
            border: 1px solid var(--hs-border-subtle);
            border-radius: 8px;
            padding: 14px;
            margin-top: 8px;
            margin-bottom: 12px;
        }
        </style>
        """
    )


def render_sidebar() -> Dict[str, Any]:
    """Render sidebar configuration controls, HubSpot connection, and quota viewer."""
    st.sidebar.markdown("### ⚙️ HubSpot App Settings")

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
    st.sidebar.markdown("#### 🛡️ CRM Safety Mode")
    dry_run = st.sidebar.checkbox(
        "Enable Dry-Run Safety Mode",
        value=True,
        help="When checked, simulates HubSpot API calls without modifying real CRM data.",
    )

    if dry_run:
        st.sidebar.caption("🟢 **Dry-Run Mode Active (Safe Non-Destructive Simulation)**")
    else:
        st.sidebar.warning("⚠️ **Live Mode Active (Mutations Enabled)**")

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🔑 HubSpot Authentication")
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
    st.sidebar.markdown("#### ⚡ Freemium AI Enrichment Quota")
    quota = get_enrichment_quota(portal_id)
    used = quota["used"]
    limit = quota["limit"]
    remaining = quota["remaining"]
    is_exceeded = quota["is_exceeded"]

    st.sidebar.markdown(
        f"""
        <div class="hs-quota-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-weight:700; font-size:0.82rem; color:#2D3E50;">Freemium Quota</span>
                <span style="background:#FFF1EE; color:#FF5C35; font-size:0.75rem; font-weight:700; padding:2px 8px; border-radius:4px;">{used}/{limit} Used</span>
            </div>
            <div style="font-size:0.75rem; color:#516F90;">500 Free AI Enriched Leads</div>
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
    st.sidebar.markdown("#### 📚 App Resources")
    if st.sidebar.button("📖 Marketplace Setup & Sync Guide"):
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
    """Render top HubSpot Canvas banner with tenant utility bar and quota pill."""
    portal_label = config.get("portal_id", "default_portal")
    is_dry_run = config.get("dry_run", True)
    quota = get_enrichment_quota(portal_label)
    used = quota["used"]
    limit = quota["limit"]

    st.markdown(
        f"""
        <div class="hs-canvas-header">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:16px;">
                <div>
                    <div class="hs-sprocket-badge">🟠 BUILT FOR HUBSPOT</div>
                    <h1 class="hs-canvas-title">Lead Cleaner & RevOps Hygiene (Indian SMEs)</h1>
                    <p class="hs-canvas-subtitle">
                        Enterprise lead cleansing, Indian mobile (+91 E.164) normalization, PIN code verification, and native duplicate consolidation for HubSpot CRM.
                    </p>
                </div>
                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:8px;">
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        <span class="hs-chip">🏢 Portal: <strong>{portal_label}</strong></span>
                        <span class="hs-chip hs-chip-{'green' if is_dry_run else 'amber'}">
                            {'🟢 Dry-Run Mode Active' if is_dry_run else '⚠️ Live Sync Mode'}
                        </span>
                        <span class="hs-chip" style="background:#FFF1EE; color:#FF5C35; border-color:#FFD3C7;">
                            ⚡ Quota: <strong>{used}/{limit} Used</strong>
                        </span>
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


@st.dialog("🏢 HubSpot App Marketplace Integration Guide", width="large")
def show_marketplace_guide_dialog() -> None:
    """Render comprehensive marketplace setup guide, shared data matrix, and security specs."""
    st.markdown(
        """
        <div style="margin-bottom:14px;">
            <span class="badge-pill" style="background:#FFF1EE; color:#FF5C35; padding:4px 10px; border-radius:12px; font-weight:700;">HubSpot Certified App Standard</span>
            <span class="badge-pill" style="background:#EAF7F4; color:#00A389; padding:4px 10px; border-radius:12px; font-weight:700;">Non-Destructive RevOps Sync</span>
            <span class="badge-pill" style="background:#EDF2F7; color:#2D3E50; padding:4px 10px; border-radius:12px; font-weight:700;">v2.4 Marketplace Edition</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Modeled after certified integrations like Leadfeeder to provide enterprise data governance, clear sync direction, and an under-10-minute setup experience.")

    guide_tab1, guide_tab2, guide_tab3, guide_tab4 = st.tabs(
        [
            "⚡ 10-Min Quickstart",
            "🔄 Shared Data & Sync Matrix",
            "🔑 Required Permissions",
            "🛡️ Safety & Overwrite Policy",
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
        st.markdown("### 📥 Lead Ingestion Source")
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
            st.info("🔗 **Direct HubSpot CRM Mode:** Streams live contacts directly via API, runs +91 phone formatting, PIN validation, GST cross-checks, and identifies duplicate clusters.")

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
    with st.expander("🔍 Contact Inspection Card (HubSpot Flyout View)", expanded=False):
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
            st.markdown(f"**Hygiene Score:** `{score} / 100`")
            issues = rec.get("issues", [])
            if issues:
                st.caption(f"Issues: `{', '.join(issues) if isinstance(issues, list) else issues}`")


def render_leadfeeder_tabs(results: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Render the primary 4-tab Leadfeeder layout."""
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
        st.markdown("#### 👥 Duplicate Clusters & Native Consolidation")
        st.caption("Exact phone/email duplicates are consolidated automatically into the primary record with backfilled properties. Fuzzy name matches require confirmation.")

        if not proposals_df.empty:
            # Check for HubSpot native merge compatibility
            has_hs_ids = (
                "primary_contact_id" in proposals_df.columns
                and (proposals_df["primary_contact_id"].astype(str) != "").any()
            )

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
        st.markdown("#### ⚠️ Flagged Records (Requires Review)")
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
        st.markdown("#### 📊 Hygiene KPIs & Executive Summary")
        
        # 4 Clean Metric Cards
        tot = stats["total_rows"]
        pass_pct = stats.get("cleaned_pct", 0.0)
        review_pct = stats.get("review_pct", 0.0)
        avg_score = stats.get("avg_quality_score", 0.0)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f"""
                <div class="lf-metric-card">
                    <div class="lf-metric-title">Total Processed</div>
                    <div class="lf-metric-val">{tot}</div>
                    <div class="lf-metric-desc">Ingested lead records</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div class="lf-metric-card">
                    <div class="lf-metric-title">Hygiene Pass Rate</div>
                    <div class="lf-metric-val" style="color:#00A389;">{pass_pct}%</div>
                    <div class="lf-metric-desc">{len(cleaned_df)} approved leads</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f"""
                <div class="lf-metric-card">
                    <div class="lf-metric-title">Review Rate</div>
                    <div class="lf-metric-val" style="color:#D97706;">{review_pct}%</div>
                    <div class="lf-metric-desc">{len(review_df)} flagged leads</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f"""
                <div class="lf-metric-card">
                    <div class="lf-metric-title">Avg Quality Score</div>
                    <div class="lf-metric-val" style="color:#FF5C35;">{avg_score:.1f}</div>
                    <div class="lf-metric-desc">Out of 100 benchmark</div>
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

    # Leadfeeder Primary Views
    _render_ingestion_controls(config)

    results = st.session_state.pipeline_results
    if results is not None:
        st.markdown("---")
        render_leadfeeder_tabs(results, config)


if __name__ == "__main__":
    main()
