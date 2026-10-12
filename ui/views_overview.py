"""Overview / Dashboard View for Lead Cleaner."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
import pandas as pd
import streamlit as st

from ui.components import render_empty_state, render_safety_notice


def render_overview_view(
    config: Dict[str, Any],
    on_navigate: Callable[[str], None],
    on_trigger_scan: Optional[Callable[[], None]] = None,
) -> None:
    """Render the Overview screen: Value proposition, workflow entry cards, metrics, and safety."""
    is_connected = st.session_state.get("hubspot_connected", False)
    portal_id = st.session_state.get("hubspot_portal_id") or config.get("portal_id")
    results = st.session_state.get("pipeline_results")

    # 1. Product Introduction & Hero
    st.markdown(
        """
        <div class="hero-banner">
            <span class="hero-tag">HubSpot Data Quality Workspace</span>
            <h1 class="hero-headline">Keep your HubSpot CRM clean.</h1>
            <p class="hero-subhead">
                Find duplicate records, standardize contact details, and review data-quality fixes before applying them to HubSpot — safely and with complete control.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Dynamic Quick Action Banner
    col_hero_act1, col_hero_act2, col_hero_spacer = st.columns([1.3, 1.3, 2.4])
    with col_hero_act1:
        if not is_connected:
            if st.button("🔗 Connect HubSpot", type="primary", use_container_width=True, key="overview_connect_btn"):
                on_navigate("settings")
        else:
            if st.button("🔍 Scan for issues", type="primary", use_container_width=True, key="overview_scan_btn"):
                on_navigate("clean_crm")
    with col_hero_act2:
        if st.button("📁 Upload lead file", type="secondary", use_container_width=True, key="overview_upload_btn"):
            on_navigate("upload_leads")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # 2. Summary Metrics Row
    st.markdown("### Data Quality Overview")
    if results is not None and "stats" in results:
        stats = results["stats"]
        tot = stats.get("total_rows", 0)
        cleaned_count = stats.get("cleaned_count", 0)
        review_count = stats.get("review_count", 0)
        avg_score = stats.get("avg_quality_score", 0.0)
        duplicate_clusters = len(results.get("proposals_df", []))

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Records Scanned", tot, help="Total contacts or leads processed in current run")
        with m2:
            st.metric("Possible Duplicates", duplicate_clusters, help="Duplicate clusters identified for review or merge")
        with m3:
            st.metric("Data-Quality Issues", review_count, help="Records requiring manual review or formatting fixes")
        with m4:
            st.metric("Ready to Clean", cleaned_count, f"{avg_score:.1f}/100 avg score", help="Records passing quality thresholds")
    else:
        # Honest first-time user empty state
        render_empty_state(
            title="No scan results yet",
            description="Run your first CRM scan or upload a vendor spreadsheet to identify duplicate contacts and data-quality issues.",
            icon="📊",
        )

    # 3. Two Prominent Workflow Entry Cards
    st.markdown("### Choose how you want to clean leads")
    col_wf1, col_wf2 = st.columns(2)

    with col_wf1:
        st.markdown(
            """
            <div class="workflow-card">
                <div>
                    <div class="workflow-card-icon workflow-icon-orange">🏢</div>
                    <div class="workflow-card-title">Option 1: Clean HubSpot CRM</div>
                    <div class="workflow-card-desc">
                        Scan existing HubSpot records for duplicates, invalid contact details, missing information, and other supported data-quality issues.
                    </div>
                    <ul class="workflow-feature-list">
                        <li>Detect duplicates across contacts & companies</li>
                        <li>Standardize Indian mobile numbers to +91 E.164</li>
                        <li>Review all changes in preview before writing to CRM</li>
                    </ul>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if is_connected:
            if st.button("Clean my CRM →", type="primary", use_container_width=True, key="card_clean_crm"):
                on_navigate("clean_crm")
        else:
            if st.button("Connect HubSpot to Clean CRM", type="secondary", use_container_width=True, key="card_connect_crm"):
                on_navigate("settings")
            st.caption("🔒 Requires an active HubSpot connection")

    with col_wf2:
        st.markdown(
            """
            <div class="workflow-card">
                <div>
                    <div class="workflow-card-icon workflow-icon-blue">📄</div>
                    <div class="workflow-card-title">Option 2: Clean an uploaded file</div>
                    <div class="workflow-card-desc">
                        Upload vendor or purchased lead lists, standardize the data, identify possible duplicates, and verify against existing CRM records.
                    </div>
                    <ul class="workflow-feature-list">
                        <li>Supports CSV, XLSX, and XLS formats up to 200 MB</li>
                        <li>Auto-maps column headers to canonical CRM fields</li>
                        <li>Export clean data or sync approved leads to HubSpot</li>
                    </ul>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Upload lead file →", type="primary", use_container_width=True, key="card_upload_leads"):
            on_navigate("upload_leads")

    # 4. Safety Guarantee Callout
    render_safety_notice(dry_run=config.get("dry_run", True))

    # 5. Recent Activity Section (Real SQLite data only)
    st.markdown("### Recent Cleaning Activity")
    from cleaner.db import DEFAULT_DB_PATH, get_connection
    from pathlib import Path

    has_history = False
    if Path(DEFAULT_DB_PATH).exists():
        try:
            with get_connection(DEFAULT_DB_PATH) as conn:
                runs_df = pd.read_sql_query(
                    "SELECT timestamp, file_name as source, total_rows, cleaned_rows, review_rows, dry_run, status FROM runs ORDER BY timestamp DESC LIMIT 5",
                    conn,
                )
                if not runs_df.empty:
                    has_history = True
                    # Clean up column names for business user
                    runs_df["Safety Mode"] = runs_df["dry_run"].apply(lambda d: "🛡️ Preview" if d else "⚠️ Live")
                    runs_df = runs_df.rename(
                        columns={
                            "timestamp": "Date & Time",
                            "source": "Workflow / Source",
                            "total_rows": "Records Scanned",
                            "cleaned_rows": "Cleaned",
                            "review_rows": "Flagged",
                            "status": "Status",
                        }
                    )
                    st.dataframe(runs_df[["Date & Time", "Workflow / Source", "Records Scanned", "Cleaned", "Flagged", "Safety Mode", "Status"]], use_container_width=True)
        except Exception:
            pass

    if not has_history:
        st.caption("No previous runs logged yet. Completed scans will appear here with record-level audit trails.")
