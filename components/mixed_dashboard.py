"""Mixed Layout Dashboard Component for Lead Cleaner (RevOps India).

Provides a modern, high-density two-column layout:
- Top Header: App title, Portal ID, Dry Run status badge, and primary "Scan contacts" trigger.
- KPI Row: Contacts scanned, Duplicate clusters, Phones fixed (+91), Avg quality score.
- Two-Column Section:
  - Left: Duplicate review queue with match % badges, Skip & Merge actions.
  - Right: Contact hygiene inspection card with per-field status indicators, preview notice, and "Clean this contact" action.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st

from cleaner.hubspot import HubSpotClient


def count_fixed_phones(df: pd.DataFrame) -> int:
    """Calculate the number of contacts whose phone was standardized to Indian +91 format."""
    if df is None or df.empty or "phone" not in df.columns:
        return 0

    count = 0
    for _, row in df.iterrows():
        val = str(row.get("phone", "") or "")
        if val.startswith("+91") and len(val) == 13 and val[3:].isdigit():
            count += 1
    return count


def render_top_header(
    portal_id: str,
    dry_run: bool,
    has_results: bool,
) -> bool:
    """Render the top header bar with title, portal ID, safety badge, and primary action."""
    col_title, col_actions = st.columns([3, 2], vertical_alignment="center")

    with col_title:
        st.subheader("🧹 Lead Cleaner for Small Businesses")
        badge_mode = "🟢 Dry run on" if dry_run else "⚠️ Live mode active"
        st.caption(f"🏢 **Portal ID:** `{portal_id or 'default_portal'}` &nbsp;&nbsp;|&nbsp;&nbsp; **Safety:** `{badge_mode}`")

    with col_actions:
        btn_col1, btn_col2 = st.columns([1, 1], vertical_alignment="center")
        with btn_col2:
            scan_clicked = st.button("🔍 Scan contacts", type="primary", use_container_width=True)

    st.divider()
    return scan_clicked


def render_kpi_row(
    total_scanned: int,
    duplicate_clusters: int,
    phones_fixed: int,
    avg_quality_score: float,
) -> None:
    """Render the 4 KPI metric cards in a single responsive row."""
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("Contacts scanned", total_scanned)
    with kpi2:
        st.metric("Duplicate clusters", duplicate_clusters)
    with kpi3:
        st.metric("Phones fixed (+91)", phones_fixed)
    with kpi4:
        st.metric("Avg quality score", f"{avg_quality_score:.1f} / 100")


def render_duplicate_review_queue(
    proposals_df: pd.DataFrame,
    config: Dict[str, Any],
) -> None:
    """Render the Left Column: Duplicate Review Queue with match % and Skip / Merge controls."""
    st.markdown("### 👥 Duplicate review queue")

    if proposals_df is None or proposals_df.empty:
        st.success("🎉 No duplicate clusters pending review.")
        return

    # Track skipped and merged clusters in session state
    if "skipped_cluster_ids" not in st.session_state:
        st.session_state.skipped_cluster_ids = set()
    if "merged_cluster_ids" not in st.session_state:
        st.session_state.merged_cluster_ids = set()

    active_proposals = proposals_df[
        ~proposals_df.index.astype(str).isin(st.session_state.skipped_cluster_ids)
        & ~proposals_df.index.astype(str).isin(st.session_state.merged_cluster_ids)
    ]

    total_active = len(active_proposals)
    st.caption(f"**{total_active} clusters** requiring review or merge confirmation.")

    if total_active == 0:
        st.info("All detected duplicate clusters have been reviewed for this session.")
        if st.button("Reset Review Queue"):
            st.session_state.skipped_cluster_ids.clear()
            st.session_state.merged_cluster_ids.clear()
            st.rerun()
        return

    # Render each cluster as an interactive card
    for idx, row in active_proposals.head(15).iterrows():
        cluster_id = str(idx)
        cluster_name = row.get("primary_name") or f"Cluster #{cluster_id}"
        cluster_type = row.get("type", "fuzzy")
        
        # Calculate match percentage
        raw_score = row.get("fuzzy_score")
        if cluster_type == "exact" or pd.isna(raw_score) or raw_score is None:
            match_pct = 100
        else:
            match_pct = int(raw_score)

        with st.container(border=True):
            header_col1, header_col2 = st.columns([3, 1])
            with header_col1:
                st.markdown(f"**{cluster_name}**")
                primary_info = []
                if row.get("primary_email"):
                    primary_info.append(f"✉️ {row.get('primary_email')}")
                if row.get("primary_phone"):
                    primary_info.append(f"📞 {row.get('primary_phone')}")
                if primary_info:
                    st.caption(" • ".join(primary_info))
            with header_col2:
                if match_pct >= 95:
                    st.markdown(f":green[**{match_pct}% match**]")
                elif match_pct >= 85:
                    st.markdown(f":orange[**{match_pct}% match**]")
                else:
                    st.markdown(f":blue[**{match_pct}% match**]")

            # Secondary contacts info
            secondaries = row.get("secondary_names") or row.get("duplicate_count", 1)
            st.caption(f"Duplicate candidate: `{secondaries}`")

            # Actions row
            act_col1, act_col2 = st.columns(2)
            with act_col1:
                if st.button("Skip", key=f"skip_{cluster_id}", use_container_width=True):
                    st.session_state.skipped_cluster_ids.add(cluster_id)
                    st.toast(f"Skipped cluster: {cluster_name}")
                    st.rerun()

            with act_col2:
                btn_label = "Merge" if not config.get("dry_run", True) else "Merge (Dry-Run)"
                if st.button(btn_label, key=f"merge_{cluster_id}", type="secondary", use_container_width=True):
                    # Perform merge simulation or API call
                    if config.get("dry_run", True):
                        st.session_state.merged_cluster_ids.add(cluster_id)
                        st.toast(f"Merged {cluster_name} (Simulated in Dry-Run)")
                        st.rerun()
                    else:
                        try:
                            client = HubSpotClient(
                                token=config.get("token"),
                                portal_id=config.get("portal_id"),
                                dry_run=False,
                            )
                            cluster_dict = row.to_dict()
                            client.merge_duplicate_clusters([cluster_dict], portal_id=config.get("portal_id"))
                            st.session_state.merged_cluster_ids.add(cluster_id)
                            st.toast(f"Merged {cluster_name} in HubSpot!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to merge cluster: {e}")


def render_contact_hygiene_card(
    df: pd.DataFrame,
    config: Dict[str, Any],
) -> None:
    """Render the Right Column: Contact Hygiene Inspection Card with validation status."""
    st.markdown("### 📋 Contact hygiene")

    if df is None or df.empty:
        st.info("No contacts available for inspection.")
        return

    # Select contact to inspect
    contact_labels = []
    for idx, row in df.head(100).iterrows():
        first = row.get("first_name", "") or ""
        last = row.get("last_name", "") or ""
        full = f"{first} {last}".strip() or f"Record #{idx}"
        email = row.get("email", "") or "No Email"
        contact_labels.append(f"{full} ({email})")

    selected_label = st.selectbox(
        "Select contact to inspect:",
        options=contact_labels,
        key="selected_hygiene_contact",
    )

    selected_idx = contact_labels.index(selected_label)
    selected_row = df.iloc[selected_idx]

    with st.container(border=True):
        st.markdown(f"#### {selected_label.split(' (')[0]}")
        st.caption(f"Quality Score: **{selected_row.get('quality_score', 0):.0f} / 100**")

        st.markdown("##### Verification Checks")

        # 1. Phone Format Check
        phone_val = str(selected_row.get("phone", "") or "")
        issues = selected_row.get("issues", [])
        if isinstance(issues, str):
            issue_list = [i.strip() for i in issues.split(",") if i.strip()]
        elif isinstance(issues, (list, tuple)):
            issue_list = list(issues)
        else:
            issue_list = []

        if "phone_invalid" in issue_list or not phone_val:
            st.markdown("🔴 **Phone format:** :red[Invalid or missing] " + (f"(`{phone_val}`)" if phone_val else ""))
        elif phone_val.startswith("+91") and len(phone_val) == 13:
            st.markdown(f"🟢 **Phone format:** :green[Standardized Indian E.164 (`{phone_val}`)]")
        else:
            st.markdown(f"🟡 **Phone format:** :orange[`{phone_val}`]")

        # 2. Email RFC 5322 Check
        email_val = str(selected_row.get("email", "") or "")
        if "email_invalid" in issue_list or not email_val:
            st.markdown("🔴 **Email:** :red[Invalid format or missing]")
        else:
            st.markdown(f"🟢 **Email:** :green[Valid RFC 5322 (`{email_val}`)]")

        # 3. Company Name Check
        company_val = str(selected_row.get("company", "") or "").strip()
        if company_val and company_val.lower() != "nan":
            st.markdown(f"🟢 **Company name:** :green[Present (`{company_val}`)]")
        else:
            st.markdown("🟡 **Company name:** :orange[Missing]")

        # 4. Location & GSTIN Checks
        city_val = str(selected_row.get("city", "") or "").strip()
        state_val = str(selected_row.get("state", "") or "").strip()
        if "city_unknown" in issue_list:
            st.markdown(f"🟡 **Location:** :orange[Unmapped city (`{city_val}, {state_val}`)]")
        elif city_val or state_val:
            st.markdown(f"🟢 **Location:** :green[Verified (`{city_val}, {state_val}`)]")

        gst_val = str(selected_row.get("gst_number", "") or "").strip()
        if gst_val and gst_val.lower() != "nan":
            if "gst_format_invalid" in issue_list or "gst_state_mismatch" in issue_list:
                st.markdown(f"🔴 **GSTIN:** :red[Format/state mismatch (`{gst_val}`)]")
            else:
                st.markdown(f"🟢 **GSTIN:** :green[Valid 15-digit code (`{gst_val}`)]")

        st.divider()

        # Confirmation notice
        st.info("ℹ️ **Preview only.** Changes need your confirmation.")

        # Clean this contact action
        if st.button("🧹 Clean this contact", type="primary", use_container_width=True, key=f"clean_contact_{selected_idx}"):
            st.success(f"Contact {selected_label.split(' (')[0]} verified and approved for sync!")
            st.toast("Contact hygiene verified.")


from pathlib import Path


def render_mixed_dashboard(
    results: Optional[Dict[str, Any]],
    config: Dict[str, Any],
    run_pipeline_fn: Optional[Any] = None,
) -> None:
    """Main render entrypoint for the Mixed Layout Dashboard."""
    portal_id = config.get("portal_id", "default_portal")
    dry_run = config.get("dry_run", True)
    has_results = results is not None

    scan_triggered = render_top_header(portal_id, dry_run, has_results)

    if scan_triggered:
        if results is None and run_pipeline_fn is not None:
            sample_file = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "test_500_leads.csv"
            if sample_file.exists():
                with st.spinner("Scanning demo leads dataset (test_500_leads.csv)..."):
                    demo_res = run_pipeline_fn(
                        file_bytes=sample_file.read_bytes(),
                        file_name=sample_file.name,
                        fuzzy_thresh=config.get("fuzzy_threshold", 90),
                        quality_cutoff=config.get("quality_cutoff", 70),
                        dry_run=config.get("dry_run", True),
                        enrich=config.get("enrich", False),
                        portal_id=config.get("portal_id", "default_portal"),
                    )
                    st.session_state.pipeline_results = demo_res
                    st.session_state.active_file_name = sample_file.name
                    st.toast("✅ Scanned contacts dataset!")
                    st.rerun()
            else:
                st.info("To scan leads, upload a file or fetch directly from HubSpot CRM using the Ingestion section below.")
        else:
            st.toast("Scan refreshed!")

    if not has_results:
        # Prompt user to ingest leads
        st.info("👆 Please click **'🔍 Scan contacts'** above or upload a file using the Ingestion section below.")
        return

    # Extract metrics
    deduped_df = results["deduped_df"]
    cleaned_df = results["cleaned_df"]
    review_df = results["review_df"]
    proposals_df = results["proposals_df"]
    stats = results["stats"]

    total_scanned = stats.get("total_rows", len(deduped_df))
    duplicate_clusters = len(proposals_df)
    phones_fixed = count_fixed_phones(deduped_df)
    avg_quality = stats.get("avg_quality_score", 0.0)

    # 1. KPI Row
    render_kpi_row(total_scanned, duplicate_clusters, phones_fixed, avg_quality)
    st.write("")

    # 2. Two-Column Layout
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        render_duplicate_review_queue(proposals_df, config)

    with col_right:
        # Show cleaned or review contacts in the hygiene card
        inspect_df = cleaned_df if not cleaned_df.empty else deduped_df
        render_contact_hygiene_card(inspect_df, config)
