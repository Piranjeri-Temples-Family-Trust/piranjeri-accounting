"""
ptft_utils.py — Shared utilities for Piranjeri Trust Accounting App
"""

from datetime import date
import streamlit as st


def fy_from_date(d: date) -> str:
    """Return FY string e.g. '2025-26' for a given date.
    Accounting year: April 1 – March 31.
    """
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def date_fy_selector(key_prefix: str = "",
                     default_from: date = None,
                     default_to: date = None):
    """
    Render From / To date pickers + auto-derived Financial Year label.
    Returns (date_from, date_to, fy_string).
    """
    if default_from is None:
        default_from = date(2025, 4, 1)
    if default_to is None:
        default_to = date(2026, 3, 31)

    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=default_from,
                                  key=f"{key_prefix}_from")
    with col2:
        date_to = st.date_input("To", value=default_to,
                                key=f"{key_prefix}_to")

    fy = fy_from_date(date_from)
    st.markdown(
        f"<p style='font-size:0.82rem;color:#888;margin-top:2px'>"
        f"📅 Financial Year: <b>{fy}</b>"
        f"</p>",
        unsafe_allow_html=True,
    )

    return date_from, date_to, fy
