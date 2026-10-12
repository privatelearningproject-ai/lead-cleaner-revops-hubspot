"""UI styles and theme injection for Lead Cleaner.

SaaS Design System:
- Light, clean, trustworthy aesthetic inspired by HubSpot CRM & modern B2B SaaS.
- Palette: #F5F7FA canvas, #FFFFFF cards, #243342 primary text, #617184 secondary text.
- Accent: #FF5C35 HubSpot Warm Orange, #10B981 emerald success, #F59E0B amber warning, #EF4444 red error.
- Typography: Inter with clean weights and comfortable line-heights.
- Interactive components: cards, pills, banners, step indicators, before-after diffs.
"""

from __future__ import annotations
import streamlit as st


def inject_saas_theme() -> None:
    """Inject crisp light-theme CSS tokens and utility classes."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* Clean Streamlit default decoration */
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
            --bg-canvas: #F5F7FA;
            --bg-card: #FFFFFF;
            --bg-subtle: #F8FAFC;
            --text-main: #243342;
            --text-secondary: #617184;
            --text-muted: #8A9CAE;
            --border-light: #DCE3EA;
            --border-strong: #CBD5E1;
            --brand-orange: #FF5C35;
            --brand-orange-hover: #E54B24;
            --brand-blue: #0070F3;
            --status-green: #10B981;
            --status-green-bg: #ECFDF5;
            --status-green-border: #A7F3D0;
            --status-amber: #D97706;
            --status-amber-bg: #FFFBEB;
            --status-amber-border: #FDE68A;
            --status-red: #DC2626;
            --status-red-bg: #FEF2F2;
            --status-red-border: #FECACA;
        }

        .stApp {
            background-color: var(--bg-canvas) !important;
            color: var(--text-main) !important;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        }

        /* Top Brand Bar */
        .app-topbar {
            background: #FFFFFF;
            border-bottom: 1px solid var(--border-light);
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin: -24px -24px 20px -24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        }
        .app-brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .app-logo-badge {
            background: #FF5C35;
            color: white;
            font-size: 1.1rem;
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
        }
        .app-title-group h1 {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-main);
            margin: 0;
            line-height: 1.2;
        }
        .app-title-group p {
            font-size: 0.76rem;
            color: var(--text-secondary);
            margin: 0;
        }

        /* Badges & Chips */
        .badge-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 600;
        }
        .badge-chip-green {
            background: var(--status-green-bg);
            border: 1px solid var(--status-green-border);
            color: #065F46;
        }
        .badge-chip-amber {
            background: var(--status-amber-bg);
            border: 1px solid var(--status-amber-border);
            color: #92400E;
        }
        .badge-chip-gray {
            background: #F1F5F9;
            border: 1px solid var(--border-light);
            color: var(--text-secondary);
        }
        .badge-chip-orange {
            background: #FFF3EB;
            border: 1px solid #FFD4C2;
            color: #C03713;
        }

        /* Hero / Product Introduction */
        .hero-banner {
            background: #FFFFFF;
            border: 1px solid var(--border-light);
            border-radius: 12px;
            padding: 24px 28px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        }
        .hero-tag {
            display: inline-block;
            background: #FFF3EB;
            color: var(--brand-orange);
            font-size: 0.74rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 3px 8px;
            border-radius: 4px;
            margin-bottom: 10px;
        }
        .hero-headline {
            font-size: 1.7rem;
            font-weight: 700;
            color: var(--text-main);
            margin: 0 0 8px 0;
            letter-spacing: -0.02em;
        }
        .hero-subhead {
            font-size: 0.95rem;
            color: var(--text-secondary);
            margin: 0 0 16px 0;
            line-height: 1.5;
            max-width: 760px;
        }

        /* Workflow Cards */
        .workflow-card {
            background: #FFFFFF;
            border: 1px solid var(--border-light);
            border-radius: 12px;
            padding: 22px 24px;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
            transition: all 0.2s ease;
        }
        .workflow-card:hover {
            border-color: var(--brand-orange);
            box-shadow: 0 6px 16px rgba(255, 92, 53, 0.08);
            transform: translateY(-2px);
        }
        .workflow-card-icon {
            width: 44px;
            height: 44px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.35rem;
            margin-bottom: 14px;
        }
        .workflow-icon-orange {
            background: #FFF3EB;
            color: var(--brand-orange);
        }
        .workflow-icon-blue {
            background: #EFF6FF;
            color: #2563EB;
        }
        .workflow-card-title {
            font-size: 1.12rem;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 6px;
        }
        .workflow-card-desc {
            font-size: 0.88rem;
            color: var(--text-secondary);
            line-height: 1.45;
            margin-bottom: 14px;
            flex-grow: 1;
        }
        .workflow-feature-list {
            list-style: none;
            padding: 0;
            margin: 0 0 18px 0;
        }
        .workflow-feature-list li {
            font-size: 0.82rem;
            color: var(--text-main);
            padding: 3px 0;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .workflow-feature-list li::before {
            content: "✓";
            color: var(--status-green);
            font-weight: 700;
        }

        /* Metric Cards */
        .kpi-card {
            background: #FFFFFF;
            border: 1px solid var(--border-light);
            border-radius: 10px;
            padding: 16px 20px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
        }
        .kpi-label {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 6px;
        }
        .kpi-val {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--text-main);
            line-height: 1.1;
        }
        .kpi-sub {
            font-size: 0.74rem;
            color: var(--text-muted);
            margin-top: 4px;
        }

        /* Safety Callout Banner */
        .safety-banner {
            background: #F0FDF4;
            border: 1px solid #BBF7D0;
            border-radius: 8px;
            padding: 12px 18px;
            display: flex;
            align-items: center;
            gap: 12px;
            margin: 16px 0;
            color: #166534;
            font-size: 0.85rem;
        }
        .safety-banner-icon {
            font-size: 1.2rem;
        }

        /* Step Process Indicator */
        .step-container {
            display: flex;
            align-items: center;
            gap: 8px;
            background: #FFFFFF;
            border: 1px solid var(--border-light);
            border-radius: 8px;
            padding: 10px 16px;
            margin-bottom: 20px;
            overflow-x: auto;
        }
        .step-pill {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--text-secondary);
            padding: 4px 10px;
            border-radius: 6px;
            white-space: nowrap;
        }
        .step-pill-active {
            background: #FFF3EB;
            color: var(--brand-orange);
        }
        .step-pill-completed {
            color: var(--status-green);
        }
        .step-num {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: var(--border-light);
            color: var(--text-secondary);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 0.72rem;
            font-weight: 700;
        }
        .step-pill-active .step-num {
            background: var(--brand-orange);
            color: white;
        }
        .step-pill-completed .step-num {
            background: var(--status-green);
            color: white;
        }
        .step-divider {
            color: var(--border-strong);
            font-size: 0.7rem;
        }

        /* Clean Streamlit Widgets overrides */
        button[kind="primary"], div.stButton > button[kind="primary"] {
            background-color: var(--brand-orange) !important;
            border: 1px solid var(--brand-orange) !important;
            color: #FFFFFF !important;
            font-weight: 600 !important;
            border-radius: 6px !important;
            padding: 8px 18px !important;
            font-size: 0.86rem !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
            transition: all 0.15s ease !important;
        }
        button[kind="primary"]:hover, div.stButton > button[kind="primary"]:hover {
            background-color: var(--brand-orange-hover) !important;
            border-color: var(--brand-orange-hover) !important;
        }

        button[kind="secondary"], div.stButton > button[kind="secondary"] {
            background-color: #FFFFFF !important;
            border: 1px solid var(--border-strong) !important;
            color: var(--text-main) !important;
            font-weight: 500 !important;
            border-radius: 6px !important;
            padding: 8px 16px !important;
            font-size: 0.86rem !important;
            transition: all 0.15s ease !important;
        }
        button[kind="secondary"]:hover, div.stButton > button[kind="secondary"]:hover {
            border-color: var(--text-main) !important;
            background-color: #F8FAFC !important;
        }

        /* Dataframes & Tables */
        div[data-testid="stDataFrame"] {
            background: #FFFFFF !important;
            border: 1px solid var(--border-light) !important;
            border-radius: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
