"""Meridian Investigation Workspace Enterprise Theme.

Light enterprise theme with deep navy/blue sidebar, bordered KPI cards,
and accessible typography with measured contrast on key interface elements.
Contains zero CDN or external network assets.
"""

import streamlit as st


def inject_theme_css() -> None:
    """Inject scoped CSS for the banking workspace shell."""
    css = """
    <style>
    /* Global layout & typography */
    body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
            Roboto, Helvetica, Arial, sans-serif;
    }

    /* Main container background */
    .stApp {
        background-color: #F8FAFC;
    }

    /* Deep-blue gradient sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0F172A 0%, #1E3A8A 100%) !important;
        color: #F8FAFC !important;
    }

    /* Sidebar text, headers, and labels */
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] h4,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
        color: #F8FAFC !important;
    }

    /* Sidebar navigation radio items */
    section[data-testid="stSidebar"] div[data-testid="stRadio"] > div {
        gap: 0.35rem;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label {
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 6px;
        padding: 0.45rem 0.75rem;
        transition: background 0.15s ease-in-out;
        color: #FFFFFF !important;
        cursor: pointer;
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {
        background: rgba(255, 255, 255, 0.18);
    }
    section[data-testid="stSidebar"] div[data-testid="stRadio"]
        label[data-checked="true"],
    section[data-testid="stSidebar"] div[data-testid="stRadio"] input:checked + div {
        background: rgba(255, 255, 255, 0.25) !important;
        border-color: rgba(255, 255, 255, 0.4) !important;
        font-weight: 600;
    }

    /* Sidebar token input styling */
    section[data-testid="stSidebar"] input {
        background-color: rgba(255, 255, 255, 0.95) !important;
        color: #0F172A !important;
        border-radius: 6px !important;
    }

    /* Bordered containers and card components */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 8px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
        padding: 1rem 1.25rem !important;
    }

    /* Header band styling */
    .meridian-header-band {
        background-color: #FFFFFF;
        border-bottom: 2px solid #E2E8F0;
        padding: 0.75rem 0 1rem 0;
        margin-bottom: 1.25rem;
    }

    /* Case badge */
    .meridian-case-badge {
        display: inline-block;
        background-color: #E0E7FF;
        color: #1E3A8A;
        font-weight: 600;
        font-size: 0.85rem;
        padding: 0.25rem 0.6rem;
        border-radius: 4px;
        border: 1px solid #C7D2FE;
    }

    /* Progress indicator bar */
    .meridian-progress-bar {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.5rem;
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 0.5rem 0.85rem;
        font-size: 0.82rem;
        color: #334155;
        margin-bottom: 1rem;
    }
    .meridian-step-done {
        color: #047857;
        font-weight: 600;
    }
    .meridian-step-pending {
        color: #64748B;
    }

    /* Dataframe table refinements */
    div[data-testid="stDataFrame"] {
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        overflow: hidden;
    }

    /* Notice banner styling */
    .meridian-prototype-notice {
        font-size: 0.82rem;
        font-style: italic;
        color: #475569;
        background-color: #F1F5F9;
        border-left: 3px solid #64748B;
        padding: 0.4rem 0.75rem;
        margin-bottom: 0.75rem;
        border-radius: 0 4px 4px 0;
    }

    /* Reasoning chain indicator */
    .meridian-chain-legend {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 0.6rem 0.9rem;
        font-size: 0.82rem;
        color: #334155;
        margin-bottom: 1rem;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
