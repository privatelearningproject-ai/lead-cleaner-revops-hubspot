"""Upload Leads Guided Workflow for Lead Cleaner."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import pandas as pd
import streamlit as st

from cleaner.loader import load_mappings, map_columns, read_file
from ui.components import render_empty_state, render_safety_notice, render_step_progress


def render_upload_leads_view(
    config: Dict[str, Any],
    run_in_memory_pipeline_fn: Callable[..., Dict[str, Any]],
    on_navigate: Callable[[str], None],
) -> None:
    """Render the 6-step guided Clean an Uploaded File workflow."""
    is_connected = st.session_state.get("hubspot_connected", False)
    portal_id = st.session_state.get("hubspot_portal_id") or config.get("portal_id")
    results = st.session_state.get("pipeline_results")

    # Workflow Header
    st.markdown("## 📄 Clean an uploaded lead file")
    st.markdown(
        "Upload vendor spreadsheets, expo attendee lists, or offline sales files to standardize contact data, detect duplicates, and preview fixes before importing into HubSpot."
    )

    steps = [
        "1. Upload File",
        "2. Preview & Columns",
        "3. Configure Rules",
        "4. Process & Detect",
        "5. Review & Fix",
        "6. Export / Sync",
    ]
    current_step = 4 if results is not None else (1 if st.session_state.get("uploaded_file_bytes") else 0)
    render_step_progress(steps, current_step)

    # STEP 1: Upload Dropzone
    with st.container(border=True):
        st.markdown("#### Step 1: Upload spreadsheet")
        uploaded_file = st.file_uploader(
            "Select CSV or Excel lead list (.csv, .xlsx, .xls)",
            type=["csv", "xlsx", "xls"],
            help="Supported formats: CSV, XLSX, XLS. Maximum tested file size: 200 MB.",
            key="file_uploader_widget",
        )

        if uploaded_file is not None:
            file_bytes = uploaded_file.getvalue()
            file_size_kb = round(len(file_bytes) / 1024, 1)

            if st.session_state.get("active_file_name") != uploaded_file.name:
                st.session_state.pipeline_results = None
                st.session_state.uploaded_file_bytes = file_bytes
                st.session_state.active_file_name = uploaded_file.name
                results = None

            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            with c1:
                st.markdown(f"**Loaded File:** `{uploaded_file.name}` &nbsp;&nbsp;|&nbsp;&nbsp; **Size:** {file_size_kb} KB")
            with c2:
                if st.button("🔄 Clear File", type="secondary", use_container_width=True):
                    st.session_state.pipeline_results = None
                    st.session_state.uploaded_file_bytes = None
                    st.session_state.active_file_name = None
                    st.rerun()

    # If file loaded, show Preview & Mapping (Step 2 & 3)
    file_bytes = st.session_state.get("uploaded_file_bytes")
    if file_bytes and uploaded_file is not None:
        try:
            raw_preview_df, _ = read_file(file_bytes, filename=uploaded_file.name)
            detected_rows = len(raw_preview_df)
            detected_cols = len(raw_preview_df.columns)

            with st.container(border=True):
                st.markdown(f"#### Step 2: File preview & column detection ({detected_rows} rows, {detected_cols} columns)")
                st.dataframe(raw_preview_df.head(5), use_container_width=True)

                # Column mapping preview
                mappings = load_mappings()
                col_map = map_columns(raw_preview_df, mappings=mappings)

                with st.expander("📋 Review Column Header Mappings", expanded=False):
                    map_display = []
                    for raw_c in raw_preview_df.columns:
                        dest = col_map.get(raw_c)
                        status = "✓ Auto-mapped" if dest else "— Unmapped"
                        map_display.append({"File Column": raw_c, "Destination Field": dest or "Excluded / Raw only", "Status": status})
                    st.dataframe(pd.DataFrame(map_display), use_container_width=True)

            # STEP 3: Configure rules & Run audit
            with st.container(border=True):
                st.markdown("#### Step 3: Configure cleaning rules")
                r_c1, r_c2, r_c3 = st.columns(3)
                with r_c1:
                    st.caption("Standardization:")
                    st.checkbox("Normalize Indian mobile numbers (+91)", value=True, disabled=True)
                    st.checkbox("Standardize city and state names", value=True, disabled=True)
                with r_c2:
                    st.caption("Validation:")
                    st.checkbox("Check RFC 5322 email syntax", value=True, disabled=True)
                    st.checkbox("Verify postal PIN & GSTIN state codes", value=True, disabled=True)
                with r_c3:
                    st.caption("Safety & Quota:")
                    render_safety_notice(dry_run=config.get("dry_run", True))

                btn_c1, btn_c2 = st.columns([1.5, 3.5], vertical_alignment="center")
                with btn_c1:
                    if st.button("🚀 Audit & Clean Lead File", type="primary", use_container_width=True, key="run_file_pipeline_btn"):
                        with st.spinner("Processing file through normalization, validation, and duplicate detection..."):
                            try:
                                results = run_in_memory_pipeline_fn(
                                    file_bytes=file_bytes,
                                    file_name=uploaded_file.name,
                                    fuzzy_thresh=config["fuzzy_threshold"],
                                    quality_cutoff=config["quality_cutoff"],
                                    dry_run=config["dry_run"],
                                    enrich=config.get("enrich", False),
                                    portal_id=portal_id or "default_portal",
                                )
                                st.session_state.pipeline_results = results
                                st.success("✅ File cleaning analysis complete!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Processing failed: {e}")

        except Exception as e:
            st.error(f"Could not parse uploaded file: {e}")

    # STEP 4, 5, 6: Display results when available
    if results is not None:
        st.markdown("---")
        st.markdown("### Step 5: Review Results & Export")
        stats = results["stats"]
        cleaned_df = results["cleaned_df"]
        review_df = results["review_df"]
        proposals_df = results["proposals_df"]

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric("Total Records Ingested", stats.get("total_rows", 0))
        with k2:
            st.metric("Possible Duplicate Clusters", len(proposals_df))
        with k3:
            st.metric("Flagged for Review", len(review_df), f"{stats.get('review_pct', 0)}%")
        with k4:
            st.metric("Clean & Ready Leads", len(cleaned_df), f"{stats.get('cleaned_pct', 0)}% pass rate")

        tab_clean, tab_review, tab_dupes, tab_report = st.tabs(
            [
                f"✨ Clean Leads ({len(cleaned_df)})",
                f"⚠️ Review Queue ({len(review_df)})",
                f"👥 Duplicate Clusters ({len(proposals_df)})",
                "📊 Hygiene Report",
            ]
        )

        from app import _execute_hubspot_sync, to_csv_bytes

        with tab_clean:
            st.markdown("#### Clean & Standardized Leads")
            col_d1, col_d2, col_d3 = st.columns([1.5, 1.5, 2])
            with col_d1:
                st.download_button(
                    "📥 Export Clean CSV",
                    data=to_csv_bytes(cleaned_df),
                    file_name="cleaned_leads.csv",
                    mime="text/csv",
                    type="primary",
                    use_container_width=True,
                )
            with col_d2:
                if is_connected:
                    push_lbl = "⚡ Sync to HubSpot (Preview)" if config["dry_run"] else "⚡ Push Leads to HubSpot"
                    allow_sync = True
                    if not config["dry_run"]:
                        confirm_file_sync = st.checkbox("I authorize live CRM changes", key="auth_file_sync")
                        allow_sync = confirm_file_sync

                    if st.button(push_lbl, type="secondary", use_container_width=True, key="file_push_hs_btn", disabled=not allow_sync):
                        _execute_hubspot_sync(cleaned_df, config, is_dry_run=config["dry_run"])
                else:
                    st.button("⚡ Connect HubSpot to Sync", disabled=True, use_container_width=True)

            if not cleaned_df.empty:
                show_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "gst_number", "quality_score"] if c in cleaned_df.columns]
                st.dataframe(cleaned_df[show_cols], use_container_width=True)
            else:
                st.info("No leads met the clean threshold.")

        with tab_review:
            st.markdown("#### Records Requiring Manual Review")
            st.caption("Leads with invalid mobile digit counts, unknown cities, or GST state mismatches.")
            c_r1, c_r2 = st.columns([1.5, 3.5])
            with c_r1:
                st.download_button(
                    "📥 Export Review Queue CSV",
                    data=to_csv_bytes(review_df),
                    file_name="review_queue.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            if not review_df.empty:
                r_cols = [c for c in ["first_name", "last_name", "phone", "email", "city", "state", "issues", "quality_score"] if c in review_df.columns]
                st.dataframe(review_df[r_cols], use_container_width=True)
            else:
                st.success("🎉 Zero leads flagged for review! All records passed hygiene checks.")

        with tab_dupes:
            st.markdown("#### Duplicate Clusters in Uploaded List")
            if not proposals_df.empty:
                st.dataframe(proposals_df, use_container_width=True)
            else:
                st.success("🎉 Zero duplicate clusters found in this uploaded spreadsheet.")

        with tab_report:
            st.markdown("#### Analytical Markdown Audit Report")
            st.markdown(results.get("report_md", ""))
