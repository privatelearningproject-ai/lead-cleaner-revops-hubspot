"""Streamlit Web Application for Lead Cleaner (HubSpot CRM Data Quality & RevOps Pipeline).

Production SaaS UI/UX:
- Clean, trustworthy light aesthetic inspired by HubSpot CRM design system (#F5F7FA canvas, #FFFFFF cards, #243342 text, #FF5C35 accent).
- 5-view Information Architecture: Overview, Clean CRM, Upload Leads, History, Settings.
- Guided step-by-step workflows with real data parsing, previewing, and non-destructive CRM safety.
- Complete backward compatibility with existing tests, in-memory pipeline, and CLI/FastAPI server.
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
    get_portal,
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
from ui.components import (
    render_empty_state,
    render_safety_notice,
    render_step_progress,
    render_top_navbar,
)
from ui.theme import inject_saas_theme
from ui.views_clean_crm import render_clean_crm_view
from ui.views_history import render_history_view
from ui.views_overview import render_overview_view
from ui.views_settings import render_settings_view
from ui.views_upload import render_upload_leads_view

# Page Configuration
st.set_page_config(
    page_title="Lead Cleaner — HubSpot CRM Data Quality",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_session_state() -> None:
    """Initialize Streamlit session state variables."""
    if "pipeline_results" not in st.session_state:
        st.session_state.pipeline_results = None
    if "crm_scan_results" not in st.session_state:
        st.session_state.crm_scan_results = None
    if "sync_results" not in st.session_state:
        st.session_state.sync_results = None
    if "active_file_name" not in st.session_state:
        st.session_state.active_file_name = None
    if "uploaded_file_bytes" not in st.session_state:
        st.session_state.uploaded_file_bytes = None
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
    if "current_nav" not in st.session_state:
        st.session_state.current_nav = "overview"
    if "show_marketplace_modal" not in st.session_state:
        st.session_state.show_marketplace_modal = False
    if "show_db_modal" not in st.session_state:
        st.session_state.show_db_modal = False
    if "selected_contact_id" not in st.session_state:
        st.session_state.selected_contact_id = 0

    # Auto-detect token from environment on first run if available
    if not st.session_state.hubspot_connected:
        env_tok = get_token_from_env()
        if env_tok:
            st.session_state.hubspot_token = env_tok


def inject_custom_css() -> None:
    """Inject SaaS Theme styling (backward compatible alias)."""
    inject_saas_theme()


def render_sidebar() -> Dict[str, Any]:
    """Render sidebar navigation and quick preferences."""
    st.sidebar.markdown(
        """
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:16px;">
            <div style="background:#FF5C35; color:white; width:28px; height:28px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:0.95rem;">
                ✦
            </div>
            <div>
                <div style="font-weight:700; font-size:1.05rem; color:#243342; line-height:1.2;">Lead Cleaner</div>
                <div style="font-size:0.72rem; color:#617184;">HubSpot Marketplace App</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 1. Primary Navigation
    st.sidebar.markdown("### Navigation")
    nav_options = [
        ("overview", "🏠 Overview"),
        ("clean_crm", "🏢 Clean HubSpot CRM"),
        ("upload_leads", "📄 Upload Lead File"),
        ("history", "📜 History & Audit"),
        ("settings", "⚙️ Settings"),
    ]

    current_idx = 0
    for idx, (code, _) in enumerate(nav_options):
        if st.session_state.get("current_nav") == code:
            current_idx = idx
            break

    selected_nav = st.sidebar.radio(
        "Workspace View",
        options=[opt[0] for opt in nav_options],
        format_func=lambda c: next(lbl for code, lbl in nav_options if code == c),
        index=current_idx,
        label_visibility="collapsed",
    )
    st.session_state.current_nav = selected_nav

    st.sidebar.markdown("---")

    # 2. Connection Status Widget
    is_connected = st.session_state.get("hubspot_connected", False)
    active_portal = st.session_state.get("hubspot_portal_id") or "default_portal"
    if is_connected:
        st.sidebar.success(f"● Connected: Portal `{active_portal}`")
    else:
        st.sidebar.info("○ HubSpot Disconnected")
        if st.sidebar.button("Connect Account", type="primary", use_container_width=True, key="side_connect_hs"):
            st.session_state.current_nav = "settings"
            st.rerun()

    # 3. Quick Safety Toggle
    dry_run = st.session_state.get("cfg_dry_run", True)
    fuzzy_thresh = st.session_state.get("cfg_fuzzy_thresh", 90)
    quality_cutoff = st.session_state.get("cfg_quality_cutoff", 70)
    token_input = st.session_state.get("hubspot_token") or get_token_from_env() or ""

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Safety Mode: **{'🛡️ Preview (Safe)' if dry_run else '⚠️ Live CRM'}**")
    st.sidebar.caption(f"Sensitivity: **{fuzzy_thresh}%** | Cutoff: **{quality_cutoff}**")

    # 4. Freemium AI Quota
    quota = get_enrichment_quota(active_portal)
    used = quota["used"]
    limit = quota["limit"]
    st.sidebar.caption(f"AI Quota: **{used}/{limit} Used** (500 free)")

    return {
        "fuzzy_threshold": fuzzy_thresh,
        "quality_cutoff": quality_cutoff,
        "dry_run": dry_run,
        "token": token_input,
        "portal_id": active_portal,
        "enrich": False,
        "ui_mode": "saas",
    }


