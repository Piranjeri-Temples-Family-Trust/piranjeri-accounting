# app_accounting.py — Piranjeri Temples Family Trust Accounting App
# Run: streamlit run app_accounting.py

import streamlit as st
from datetime import datetime, timedelta

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Piranjeri Temples Family Trust — Accounting",
    page_icon="🪔",
    layout="wide",
)

# ── Users & session config ────────────────────────────────────────────────────
USERS = {
    "esrivasan": "Password1",
    "pmk45in":   "Password2",
    "admin3":    "Password3",
}
SESSION_TIMEOUT_MINUTES = 30

# ── Session state init ────────────────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in   = False
    st.session_state.user        = None
    st.session_state.last_active = None

# ── Auto-logout on inactivity ─────────────────────────────────────────────────
if st.session_state.logged_in and st.session_state.last_active:
    idle = datetime.now() - st.session_state.last_active
    if idle > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        st.session_state.logged_in   = False
        st.session_state.user        = None
        st.session_state.last_active = None
        st.warning("Session expired due to inactivity. Please log in again.")

# ── Login screen ──────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    st.title("🪔 Piranjeri Temples Family Trust")
    st.subheader("Accounting System — Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_btn = st.form_submit_button("Login", type="primary")

    if login_btn:
        if username in USERS and USERS[username] == password:
            st.session_state.logged_in   = True
            st.session_state.user        = username
            st.session_state.last_active = datetime.now()
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.stop()

# ── Authenticated — update activity timestamp ─────────────────────────────────
st.session_state.last_active = datetime.now()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🪔 Piranjeri Temples Family Trust")
    st.markdown("**Accounting System**")
    st.divider()
    st.markdown(f"👤 Logged in as **{st.session_state.user}**")
    if st.button("Logout"):
        st.session_state.logged_in   = False
        st.session_state.user        = None
        st.session_state.last_active = None
        st.rerun()
    st.divider()
    st.caption("FY 2025-26 (Apr 2025 – Mar 2026)")

# ── Main content ──────────────────────────────────────────────────────────────
try:
    from expense_entry import render_expense_entry
    render_expense_entry(st.session_state.user)
except Exception as _e:
    import traceback
    st.error(f"Startup error: {_e}")
    st.code(traceback.format_exc())
