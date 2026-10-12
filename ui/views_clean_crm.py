"""Clean HubSpot CRM Guided Workflow."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import pandas as pd
import streamlit as st

from cleaner.hubspot import ConfigurationError, HubSpotClient
from ui.components import render_empty_state, render_safety_notice, render_step_progress


def render_clean_crm_view(
    config: Dict[str, Any],
    run_dataframe_pipeline_fn: Callable[..., Dict[str, Any]],
    on_navigate: Callable[[str], None],
) -> None:
    """Render the 5-step guided Clean HubSpot CRM workflow."""
    is_connected = st.session_state.get("hubspot_connected", False)
    portal_id = st.session_state.get("hubspot_portal_id") or config.get("portal_id")
    results = st.session_state.get("crm_scan_results")

    # Workflow Header
    st.markdown("## 🏢 Clean HubSpot CRM")
    st.markdown(
        "Scan existing HubSpot contacts, identify duplicate records, and standardize inconsistent phone and contact data — safely in preview mode before applying changes."
    )

    if not is_connected:
        st.warning("⚠️ **HubSpot is not connected.** You must connect your HubSpot account before you can scan CRM records.")
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Connect HubSpot Account →", type="primary", use_container_width=True):
                on_navigate("settings")
        return

    # Steps in workflow
    steps = [
        "1. Select Records",
        "2. Configure Checks",
        "3. Scan & Identify",
        "4. Review Proposed Fixes",
        "5. Apply & Report",
    ]

    current_step = 2 if results is not None else 0
    render_step_progress(steps, current_step)

    # STEP 1 & 2: Configuration & Scan Trigger
    with st.container(border=True):
        st.markdown("#### Step 1: Choose what to scan")
        c_obj1, c_obj2, c_obj3 = st.columns(3)
        with c_obj1:
            st.radio(
                "HubSpot Object:",
                options=["Contacts (Supported)", "Companies (Coming soon)", "Deals (Coming soon)"],
                index=0,
                help="Contacts are fully supported for scanning, deduplication, and non-destructive patching.",
            )
        with c_obj2:
            fetch_limit = st.select_slider(
                "Scan Scope (Max Records):",
                options=[50, 100, 250, 500],
                value=250,
                help="Limits the maximum number of HubSpot contact records fetched for this scan batch.",
            )
        with c_obj3:
            st.caption("Active Account:")
            st.markdown(f"**Portal ID:** `{portal_id}`")
            st.caption(f"Safety Mode: **{'🛡️ Preview (Zero writes)' if config['dry_run'] else '⚠️ Live CRM writes'}**")

        st.markdown("---")
        st.markdown("#### Step 2: Configure data-quality checks")
        col_chk1, col_chk2, col_chk3 = st.columns(3)
        with col_chk1:
            check_dedupe = st.checkbox("Duplicate detection", value=True, help="Find records referring to the same contact by phone, email, or name+city.")
            check_phone = st.checkbox("Phone standardization", value=True, help="Standardize Indian mobile numbers into consistent +91 E.164 format.")
        with col_chk2:
            check_email = st.checkbox("Email syntax validation", value=True, help="Validate email addresses against standard RFC 5322 format.")
            check_missing = st.checkbox("Missing required fields", value=True, help="Flag records missing essential contact info.")
        with col_chk3:
            check_pin = st.checkbox("PIN & GST validation", value=True, help="Validate 6-digit postal PIN codes and verify GSTIN state checksums.")
            check_ai = st.checkbox("AI intent note enrichment", value=config.get("enrich", False), help="Extract budget and intent from notes using Cloud LLM.")

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        col_scan_btn, col_scan_info = st.columns([1.5, 3.5], vertical_alignment="center")
        with col_scan_btn:
            scan_clicked = st.button("🚀 Scan HubSpot Records", type="primary", use_container_width=True, key="start_crm_scan_btn")
        with col_scan_info:
            st.caption(f"Ready to scan up to {fetch_limit} contacts. Changes will only be previewed.")

    # Execute Scan if triggered
    if scan_clicked:
        with st.spinner("Fetching contacts from HubSpot CRM and analyzing data quality..."):
            try:
                client = HubSpotClient(
                    token=config.get("token"),
                    portal_id=portal_id,
                    dry_run=config.get("dry_run", True),
                )
                raw_contacts = client.fetch_contacts(max_records=fetch_limit)
                if not raw_contacts:
                    st.info("No contacts found in HubSpot to scan.")
                else:
                    crm_df = client.contacts_to_dataframe(raw_contacts)
                    source_label = f"HubSpot_CRM_Portal_{portal_id}"
                    results = run_dataframe_pipeline_fn(
                        df=crm_df,
                        source_name=source_label,
                        fuzzy_thresh=config["fuzzy_threshold"],
                        quality_cutoff=config["quality_cutoff"],
                        dry_run=config["dry_run"],
                        enrich=check_ai,
                        portal_id=portal_id,
                    )
                    st.session_state.crm_scan_results = results
                    st.session_state.pipeline_results = results
                    from datetime import datetime, timezone
                    st.session_state.crm_scan_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                    st.success(f"✅ Scanned {len(raw_contacts)} contacts successfully!")
                    st.rerun()
            except ConfigurationError as ce:
                st.error(f"Configuration error: {ce}")
            except Exception as e:
                st.error(f"CRM scan failed: {e}")

    # STEP 3 & 4 & 5: Results & Review
    if results is not None:
        st.markdown("---")
        st.markdown("### Step 3: Scan Results & Findings")
        stats = results["stats"]
        cleaned_df = results["cleaned_df"]
        review_df = results["review_df"]
        proposals_df = results["proposals_df"]

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric("Total Scanned", stats.get("total_rows", 0))
        with k2:
            st.metric("Possible Duplicates", len(proposals_df), help="Duplicate clusters requiring review")
        with k3:
            st.metric("Format & Field Issues", len(review_df), f"{stats.get('review_pct', 0)}% of total")
        with k4:
            st.metric("Clean & Ready", len(cleaned_df), f"{stats.get('cleaned_pct', 0)}% pass rate")

        render_safety_notice(dry_run=config.get("dry_run", True))

        # Review & Approval Tabs
        st.markdown("### Step 4: Review Proposed Fixes")
        tab_dupes, tab_fixes, tab_review_queue, tab_report = st.tabs(
            [
                f"👥 Duplicate Clusters ({len(proposals_df)})",
                f"✨ Field Fixes & Ready ({len(cleaned_df)})",
                f"⚠️ Flagged for Manual Review ({len(review_df)})",
                "📊 Summary Report",
            ]
        )

        with tab_dupes:
            st.markdown("#### Review Duplicate Clusters")
            st.markdown(
                "When duplicate records are merged in HubSpot, non-empty properties from secondary contacts are backfilled into the primary contact, and sales activities are preserved."
            )
            if not proposals_df.empty:
                col_m_info, col_m_btn = st.columns([3, 1.5])
                with col_m_info:
                    st.caption(f"Found **{len(proposals_df)} duplicate clusters**. Review proposals before merging.")
                with col_m_btn:
                    merge_label = "⚡ Merge Duplicates in HubSpot"
                    allow_merge = True
                    if not config["dry_run"]:
                        confirm_merge = st.checkbox("I authorize live contact merges", key="auth_crm_merge")
                        allow_merge = confirm_merge

                    if st.button(merge_label, type="primary", use_container_width=True, key="crm_merge_btn", disabled=not allow_merge):
                        with st.spinner("Executing HubSpot native contact merges..."):
                            try:
                                client = HubSpotClient(
                                    token=config.get("token"),
                                    portal_id=portal_id,
                                    dry_run=config["dry_run"],
                                )
                                merge_records = proposals_df.to_dict(orient="records")
                                res_list = client.merge_duplicate_clusters(merge_records, portal_id=portal_id)
                                successful = sum(1 for r in res_list if r.get("status") in {"success", "dry_run"})
                                mode_text = "Dry-Run Simulation (Zero writes)" if config["dry_run"] else "Live CRM Execution"
                                st.success(f"🎉 Processed {successful} merge pairs ({mode_text})!")
                                with st.expander("Inspection: Merge Audit Log", expanded=True):
                                    st.dataframe(pd.DataFrame(res_list), use_container_width=True)
                            except Exception as e:
                                st.error(f"Failed to merge contacts: {e}")

                st.dataframe(proposals_df, use_container_width=True)
            else:
                st.success("🎉 No duplicate contacts detected in this scanned batch.")

        with tab_fixes:
            st.markdown("#### Standardized & Ready Contacts")
            scan_time = st.session_state.get("crm_scan_timestamp", "Recent")
            st.caption(f"Preview generated at: **{scan_time}**. These contacts pass quality checks with standardized +91 phone numbers and clean email syntax.")

            col_btn_apply, col_btn_dl, col_space = st.columns([1.5, 1.5, 2])
            with col_btn_apply:
                push_label = "⚡ Apply Updates (Preview)" if config["dry_run"] else "⚡ Push Updates to CRM"
                allow_live = True
                if not config["dry_run"]:
                    confirm_write = st.checkbox("I authorize live CRM changes", key="auth_crm_push")
                    allow_live = confirm_write

                if st.button(push_label, type="primary", use_container_width=True, key="crm_push_btn", disabled=not allow_live):
                    from app import _execute_hubspot_sync
                    _execute_hubspot_sync(cleaned_df, config, is_dry_run=config["dry_run"])

            with col_btn_dl:
                from app import to_csv_bytes
                st.download_button(
                    "📥 Export Clean CSV",
                    data=to_csv_bytes(cleaned_df),
                    file_name=f"hubspot_cleaned_contacts_{portal_id}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            # Display Before & After Comparison Table
            if not cleaned_df.empty:
                display_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "quality_score"] if c in cleaned_df.columns]
                st.dataframe(cleaned_df[display_cols], use_container_width=True)

                with st.expander("🔍 Before-and-After Inspection (Raw vs Standardized)"):
                    diff_rows = []
                    for _, r in cleaned_df.head(20).iterrows():
                        diff_rows.append(
                            {
                                "Contact": f"{r.get('first_name', '')} {r.get('last_name', '')}".strip(),
                                "Raw Phone": r.get("raw_phone") or "-",
                                "Normalized Phone (+91)": r.get("phone") or "-",
                                "Raw Email": r.get("raw_email") or "-",
                                "Validated Email": r.get("email") or "-",
                                "Quality Score": f"{r.get('quality_score', 0)}/100",
                            }
                        )
                    st.dataframe(pd.DataFrame(diff_rows), use_container_width=True)
            else:
                st.info("No contacts met the clean threshold.")

        with tab_review_queue:
            st.markdown("#### Flagged Records Requiring Review")
            st.caption("Contacts flagged for invalid phone digits, unrecognized cities, GST state mismatches, or missing consent.")
            if not review_df.empty:
                r_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "issues", "quality_score"] if c in review_df.columns]
                st.dataframe(review_df[r_cols], use_container_width=True)
            else:
                st.success("🎉 Zero contacts flagged for review! 100% passed data-quality validation.")

        with tab_report:
            st.markdown("#### Analytical Markdown Audit Report")
            st.markdown(results.get("report_md", "No report available."))