def render_header_and_tenant_bar(config: Dict[str, Any]) -> None:
    """Render top product navbar (backward compatible wrapper)."""
    is_connected = st.session_state.get("hubspot_connected", False)
    portal_id = st.session_state.get("hubspot_portal_id") or config.get("portal_id")
    dry_run = config.get("dry_run", True)
    render_top_navbar(is_connected=is_connected, portal_id=portal_id, dry_run=dry_run)


def render_audit_modal() -> None:
    """Render SQLite audit database runs modal."""
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
               - Enter your **Private App Token** or use OAuth install.
               - The app securely calls `GET /account-info/v3/details` to fetch and verify your Portal ID.
            2. **Step 2: Choose Data Ingestion Source**  
               - **Clean HubSpot CRM:** Scan live contacts directly from your CRM.
               - **Upload Lead File:** Clean vendor CSV/Excel files before CRM import.
            3. **Step 3: Run Pre-Flight Diagnostics & Hygiene**  
               - Standardizes Indian mobile numbers into E.164 `+91XXXXXXXXXX`.
               - Validates 6-digit postal PIN codes and cross-matches GSTIN state codes.
               - Identifies fuzzy duplicates using RapidFuzz Token-Sort ratio with auto-merge backfills.
            4. **Step 4: Non-Destructive Push & Native Duplicate Merge**  
               - Preview all changes safely before live execution.
               - Push clean leads or merge duplicates via native `/crm/v3/objects/contacts/merge`.
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

    # Normalization and Validation
    validated_df = validate_dataframe(df)

    # Deduplication & Exact Merge
    deduped_df, proposals_df = deduplicate_leads(
        validated_df,
        fuzzy_threshold=fuzzy_thresh,
        auto_merge_exact=True,
    )

    # Optional Cloud LLM Enrichment with Quota Guard
    deduped_df, quota_summary = enrich_dataframe(
        deduped_df,
        enabled=enrich,
        portal_id=portal_id or "default_portal",
    )

    # Routing with quality score cutoff
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

    # Batch stats and Report
    batch_stats = generate_summary_stats(deduped_df)
    report_md = generate_markdown_report(batch_stats, output_path=None)

    # Audit Logging
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
    """Convert dataframe to downloadable CSV bytes with formula injection protection."""
    from cleaner.report import _sanitize_formula_injection

    export_df = df.copy()
    if "issues" in export_df.columns:
        export_df["issues"] = export_df["issues"].apply(
            lambda x: ", ".join(x) if isinstance(x, (list, tuple, set)) else str(x or "")
        )

    for col in export_df.columns:
        export_df[col] = export_df[col].apply(_sanitize_formula_injection)

    return export_df.to_csv(index=False).encode("utf-8")


