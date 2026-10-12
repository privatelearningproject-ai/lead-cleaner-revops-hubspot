"""History and Audit Trail View for Lead Cleaner."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st

from cleaner.db import DEFAULT_DB_PATH, get_connection, get_merge_audits, get_record_audits, get_run
from ui.components import render_empty_state


def render_history_view(config: Dict[str, Any]) -> None:
    """Render the History & Audit Trail screen with real SQLite logs."""
    st.markdown("## 📜 History & Audit Trail")
    st.markdown(
        "Inspect previous lead cleaning runs, CRM synchronizations, duplicate proposals, and record-level transformations logged to the local audit store."
    )

    if not Path(DEFAULT_DB_PATH).exists():
        render_empty_state(
            title="Audit database not yet initialized",
            description="Run your first file cleaning or CRM scan to generate an audit log.",
            icon="📜",
        )
        return

    portal_id = config.get("portal_id") or st.session_state.get("hubspot_portal_id")
    try:
        with get_connection(DEFAULT_DB_PATH) as conn:
            if portal_id:
                runs_df = pd.read_sql_query(
                    "SELECT run_id, timestamp, file_name, total_rows, cleaned_rows, review_rows, dry_run, status FROM runs WHERE portal_id = ? ORDER BY timestamp DESC LIMIT 50",
                    conn,
                    params=(str(portal_id),),
                )
            else:
                runs_df = pd.read_sql_query(
                    "SELECT run_id, timestamp, file_name, total_rows, cleaned_rows, review_rows, dry_run, status FROM runs ORDER BY timestamp DESC LIMIT 50",
                    conn,
                )
    except Exception as e:
        st.error(f"Failed to query audit database: {e}")
        return

    if runs_df.empty:
        render_empty_state(
            title="No past cleaning runs recorded" + (f" for portal {portal_id}" if portal_id else ""),
            description="When you audit a lead file or scan HubSpot contacts, execution details will appear here.",
            icon="📭",
        )
        return

    # User-friendly presentation
    runs_df["Safety Mode"] = runs_df["dry_run"].apply(lambda d: "🛡️ Preview" if d else "⚠️ Live")
    display_df = runs_df.rename(
        columns={
            "run_id": "Run ID",
            "timestamp": "Timestamp",
            "file_name": "Source / File",
            "total_rows": "Total Records",
            "cleaned_rows": "Cleaned",
            "review_rows": "Flagged",
            "status": "Status",
        }
    )

    st.markdown(f"#### Logged Runs ({len(runs_df)})")
    st.dataframe(
        display_df[["Timestamp", "Source / File", "Total Records", "Cleaned", "Flagged", "Safety Mode", "Status", "Run ID"]],
        use_container_width=True,
    )

    # Detailed Run Inspector
    st.markdown("---")
    st.markdown("#### Inspect Specific Run")
    selected_run_id = st.selectbox(
        "Select Run ID to view record audits and merge details:",
        options=runs_df["run_id"].tolist(),
        format_func=lambda rid: f"{rid[:8]}... | {runs_df.loc[runs_df['run_id'] == rid, 'file_name'].values[0]} ({runs_df.loc[runs_df['run_id'] == rid, 'timestamp'].values[0]})",
    )

    if selected_run_id:
        record_audits = get_record_audits(selected_run_id, portal_id=str(portal_id) if portal_id else None)
        merge_audits = get_merge_audits(selected_run_id, portal_id=str(portal_id) if portal_id else None)

        h_tab1, h_tab2 = st.tabs([f"Record Audits ({len(record_audits)})", f"Duplicate Merges ({len(merge_audits)})"])

        with h_tab1:
            if record_audits:
                rec_df = pd.DataFrame(record_audits)
                st.dataframe(rec_df, use_container_width=True)
            else:
                st.info("No individual record audits stored for this run.")

        with h_tab2:
            if merge_audits:
                m_df = pd.DataFrame(merge_audits)
                st.dataframe(m_df, use_container_width=True)
            else:
                st.info("No duplicate merge proposals logged for this run.")
