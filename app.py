"""Streamlit Web Application for Lead Cleaner (RevOps India).

Features:
- Professional UI for Indian SMB lead hygiene
- File upload (.csv, .xlsx, .xls)
- Interactive configuration: fuzzy match threshold, quality score cutoff, dry-run safety
- In-memory processing (Loader -> Normalizer -> Validator -> Dedupe -> Reporter)
- KPI metrics & interactive tabbed results (Cleaned Leads, Review Queue, Merges, Report)
- HubSpot CRM integration with dry-run simulation and safe live push confirmation
- SQLite audit history inspector
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

# Page Configuration
st.set_page_config(
    page_title="Lead Cleaner | RevOps Hub",
    page_icon="🧹",
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


def render_sidebar() -> Dict[str, Any]:
    """Render sidebar configuration controls, HubSpot connection, and quota viewer."""
    st.sidebar.title("⚙️ Configuration")

    st.sidebar.markdown("### Matching & Quality Thresholds")
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
        help="Minimum quality score (0-100) required to route a lead to cleaned.csv.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### HubSpot CRM Settings")

    dry_run = st.sidebar.checkbox(
        "Enable Dry-Run Safety Mode",
        value=True,
        help="When checked, simulates HubSpot API calls without modifying real CRM data.",
    )

    if dry_run:
        st.sidebar.success("🟢 Dry-Run Mode Active (Safe)")
    else:
        st.sidebar.warning("⚠️ Live Mode Active (Mutations Enabled)")

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

    # Connect / Disconnect Action & Status Line
    col_conn_btn, col_conn_status = st.sidebar.columns([1, 1])
    if not is_connected:
        with col_conn_btn:
            if st.button("🔗 Connect", type="primary", use_container_width=True, key="hs_connect_btn"):
                if not token_input.strip():
                    st.sidebar.error("Please enter a token first.")
                else:
                    with st.sidebar.spinner("Validating with HubSpot API..."):
                        from hubspot.connection import validate_and_connect
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
        st.sidebar.markdown(f":green[**Connected to portal {active_portal}**]")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🏢 HubSpot Multi-Tenant Portal")
    if is_connected and active_portal:
        st.sidebar.info(f"Connected Portal: `{active_portal}`")
        portal_id = active_portal
    else:
        portal_id = st.sidebar.text_input(
            "Connected Portal ID",
            value="default_portal",
            help="HubSpot Account (Portal) ID. Governs OAuth credentials and tenant quota isolation.",
        )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚡ Tenant Quota Widget")

    # Fetch tenant quota status
    quota = get_enrichment_quota(portal_id)
    used = quota["used"]
    limit = quota["limit"]
    remaining = quota["remaining"]
    is_exceeded = quota["is_exceeded"]

    st.sidebar.markdown(
        f"""
        <div class="quota-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-weight:700; font-size:0.85rem; color:#0F172A;">Freemium Quota</span>
                <span class="badge-pill badge-coral">{used} / {limit} Used</span>
            </div>
            <div style="font-size:0.78rem; color:#64748B;">500 Free Leads Included</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    quota_pct = min(1.0, used / limit if limit > 0 else 1.0)
    st.sidebar.progress(quota_pct)
    st.sidebar.caption(f"✨ **{remaining}** free contacts remaining")

    if is_exceeded:
        st.sidebar.error("⚠️ Freemium quota reached (500/500 contacts). Upgrade plan to continue.")
        enrich_enabled = False
    else:
        has_gemini_key = bool(get_gemini_api_key())
        enrich_enabled = st.sidebar.checkbox(
            "Enable Cloud LLM Note Enrichment",
            value=False,
            help="Extracts structured budget, product intent, and city from raw notes using Google Gemini 1.5 Flash.",
        )
        if enrich_enabled:
            if has_gemini_key:
                st.sidebar.success("🟢 Google Gemini API Key Configured")
            else:
                st.sidebar.warning("⚠️ GEMINI_API_KEY not found in .env. Enrichment calls may fail.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🖥️ Dashboard Layout")
    ui_mode = st.sidebar.selectbox(
        "UI Mode",
        options=["classic", "mixed"],
        index=0,
        help="Switch between Classic Tabbed explorer and the new high-density Mixed layout.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📚 Marketplace Resources")
    if st.sidebar.button("📖 App Setup & Sync Guide"):
        st.session_state.show_marketplace_modal = True

    st.sidebar.markdown("### SQLite Audit Trail")
    if st.sidebar.button("Inspect Previous Runs"):
        st.session_state.show_db_modal = True

    return {
        "fuzzy_threshold": fuzzy_thresh,
        "quality_cutoff": quality_cutoff,
        "dry_run": dry_run,
        "token": token_input,
        "portal_id": portal_id,
        "enrich": enrich_enabled,
        "ui_mode": ui_mode,
    }


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
            <span class="badge-pill badge-coral">HubSpot Certified App Standard</span>
            <span class="badge-pill badge-teal">Non-Destructive RevOps Sync</span>
            <span class="badge-pill badge-slate">v2.4 Marketplace Edition</span>
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
               - Navigate to the sidebar under **HubSpot CRM Settings**.
               - Enter your **Private App Token** and click **Connect**.
               - The app securely calls `GET /crm/v3/objects/contacts?limit=1` and `GET /account-info/v3/details` to fetch and store your Portal ID.
            
            2. **Step 2: Choose Data Ingestion Source**  
               - **Option A (Staged Files):** Upload messy Excel/CSV exports from trade expos, WhatsApp, Meta Lead Ads, or website forms.
               - **Option B (Direct CRM Sync):** Pull live contacts, associated companies, and deals directly from your HubSpot database via API.
            
            3. **Step 3: Run Pre-Flight Diagnostics & Hygiene**  
               - Standardizes Indian mobile numbers into E.164 `+91XXXXXXXXXX`.
               - Validates 6-digit postal PIN codes and cross-matches GSTIN state codes.
               - Identifies fuzzy duplicates using RapidFuzz Token-Sort ratio with auto-merge backfills.
            
            4. **Step 4: Non-Destructive Push & Native Duplicate Merge**  
               - Test with **Dry-Run Mode Enabled** (zero real mutations) to inspect simulated payloads.
               - Once satisfied, push clean leads to HubSpot or merge duplicates via `POST /crm/v3/objects/contacts/merge`.
            """
        )

    with guide_tab2:
        st.markdown("#### 🔄 Shared Data & Property Mapping Matrix")
        st.caption("How Indian lead fields and AI intelligence map directly into HubSpot standard and custom properties:")
        
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
            To install this app or generate a Private App Token, grant the following standard scopes:
            
            | Scope | Permission Type | Rationale |
            | :--- | :---: | :--- |
            | `crm.objects.contacts.read` | Read | Fetch contacts to scan hygiene and deduplicate |
            | `crm.objects.contacts.write` | Write | Push standardized numbers, emails, and GSTINs |
            | `crm.objects.companies.read` | Read | Read associated company details for B2B accounts |
            | `crm.objects.companies.write` | Write | Link contacts to existing company records |
            | `crm.schemas.custom.read` | Read | Inspect custom fields like `gst_number` |
            
            > **Security Guarantee:** Tokens are kept strictly in memory for the active session. Tokens are never logged, persisted to disk, or exposed in URLs.
            """
        )

    with guide_tab4:
        st.markdown("#### 🛡️ Non-Destructive Safety & Overwrite Policy")
        st.markdown(
            """
            Unlike basic import tools that overwrite existing records, this integration uses **RevOps Non-Destructive Patch Architecture**:
            
            - **Never Overwrites Existing Valid Data:** If a contact already has a valid phone or email in HubSpot, our engine preserves it unless `overwrite=True` is explicitly instructed.
            - **Fills Property Gaps:** Blank fields (e.g., missing PIN code, unformatted city, missing GST number) are enriched and backfilled non-destructively.
            - **Safety-First Dry-Run Default:** All CRM sync operations simulate the exact API payloads in Dry-Run mode before live execution.
            - **Native CRM Merges:** Duplicate pairs use HubSpot's official merge endpoint (`/crm/v3/objects/contacts/merge`), preserving sales history, email engagements, and deal associations on the primary contact.
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


def inject_custom_css() -> None:
    """Inject clean, executive-tier SaaS CSS inspired by HubSpot design system."""
    st.html(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

        :root {
            --hs-coral: #FF5C35;
            --hs-coral-hover: #E54B24;
            --hs-coral-light: #FFF1EE;
            --hs-teal: #00A389;
            --hs-teal-light: #E6F7F5;
            --hs-dark: #0F172A;
            --hs-slate: #1E293B;
            --hs-muted: #64748B;
            --hs-border: #E2E8F0;
        }

        html, body, [class*="css"] {
            font-family: 'Plus Jakarta Sans', 'Inter', -apple-system, sans-serif !important;
            color: var(--hs-slate);
        }

        /* Hero Header Banner */
        .hs-hero-banner {
            background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
            border-radius: 16px;
            padding: 24px 28px;
            color: #FFFFFF;
            margin-bottom: 24px;
            box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .hs-hero-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 92, 53, 0.2);
            border: 1px solid rgba(255, 92, 53, 0.4);
            color: #FF8F70;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 12px;
        }
        .hs-hero-title {
            font-size: 1.85rem;
            font-weight: 800;
            color: #FFFFFF;
            margin: 0 0 8px 0;
            line-height: 1.2;
        }
        .hs-hero-subtitle {
            font-size: 0.95rem;
            color: #94A3B8;
            margin: 0;
            line-height: 1.5;
            max-width: 900px;
        }

        /* Metric Cards */
        .metric-card-container {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 14px;
            padding: 18px 20px;
            box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.05);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            height: 100%;
        }
        .metric-card-container:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px -4px rgba(15, 23, 42, 0.08);
            border-color: #CBD5E1;
        }
        .metric-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .metric-title {
            color: #64748B;
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .metric-number {
            font-size: 2rem;
            font-weight: 800;
            color: #0F172A;
            line-height: 1.1;
            margin-bottom: 6px;
        }
        .metric-sub {
            font-size: 0.8rem;
            color: #64748B;
        }

        /* Pill Badges */
        .badge-pill {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.76rem;
            font-weight: 700;
            line-height: 1.2;
        }
        .badge-teal { background: #E6F7F5; color: #00A389; }
        .badge-coral { background: #FFF1EE; color: #FF5C35; }
        .badge-amber { background: #FEF3C7; color: #B45309; }
        .badge-slate { background: #F1F5F9; color: #1E293B; }
        .badge-red { background: #FEE2E2; color: #DC2626; }

        /* Buttons */
        button[kind="primary"] {
            background: linear-gradient(135deg, #FF5C35 0%, #FF724E 100%) !important;
            border: none !important;
            color: #FFFFFF !important;
            font-weight: 600 !important;
            border-radius: 8px !important;
            padding: 10px 20px !important;
            box-shadow: 0 4px 14px rgba(255, 92, 53, 0.28) !important;
            transition: all 0.2s ease !important;
        }
        button[kind="primary"]:hover {
            background: linear-gradient(135deg, #E54B24 0%, #FF5C35 100%) !important;
            box-shadow: 0 6px 18px rgba(255, 92, 53, 0.4) !important;
            transform: translateY(-1px) !important;
        }
        button[kind="secondary"] {
            border: 1px solid #CBD5E1 !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
            color: #1E293B !important;
            transition: all 0.2s ease !important;
        }
        button[kind="secondary"]:hover {
            border-color: #FF5C35 !important;
            color: #FF5C35 !important;
        }

        /* Tabs */
        div[data-testid="stTabs"] button {
            font-weight: 600 !important;
            font-size: 0.95rem !important;
            padding: 12px 18px !important;
            color: #64748B !important;
            border-bottom: 2px solid transparent !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            color: #FF5C35 !important;
            border-bottom: 2px solid #FF5C35 !important;
        }

        /* Sidebar Progress Bar Gradient */
        div[data-testid="stSidebar"] div[data-testid="stProgress"] > div > div > div {
            background: linear-gradient(90deg, #FF5C35 0%, #FF8F70 100%) !important;
            border-radius: 9999px !important;
        }

        /* Sidebar Quota Widget Box */
        .quota-box {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 14px 16px;
            margin-top: 6px;
            margin-bottom: 12px;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
        }

        /* Dataframe styling */
        div[data-testid="stDataFrame"] {
            border-radius: 10px !important;
            border: 1px solid #E2E8F0 !important;
            overflow: hidden;
        }
        </style>
        """
    )