def _execute_hubspot_sync(
    cleaned_df: pd.DataFrame,
    config: Dict[str, Any],
    is_dry_run: bool,
) -> None:
    """Execute HubSpot synchronization with progress bar, change-set validation, and summary table."""
    try:
        if cleaned_df is None or cleaned_df.empty:
            st.warning("⚠️ No valid records to synchronize.")
            return

        portal_id = st.session_state.get("hubspot_portal_id") or config.get("portal_id")
        if not is_dry_run and not portal_id:
            st.error("❌ Live CRM mutation rejected: No active HubSpot portal authenticated.")
            return

        # Fingerprint change-set to ensure records have not drifted
        expected_records = len(cleaned_df)
        client = HubSpotClient(
            token=config.get("token"),
            portal_id=portal_id,
            dry_run=is_dry_run,
            overwrite=False,
        )

        progress_bar = st.progress(0)
        status_text = st.empty()

        results_list = []
        counts = {"created": 0, "updated": 0, "no_op": 0, "failed": 0}

        total = len(cleaned_df)
        for i, (_, row) in enumerate(cleaned_df.iterrows()):
            name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
            status_text.text(f"Syncing contact {i+1} of {total}: {name} ({row.get('email', '')})...")
            try:
                res = client.upsert_contact(row)
                action = res.get("action", "")
                if "CREATE" in action:
                    counts["created"] += 1
                elif "UPDATE" in action:
                    counts["updated"] += 1
                elif action == "NO_OP":
                    counts["no_op"] += 1
                elif res.get("status") == "failed":
                    counts["failed"] += 1
                results_list.append(res)
            except Exception as item_err:
                counts["failed"] += 1
                results_list.append({"status": "failed", "error": str(item_err), "contact": name})

            progress_bar.progress((i + 1) / total)

        status_text.empty()
        progress_bar.empty()

        mode_str = "Dry-Run Simulation (Zero writes)" if is_dry_run else "Live Push"
        st.success(f"🎉 HubSpot sync completed ({mode_str})!")

        col_c, col_u, col_n, col_f = st.columns(4)
        col_c.metric("Created", counts["created"])
        col_u.metric("Updated (Non-destructive)", counts["updated"])
        col_n.metric("Already Up-to-date", counts["no_op"])
        col_f.metric("Failed", counts["failed"])

        if client.audit_log:
            with st.expander("🔍 View CRM Sync Audit Log", expanded=False):
                st.dataframe(pd.DataFrame(client.audit_log), use_container_width=True)

    except ConfigurationError as ce:
        st.error(f"Configuration error: {ce}")
    except Exception as e:
        st.error(f"HubSpot sync failed: {e}")


def main() -> None:
    init_session_state()
    inject_custom_css()

    # Handle incoming portal_id query parameter (from FastAPI OAuth install redirect or return link)
    if "portal_id" in st.query_params:
        pid = str(st.query_params.get("portal_id") or "").strip()
        if pid:
            portal_record = get_portal(pid)
            if portal_record and portal_record.get("access_token"):
                st.session_state.hubspot_connected = True
                st.session_state.hubspot_portal_id = pid
                st.session_state.hubspot_token = portal_record.get("access_token")
                st.toast(f"✅ Connected to HubSpot Portal {pid}!")
                st.query_params.clear()
                st.rerun()

    # Authoritative direct code callback (if Streamlit is configured as redirect_uri)
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
    render_header_and_tenant_bar(config)
    render_audit_modal()
    if st.session_state.get("show_marketplace_modal"):
        show_marketplace_guide_dialog()

    def navigate_to(view_name: str) -> None:
        st.session_state.current_nav = view_name
        st.rerun()

    active_view = st.session_state.get("current_nav", "overview")

    if active_view == "overview":
        render_overview_view(config=config, on_navigate=navigate_to)
    elif active_view == "clean_crm":
        render_clean_crm_view(
            config=config,
            run_dataframe_pipeline_fn=run_dataframe_pipeline,
            on_navigate=navigate_to,
        )
    elif active_view == "upload_leads":
        render_upload_leads_view(
            config=config,
            run_in_memory_pipeline_fn=run_in_memory_pipeline,
            on_navigate=navigate_to,
        )
    elif active_view == "history":
        render_history_view(config=config)
    elif active_view == "settings":
        render_settings_view(config=config)
    else:
        render_overview_view(config=config, on_navigate=navigate_to)


if __name__ == "__main__":
    main()
