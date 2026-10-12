"""Settings and Preferences View for Lead Cleaner."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
import streamlit as st

from cleaner.db import get_enrichment_quota, get_portal
from cleaner.hubspot import get_token_from_env
from hubspot.connection import HubSpotOAuthProvider, validate_and_connect
from ui.components import render_safety_notice


def render_settings_view(config: Dict[str, Any]) -> None:
    """Render the Settings screen organized into logical sections."""
    st.markdown("## ⚙️ Settings & Configuration")
    st.markdown(
        "Manage your HubSpot connection, duplicate detection sensitivity, data-quality thresholds, and safety preferences."
    )

    is_connected = st.session_state.get("hubspot_connected", False)
    active_portal = st.session_state.get("hubspot_portal_id") or config.get("portal_id")

    set_tab1, set_tab2, set_tab3, set_tab4, set_tab5 = st.tabs(
        [
            "🔗 HubSpot Connection",
            "🛡️ Safety & Execution",
            "👥 Duplicate Matching",
            "📊 Data Quality Thresholds",
            "💳 Freemium Quota & Plan",
        ]
    )

    with set_tab1:
        st.markdown("#### HubSpot Account Authentication")
        st.caption("Connect your HubSpot account via OAuth to scan contacts, detect duplicates, and push standardized records.")

        if is_connected:
            portal_info = get_portal(active_portal) if active_portal else None
            st.success(f"✅ **Connected to HubSpot Account:** Portal ID `{active_portal}`")
            if portal_info:
                st.caption(f"Plan Tier: **{portal_info.get('plan_tier', 'free').upper()}** | Connected Since: {portal_info.get('created_at', 'N/A')[:10]}")
            
            col_dc1, col_dc2 = st.columns([1.5, 3])
            with col_dc1:
                if st.button("Disconnect Account", type="secondary", use_container_width=True, key="settings_disconnect_btn"):
                    if active_portal:
                        from cleaner.db import delete_portal
                        try:
                            delete_portal(active_portal)
                        except Exception:
                            pass
                    st.session_state.hubspot_connected = False
                    st.session_state.hubspot_portal_id = None
                    st.session_state.hubspot_token = ""
                    st.toast("HubSpot account disconnected successfully.")
                    st.rerun()
        else:
            st.info("Your HubSpot account is currently disconnected.")

            backend_api_base = os.environ.get("BACKEND_API_BASE", "").strip().rstrip("/")
            oauth_install_url = f"{backend_api_base}/oauth/install" if backend_api_base else "/oauth/install"

            client_id = os.environ.get("HUBSPOT_CLIENT_ID", "").strip()
            redirect_uri = os.environ.get("HUBSPOT_REDIRECT_URI", "").strip()

            if not client_id or not redirect_uri:
                st.warning(
                    "⚠️ **HubSpot OAuth Configuration Missing**\n\n"
                    "Server environment variables `HUBSPOT_CLIENT_ID` or `HUBSPOT_REDIRECT_URI` are not configured. "
                    "Please set these in your server environment or `.env` file to enable Marketplace installation."
                )

            col_con1, col_con2 = st.columns([1.8, 3.2])
            with col_con1:
                if client_id and redirect_uri:
                    st.link_button(
                        "🟠 Connect HubSpot",
                        oauth_install_url,
                        type="primary",
                        use_container_width=True,
                        help="Initiate secure OAuth 2.0 connection to your HubSpot portal.",
                    )
                else:
                    st.button(
                        "🟠 Connect HubSpot",
                        disabled=True,
                        use_container_width=True,
                        help="OAuth configuration is missing on the server.",
                    )
            with col_con2:
                st.caption(
                    "Secure OAuth 2.0 handshake via HubSpot Marketplace. "
                    "No manual tokens or API keys required."
                )

            # Developer / Direct PAT fallback strictly hidden under advanced accordion
            with st.expander("🛠️ Advanced / Developer Mode (Direct Private App Token)", expanded=False):
                st.caption("For internal testing without OAuth credentials. Standard marketplace users should use OAuth above.")
                env_tok = get_token_from_env() or ""
                current_tok = st.session_state.get("hubspot_token") or env_tok

                tok_val = st.text_input(
                    "Developer Private App Token:",
                    value=current_tok,
                    type="password",
                    help="For local developers only (starts with pat-).",
                    key="settings_token_input",
                )
                if st.button("Connect with Developer Token", key="settings_pat_connect_btn"):
                    if not tok_val.strip():
                        st.error("Please enter a valid Private App Token.")
                    else:
                        with st.spinner("Validating token with HubSpot API..."):
                            ok, pid_res, err = validate_and_connect(tok_val.strip())
                            if ok:
                                st.session_state.hubspot_connected = True
                                st.session_state.hubspot_portal_id = str(pid_res)
                                st.session_state.hubspot_token = tok_val.strip()
                                st.success(f"Connected to Portal {pid_res}!")
                                st.rerun()
                            else:
                                st.error(f"Connection failed: {err}")

    with set_tab2:
        st.markdown("#### Safety & Non-Destructive Execution")
        st.caption("Control whether the application runs in preview mode or executes real modifications to your CRM.")

        dry_val = st.toggle(
            "Preview changes before applying them (Recommended)",
            value=st.session_state.get("cfg_dry_run", config.get("dry_run", True)),
            help="When enabled, all CRM interactions simulate payloads and calculate outcomes without altering HubSpot records.",
            key="cfg_dry_run",
        )

        render_safety_notice(dry_run=dry_val)

        st.markdown("##### Non-Destructive Field Policy")
        st.markdown(
            """
            - **No Blanking:** The app never clears or deletes existing valid CRM data.
            - **Fill Gaps Only:** Standardized values only backfill missing properties unless explicitly instructed.
            - **Audit Trail:** Every merge and update is logged to the local SQLite audit database for verification.
            """
        )

    with set_tab3:
        st.markdown("#### Duplicate Detection Sensitivity")
        st.caption("Adjust the algorithm sensitivity for detecting duplicate leads.")

        fuzzy_val = st.slider(
            "Duplicate matching sensitivity (Name + City):",
            min_value=75,
            max_value=100,
            value=st.session_state.get("cfg_fuzzy_thresh", config.get("fuzzy_threshold", 90)),
            step=1,
            help="Uses RapidFuzz Token-Sort ratio. 90 is recommended. Higher values require closer spelling matches; lower values match looser spelling variations.",
            key="cfg_fuzzy_thresh",
        )
        st.caption(
            f"**Current Sensitivity:** `{fuzzy_val}%`. Phone and email matches are always checked at 100% exact match priority first."
        )

    with set_tab4:
        st.markdown("#### Data-Quality Score Threshold")
        st.caption("Set the minimum hygiene score required to consider a lead ready for CRM import.")

        quality_val = st.slider(
            "Minimum quality score threshold:",
            min_value=50,
            max_value=90,
            value=st.session_state.get("cfg_quality_cutoff", config.get("quality_cutoff", 70)),
            step=5,
            help="Leads scoring below this cutoff are routed to the Review Queue for manual inspection.",
            key="cfg_quality_cutoff",
        )
        st.caption(
            f"**Current Cutoff:** `{quality_val}/100`. Missing valid phone or email deducts 40 points; invalid formats deduct 20 points."
        )

    with set_tab5:
        st.markdown("#### Freemium AI Enrichment Quota")
        quota = get_enrichment_quota(active_portal)
        used = quota["used"]
        limit = quota["limit"]
        remaining = quota["remaining"]

        col_q1, col_q2 = st.columns(2)
        with col_q1:
            st.metric("Records Enriched", f"{used} / {limit}")
        with col_q2:
            st.metric("Free Records Remaining", remaining)

        quota_pct = min(1.0, used / limit if limit > 0 else 1.0)
        st.progress(quota_pct)

        st.caption(
            "Every HubSpot account receives 500 free AI enriched leads using Cloud LLM (Gemini 1.5 Flash) to extract budget and intent."
        )