def render_preflight_diagnostics(is_dry_run: bool) -> None:
    """Render Step 2: Live Progress & Pre-flight Diagnostics."""
    st.markdown("### 2. Pre-flight Diagnostics & Engine Health")
    with st.container(border=True):
        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.markdown(
                """
                <div style="margin-bottom:8px;">
                    <span class="badge-pill badge-teal">● Active</span>
                    <strong style="margin-left:6px; color:#0F172A;">Mobile Normalizer</strong>
                </div>
                <div style="font-size:0.8rem; color:#64748B;">Standardizes Indian 10-digit numbers to E.164 (+91)</div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                """
                <div style="margin-top:12px; margin-bottom:8px;">
                    <span class="badge-pill badge-teal">● Active</span>
                    <strong style="margin-left:6px; color:#0F172A;">PIN Code Engine</strong>
                </div>
                <div style="font-size:0.8rem; color:#64748B;">Cross-checks 6-digit postal codes against state rules</div>
                """,
                unsafe_allow_html=True,
            )
        with col_d2:
            st.markdown(
                """
                <div style="margin-bottom:8px;">
                    <span class="badge-pill badge-teal">● Active</span>
                    <strong style="margin-left:6px; color:#0F172A;">GSTIN Validator</strong>
                </div>
                <div style="font-size:0.8rem; color:#64748B;">15-char checksum verification & state alignment check</div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                """
                <div style="margin-top:12px; margin-bottom:8px;">
                    <span class="badge-pill badge-teal">● Active</span>
                    <strong style="margin-left:6px; color:#0F172A;">Fuzzy Deduplication</strong>
                </div>
                <div style="font-size:0.8rem; color:#64748B;">Token-sort clustering with exact merge backfilling</div>
                """,
                unsafe_allow_html=True,
            )
        with col_d3:
            st.markdown(
                f"""
                <div style="margin-bottom:8px;">
                    <span class="badge-pill {'badge-teal' if is_dry_run else 'badge-amber'}">● {'Dry-Run Safe' if is_dry_run else 'Live Mutations'}</span>
                    <strong style="margin-left:6px; color:#0F172A;">HubSpot CRM Safety</strong>
                </div>
                <div style="font-size:0.8rem; color:#64748B;">{'Non-destructive simulated sync active' if is_dry_run else 'Live CRM mutations enabled'}</div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                """
                <div style="margin-top:12px; margin-bottom:8px;">
                    <span class="badge-pill badge-coral">● AI Ready</span>
                    <strong style="margin-left:6px; color:#0F172A;">Gemini 1.5 Flash</strong>
                </div>
                <div style="font-size:0.8rem; color:#64748B;">Freemium note enrichment with budget & intent extraction</div>
                """,
                unsafe_allow_html=True,
            )


def render_modern_kpi_cards(results: Dict[str, Any]) -> None:
    """Render modern rounded metric cards with drop shadows and pill badges."""
    stats = results["stats"]
    total_rows = stats["total_rows"]
    cleaned_count = len(results["cleaned_df"])
    cleaned_pct = stats.get("cleaned_pct", 0.0)
    review_count = len(results["review_df"])
    review_pct = stats.get("review_pct", 0.0)
    dedupe_count = len(results["proposals_df"])
    avg_score = stats.get("avg_quality_score", 0.0)

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.markdown(
            f"""
            <div class="metric-card-container">
                <div class="metric-top">
                    <span class="metric-title">Total Records</span>
                    <span class="badge-pill badge-slate">Batch Total</span>
                </div>
                <div class="metric-number">{total_rows}</div>
                <div class="metric-sub">Ingested into pipeline</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with kpi2:
        st.markdown(
            f"""
            <div class="metric-card-container">
                <div class="metric-top">
                    <span class="metric-title">Cleaned Leads</span>
                    <span class="badge-pill badge-teal">🟢 Cleaned {cleaned_pct}%</span>
                </div>
                <div class="metric-number">{cleaned_count}</div>
                <div class="metric-sub">Approved for CRM sync</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with kpi3:
        st.markdown(
            f"""
            <div class="metric-card-container">
                <div class="metric-top">
                    <span class="metric-title">Review Needed</span>
                    <span class="badge-pill badge-amber">🟡 Flagged {review_pct}%</span>
                </div>
                <div class="metric-number">{review_count}</div>
                <div class="metric-sub">Requires human inspection</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with kpi4:
        st.markdown(
            f"""
            <div class="metric-card-container">
                <div class="metric-top">
                    <span class="metric-title">Quality Score</span>
                    <span class="badge-pill badge-coral">✨ {avg_score:.1f} / 100</span>
                </div>
                <div class="metric-number">{avg_score:.1f}<span style="font-size:1rem; color:#64748B;">/100</span></div>
                <div class="metric-sub">Duplicate Clusters: <strong>{dedupe_count}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_crm_push_controls(results: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Render HubSpot CRM Push section with dry-run simulation or live confirmation."""
    st.markdown("### HubSpot CRM Push")

    cleaned_count = len(results["cleaned_df"])
    if cleaned_count == 0:
        st.info("No cleaned leads available to push.")
        return

    is_dry_run = config["dry_run"]

    if is_dry_run:
        st.info("ℹ️ **Dry-Run Mode Enabled:** Pushing will simulate search, contact creation, and non-destructive updates without making live changes in HubSpot.")
        if st.button(f"🧪 Test Push ({cleaned_count} Leads - Dry-Run Simulation)", type="primary", key="push_dry_run_btn"):
            _execute_hubspot_sync(results["cleaned_df"], config, is_dry_run=True)
    else:
        st.error("🚨 **Live Mode Active:** Proceeding will create or patch actual contact records in your HubSpot CRM account.")
        confirm_live = st.checkbox("I understand and confirm that I want to execute real mutations in HubSpot CRM.", key="confirm_live_push")
        if confirm_live:
            if st.button(f"🚀 Push {cleaned_count} Leads to HubSpot (Live)", type="primary", key="push_live_btn"):
                _execute_hubspot_sync(results["cleaned_df"], config, is_dry_run=False)


def _render_ingestion_controls(config: Dict[str, Any]) -> None:
    """Render data ingestion controls (file upload or live HubSpot fetch)."""
    st.markdown("### 1. Ingest Leads")
    intake_mode = st.segmented_control(
        "Select Data Ingestion Source:",
        options=["📂 Upload File (CSV / Excel)", "🔄 Direct HubSpot CRM Sync"],
        default="📂 Upload File (CSV / Excel)",
        help="Choose between staging raw files or scanning your live HubSpot CRM contact database.",
    )
    if not intake_mode:
        intake_mode = "📂 Upload File (CSV / Excel)"

    if intake_mode == "📂 Upload File (CSV / Excel)":
        uploaded_file = st.file_uploader(
            "Upload raw leads file (.csv, .xlsx, .xls)",
            type=["csv", "xlsx", "xls"],
            help="Upload messy Excel or CSV exports from trade expos, WhatsApp, Meta Lead Ads, or website forms.",
        )

        if uploaded_file is not None:
            file_bytes = uploaded_file.getvalue()
            file_size_kb = round(len(file_bytes) / 1024, 1)

            # Show raw preview if new file
            if st.session_state.active_file_name != uploaded_file.name:
                st.session_state.pipeline_results = None
                st.session_state.sync_results = None
                st.session_state.active_file_name = uploaded_file.name

            col_meta1, col_meta2 = st.columns(2)
            with col_meta1:
                st.write(f"📄 **File:** `{uploaded_file.name}` ({file_size_kb} KB)")
            with col_meta2:
                st.write("🛡️ **Safety Mode:** " + ("`Dry-Run (Simulated)`" if config["dry_run"] else "`Live Mode`"))

            if st.session_state.pipeline_results is None:
                if st.button("🚀 Run Cleaning Pipeline", type="primary"):
                    with st.spinner("Processing leads through normalization, validation, and deduplication..."):
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
                            st.success("✅ Pipeline executed successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Pipeline failed: {e}")
                            st.info("Tip: Check if the file has headers or valid UTF-8/Windows-1252 text encoding.")

    else:
        # Direct HubSpot CRM Sync Mode
        st.info("🔗 **Direct HubSpot CRM Sync Mode:** Pulls live contacts, associated companies, and deals directly from your HubSpot account via API, runs deduplication and hygiene validation, and identifies duplicate clusters.")

        col_h1, col_h2 = st.columns([2, 1])
        with col_h1:
            fetch_limit = st.slider("Maximum Contacts to Scan", min_value=50, max_value=1000, value=250, step=50)
        with col_h2:
            st.write(f"🏢 **Portal ID:** `{config.get('portal_id', 'default_portal')}`")

        is_connected = st.session_state.get("hubspot_connected", False)
        if not is_connected:
            st.warning("⚠️ **HubSpot Not Connected:** Please enter your Private App Token and click **Connect** in the sidebar to scan live CRM records.")
            st.button("🔄 Fetch & Clean HubSpot Contacts", type="primary", disabled=True, help="Connect to HubSpot in the sidebar first.")
        else:
            if st.button("🔄 Fetch & Clean HubSpot Contacts", type="primary"):
                with st.spinner("Streaming contacts from HubSpot CRM via API and running hygiene pipeline..."):
                    try:
                        client = HubSpotClient(
                            token=config.get("token"),
                            portal_id=config.get("portal_id"),
                            dry_run=config["dry_run"],
                        )
                        raw_contacts = client.fetch_contacts(max_records=fetch_limit)
                        if not raw_contacts:
                            st.warning("No contacts found in HubSpot or client in dry-run mock mode without live token. Connect your HubSpot App or add a Private App Token to fetch live data.")
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
                            st.success(f"✅ Successfully fetched {len(raw_contacts)} contacts and executed cleaning pipeline!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Failed to fetch from HubSpot CRM: {e}")


def main() -> None:
    init_session_state()
    inject_custom_css()

    config = render_sidebar()
    render_audit_modal()
    if st.session_state.get("show_marketplace_modal"):
        show_marketplace_guide_dialog()

    ui_mode = config.get("ui_mode", "classic")

    if ui_mode == "mixed":
        render_mixed_dashboard(
            results=st.session_state.pipeline_results,
            config=config,
            run_pipeline_fn=run_in_memory_pipeline,
        )

        st.markdown("---")
        with st.expander("📥 Ingest Leads & CRM Sync Options", expanded=(st.session_state.pipeline_results is None)):
            _render_ingestion_controls(config)
            if st.session_state.pipeline_results is not None:
                st.markdown("---")
                _render_crm_push_controls(st.session_state.pipeline_results, config)
        return

    # Classic Layout - SaaS Executive Tier Banner
    st.markdown(
        f"""
        <div class="hs-hero-banner">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
                <div>
                    <div class="hs-hero-badge">🏢 HubSpot Marketplace Ready</div>
                    <div class="hs-hero-title">🧹 Lead Cleaner for Small Businesses (India)</div>
                    <p class="hs-hero-subtitle">
                        Enterprise RevOps lead hygiene and HubSpot ingestion pipeline. Standardizes <strong>Indian mobile formats (+91)</strong>, 
                        verifies <strong>PIN code prefixes</strong>, checks <strong>GSTIN state alignment</strong>, and consolidates duplicate records non-destructively.
                    </p>
                </div>
                <div style="text-align:right;">
                    <span class="badge-pill {'badge-teal' if config.get('dry_run', True) else 'badge-amber'}">
                        {'🟢 Dry-Run Mode Active' if config.get('dry_run', True) else '⚠️ Live Mode Active'}
                    </span>
                    <div style="font-size:0.75rem; color:#94A3B8; margin-top:6px;">
                        Portal: <strong>{config.get('portal_id', 'default_portal')}</strong>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_guide_btn, _ = st.columns([1, 3])
    with col_guide_btn:
        if st.button("📖 View Setup Guide", key="banner_guide_trigger_btn", use_container_width=True):
            st.session_state.show_marketplace_modal = True
            st.rerun()

    _render_ingestion_controls(config)

    # Step 2: Processing & Metrics Display
    results = st.session_state.pipeline_results
    if results is not None:
        stats = results["stats"]

        render_preflight_diagnostics(is_dry_run=config.get("dry_run", True))

        st.markdown("---")
        st.markdown("### 3. Hygiene & Quality KPIs")
        render_modern_kpi_cards(results)

        # Step 4: Tabbed Results Explorer
        st.markdown("---")
        st.markdown("### 4. Pipeline Results Explorer")

        tab_cleaned, tab_review, tab_merges, tab_report = st.tabs(
            [
                f"🟢 Ready for CRM Sync ({len(results['cleaned_df'])})",
                f"🟡 Review Needed ({len(results['review_df'])})",
                f"🔴 Duplicate Clusters ({len(results['proposals_df'])})",
                "📊 Executive Audit Report",
            ]
        )

        with tab_cleaned:
            st.markdown("#### Cleaned Leads (Approved for CRM Sync)")
            cleaned_df = results["cleaned_df"]
            if not cleaned_df.empty:
                search_query = st.text_input("Search Cleaned Leads", placeholder="Filter by name, phone, email, city...")
                display_df = cleaned_df
                if search_query:
                    mask = display_df.astype(str).apply(lambda row: row.str.contains(search_query, case=False).any(), axis=1)
                    display_df = display_df[mask]

                # Show display columns
                preview_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "pin_code", "gst_number", "notes_structured", "quality_score"] if c in display_df.columns]
                st.dataframe(display_df[preview_cols], use_container_width=True)

                st.download_button(
                    "📥 Download Cleaned Leads (.csv)",
                    data=to_csv_bytes(cleaned_df),
                    file_name="cleaned_leads.csv",
                    mime="text/csv",
                )
            else:
                st.info("No leads met the cleaning threshold criteria.")

        with tab_review:
            st.markdown("#### Review Queue (Requires Human Inspection)")
            st.caption("Leads flagged due to invalid phones, invalid emails, unmapped cities, GST state mismatches, or fuzzy duplicate matches.")
            review_df = results["review_df"]
            if not review_df.empty:
                review_preview_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "issues_str", "notes_structured", "quality_score"] if c in review_df.columns]
                st.dataframe(review_df[review_preview_cols], use_container_width=True)

                st.download_button(
                    "📥 Download Review Queue (.csv)",
                    data=to_csv_bytes(review_df),
                    file_name="review_queue.csv",
                    mime="text/csv",
                )
            else:
                st.success("Zero leads flagged for review!")

        with tab_merges:
            st.markdown("#### Duplicate Clusters & Merge Proposals")
            proposals_df = results["proposals_df"]
            if not proposals_df.empty:
                st.dataframe(proposals_df, use_container_width=True)
                st.caption("Exact phone/email duplicates are consolidated automatically into the primary record with backfilled properties. Fuzzy matches are flagged for human sign-off.")

                # Check if duplicate clusters contain HubSpot Contact IDs (Mode 2 Direct CRM sync)
                has_hs_ids = (
                    "primary_contact_id" in proposals_df.columns
                    and (proposals_df["primary_contact_id"].astype(str) != "").any()
                )

                if has_hs_ids:
                    st.markdown("---")
                    st.markdown("##### ⚡ Native HubSpot Contact Merging")
                    if config["dry_run"]:
                        st.info("ℹ️ **Dry-Run Mode Active:** Contact merges will be simulated and logged without modifying real CRM records.")
                    else:
                        st.warning("⚠️ **Live Mode Active:** Merging will permanently combine secondary contacts into the primary contact in HubSpot CRM.")

                    merge_pairs_count = sum(
                        len(sec) if isinstance(sec, (list, tuple)) else (1 if sec else 0)
                        for sec in proposals_df.get("secondary_contact_ids", [])
                    )

                    if st.button(f"⚡ Merge Detected Duplicates in HubSpot ({merge_pairs_count} pairs)", type="secondary"):
                        with st.spinner("Executing HubSpot native contact merges..."):
                            try:
                                client = HubSpotClient(
                                    token=config.get("token"),
                                    portal_id=config.get("portal_id"),
                                    dry_run=config["dry_run"],
                                )

                                progress_merge = st.progress(0)
                                status_merge = st.empty()

                                merge_records = proposals_df.to_dict(orient="records")
                                merge_results = []
                                total_clusters = len(merge_records)

                                for idx, cluster in enumerate(merge_records):
                                    status_merge.text(f"Processing cluster {idx + 1} of {total_clusters}: {cluster.get('primary_name')}...")
                                    res_list = client.merge_duplicate_clusters([cluster], portal_id=config.get("portal_id"))
                                    merge_results.extend(res_list)
                                    progress_merge.progress((idx + 1) / total_clusters)

                                status_merge.empty()
                                progress_merge.empty()

                                successful = sum(1 for r in merge_results if r.get("status") in {"success", "dry_run"})
                                failed = sum(1 for r in merge_results if r.get("status") == "failed")

                                st.success(f"🎉 Merge batch complete! {successful} pairs processed ({'Simulated' if config['dry_run'] else 'Executed'}), {failed} failed.")

                                if merge_results:
                                    with st.expander("🔍 View Merge Operations Summary", expanded=True):
                                        st.dataframe(pd.DataFrame(merge_results), use_container_width=True)

                            except Exception as e:
                                st.error(f"❌ Merge operation failed: {e}")
            else:
                st.write("No duplicate clusters detected.")

        with tab_report:
            st.markdown("#### Analytical Markdown Summary")
            st.markdown(results["report_md"])

        # Step 4: CRM Push Action (HubSpot)
        st.markdown("---")
        st.markdown("### 4. HubSpot CRM Push")

        cleaned_count = len(results["cleaned_df"])
        if cleaned_count == 0:
            st.info("No cleaned leads available to push.")
            return

        is_dry_run = config["dry_run"]

        if is_dry_run:
            st.info("ℹ️ **Dry-Run Mode Enabled:** Pushing will simulate search, contact creation, and non-destructive updates without making live changes in HubSpot.")
            if st.button(f"🧪 Test Push ({cleaned_count} Leads - Dry-Run Simulation)", type="primary"):
                _execute_hubspot_sync(results["cleaned_df"], config, is_dry_run=True)
        else:
            st.error("🚨 **Live Mode Active:** Proceeding will create or patch actual contact records in your HubSpot CRM account.")
            confirm_live = st.checkbox("I understand and confirm that I want to execute real mutations in HubSpot CRM.")
            if confirm_live:
                if st.button(f"🚀 Push {cleaned_count} Leads to HubSpot (Live)", type="primary"):
                    _execute_hubspot_sync(results["cleaned_df"], config, is_dry_run=False)


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

        # Show audit log sample
        if client.audit_log:
            with st.expander("🔍 View CRM Sync Audit Log", expanded=False):
                st.dataframe(pd.DataFrame(client.audit_log), use_container_width=True)

    except ConfigurationError as ce:
        st.error(f"Configuration error: {ce}")
    except Exception as e:
        st.error(f"HubSpot sync failed: {e}")


if __name__ == "__main__":
    main()
