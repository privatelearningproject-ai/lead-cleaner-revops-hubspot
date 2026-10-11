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


def render_sidebar() -> Dict[str, Any]:
    """Render sidebar configuration controls and audit logs viewer."""
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
    token_input = st.sidebar.text_input(
        "HubSpot Private App Token",
        value=env_token or "",
        type="password",
        help="HubSpot token (starts with pat-). Defaults to .env if configured.",
    )

    if token_input:
        st.sidebar.caption("🔑 Token configured")
    else:
        st.sidebar.caption("⚠️ No token configured (Dry-run mock used)")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🏢 HubSpot Multi-Tenant Portal")
    known_portals = [p["portal_id"] for p in list_portals()]
    portal_options = ["default_portal"] + [p for p in known_portals if p != "default_portal"]
    portal_id = st.sidebar.text_input(
        "Connected Portal ID",
        value="default_portal",
        help="HubSpot Account (Portal) ID. Governs OAuth credentials and tenant quota isolation.",
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🤖 Cloud LLM Note Enrichment (Gemini Flash)")

    # Fetch tenant quota status
    quota = get_enrichment_quota(portal_id)
    used = quota["used"]
    limit = quota["limit"]
    remaining = quota["remaining"]
    is_exceeded = quota["is_exceeded"]

    st.sidebar.markdown(f"**Freemium Quota:** `{used} / {limit}` contacts used")
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


def main() -> None:
    init_session_state()

    # Title & Subtitle
    st.title("🧹 Lead Cleaner for Small Businesses (India)")
    st.markdown(
        "Private RevOps lead hygiene and HubSpot ingestion pipeline. "
        "Standardizes **Indian mobile formats (+91)**, verifies **PIN code prefixes**, checks **GSTIN state alignment**, "
        "detects **fuzzy duplicates**, and syncs clean contacts non-destructively."
    )

    config = render_sidebar()
    render_audit_modal()

    # Step 1: Ingestion Mode Selector (File Upload vs Direct HubSpot CRM Sync)
    st.markdown("### 1. Ingest Leads")
    intake_mode = st.radio(
        "Select Data Ingestion Source:",
        options=["📂 Upload File (CSV / Excel)", "🔄 Fetch Direct from HubSpot CRM (API)"],
        horizontal=True,
        help="Choose between staging raw files or scanning your live HubSpot CRM contact database.",
    )

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

    # Step 2: Processing & Metrics Display
    results = st.session_state.pipeline_results
    if results is not None:
        stats = results["stats"]

        st.markdown("---")
        st.markdown("### 2. Hygiene & Quality KPIs")

        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Total Records Ingested", results["stats"]["total_rows"])
        kpi2.metric(
            "Cleaned Leads (Ready)",
            len(results["cleaned_df"]),
            f"{stats['cleaned_pct']}%",
        )
        kpi3.metric(
            "Flagged for Review",
            len(results["review_df"]),
            f"{stats['review_pct']}%",
            delta_color="inverse",
        )
        kpi4.metric("Avg Quality Score", f"{stats['avg_quality_score']} / 100")

        # Step 3: Tabbed Results Explorer
        st.markdown("---")
        st.markdown("### 3. Pipeline Results Explorer")

        tab_cleaned, tab_review, tab_merges, tab_report = st.tabs(
            [
                f"✅ Cleaned Leads ({len(results['cleaned_df'])})",
                f"⚠️ Review Queue ({len(results['review_df'])})",
                f"👥 Duplicate Clusters ({len(results['proposals_df'])})",
                "📊 Audit & Executive Report",
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
