# app_accounting.py — Piranjeri Temples Family Trust Accounting App
import streamlit as st
import pg8000.native
from urllib.parse import urlparse
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Piranjeri Temples Family Trust — Accounting",
    page_icon="🪔",
    layout="wide",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Sidebar base */
[data-testid="stSidebar"] > div:first-child {
    display: flex;
    flex-direction: column;
    height: 100vh;
    padding: 1rem 0.8rem;
}

/* Nav buttons */
div[data-testid="stSidebar"] .stButton > button {
    width: 100%;
    text-align: left;
    background: transparent;
    border: none;
    color: inherit;
    font-size: 0.95rem;
    padding: 0.4rem 0.6rem;
    border-radius: 6px;
    margin-bottom: 2px;
}
div[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.08);
}

/* Logout button — small */
div[data-testid="stSidebar"] .logout-btn button {
    font-size: 0.72rem !important;
    padding: 0.2rem 0.5rem !important;
    color: #aaa !important;
    border: 1px solid #555 !important;
}

/* Active page highlight */
.nav-active button {
    background: rgba(99,102,241,0.25) !important;
    border-left: 3px solid #6366f1 !important;
}
</style>
""", unsafe_allow_html=True)

# ── Users ─────────────────────────────────────────────────────────────────────
USERS = {
    "esrivasan": "Password1",
    "pmk45in":   "Password2",
    "admin3":    "Password3",
}
SESSION_TIMEOUT_MINUTES = 30

# ── Session state ─────────────────────────────────────────────────────────────
for key, val in [
    ("logged_in", False), ("user", None),
    ("last_active", None), ("page", "trial_balance"),
    ("fin_expanded", False),
]:
    if key not in st.session_state:
        st.session_state[key] = val

# ── Auto-logout ───────────────────────────────────────────────────────────────
if st.session_state.logged_in and st.session_state.last_active:
    if datetime.now() - st.session_state.last_active > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        st.session_state.logged_in = False
        st.warning("Session expired. Please log in again.")

# ── Login screen ──────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col = st.columns([1, 1, 1])[1]
    with col:
        st.markdown("<h2 style='text-align:center'>🪔</h2>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align:center'>Piranjeri Temples Family Trust</h3>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#888'>Accounting System</p>", unsafe_allow_html=True)
        st.divider()
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                if username in USERS and USERS[username] == password:
                    st.session_state.logged_in   = True
                    st.session_state.user        = username
                    st.session_state.last_active = datetime.now()
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
    st.stop()

st.session_state.last_active = datetime.now()

# ── DB connection ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_connection():
    dsn = st.secrets["neon"]["dsn"]
    p = urlparse(dsn)
    return pg8000.native.Connection(
        user=p.username, password=p.password,
        host=p.hostname, port=p.port or 5432,
        database=p.path.lstrip("/"), ssl_context=True,
    )

conn = get_connection()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:

    # ── Title ─────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style='text-align:center; padding:0.5rem 0 0.2rem 0'>
        <span style='font-size:1.8rem'>🪔</span><br>
        <span style='font-weight:700; font-size:1rem'>Piranjeri Temples</span><br>
        <span style='font-weight:700; font-size:1rem'>Family Trust</span><br>
        <span style='font-size:0.78rem; color:#aaa; letter-spacing:1px'>ACCOUNTING SYSTEM</span>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # ── Navigation ────────────────────────────────────────────────────────────
    def nav_btn(label, page_key):
        active = st.session_state.page == page_key
        prefix = "▶ " if active else "   "
        if st.button(f"{prefix}{label}", key=f"nav_{page_key}", use_container_width=True):
            st.session_state.page = page_key
            st.session_state.fin_expanded = False
            st.rerun()

    nav_btn("📝  Journal", "journal")
    nav_btn("📒  Account Ledger", "account_ledger")
    nav_btn("⚖️  Trial Balance", "trial_balance")
    nav_btn("📖  Journal Book", "journal_book")

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    # Financial Statements — collapsible
    fin_pages = {"ie": "Income & Expenditure", "bs": "Balance Sheet", "fpnl": "Festival P&L"}
    fin_active = st.session_state.page in fin_pages

    fin_label = "📊  Financial Statements ▼" if (st.session_state.fin_expanded or fin_active) else "📊  Financial Statements ▶"
    if st.button(fin_label, key="nav_fin_toggle", use_container_width=True):
        st.session_state.fin_expanded = not st.session_state.fin_expanded
        st.rerun()

    if st.session_state.fin_expanded or fin_active:
        for key, label in fin_pages.items():
            active = st.session_state.page == key
            prefix = "  ▶ " if active else "      "
            if st.button(f"{prefix}{label}", key=f"nav_{key}", use_container_width=True):
                st.session_state.page = key
                st.rerun()

    # ── Spacer ────────────────────────────────────────────────────────────────
    st.markdown("<div style='flex:1'></div>", unsafe_allow_html=True)
    for _ in range(8):
        st.write("")
    st.divider()

    # ── Footer: logout left, clock+user right ─────────────────────────────────
    now = datetime.now()
    col_left, col_right = st.columns([1, 1.4])

    with col_left:
        st.markdown("<div class='logout-btn'>", unsafe_allow_html=True)
        if st.button("⏻ Logout", key="logout_btn"):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.last_active = None
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with col_right:
        st.markdown(f"""
        <div style='text-align:right; line-height:1.5; padding-top:2px'>
            <span style='font-size:1.1rem; font-weight:700; font-family:monospace'>
                {now.strftime('%H:%M')}
            </span><br>
            <span style='font-size:0.72rem; color:#bbb'>{now.strftime('%d %b %Y')}</span><br>
            <span style='font-size:0.72rem; color:#6366f1'>👤 {st.session_state.user}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"<p style='font-size:0.65rem;color:#555;text-align:center;margin-top:4px'>FY 2025-26</p>",
                unsafe_allow_html=True)

# ── Main content routing ──────────────────────────────────────────────────────
page = st.session_state.page

if page == "journal":
    try:
        from expense_entry import render_expense_entry
        render_expense_entry(st.session_state.user)
    except Exception as e:
        import traceback
        st.error(f"Journal error: {e}")
        st.code(traceback.format_exc())

elif page == "account_ledger":
    try:
        import account_ledger
        account_ledger.render(conn)
    except Exception as e:
        import traceback
        st.error(f"Account Ledger error: {e}")
        st.code(traceback.format_exc())

elif page == "trial_balance":
    try:
        import trial_balance
        trial_balance.render(conn)
    except Exception as e:
        import traceback
        st.error(f"Trial Balance error: {e}")
        st.code(traceback.format_exc())

elif page == "journal_book":
    try:
        import journal_book
        journal_book.render(conn)
    except Exception as e:
        import traceback
        st.error(f"Journal Book error: {e}")
        st.code(traceback.format_exc())

elif page == "ie":
    try:
        import ie_statement
        ie_statement.render(conn)
    except Exception as e:
        import traceback
        st.error(f"I&E Statement error: {e}")
        st.code(traceback.format_exc())

elif page == "bs":
    try:
        import balance_sheet
        balance_sheet.render(conn)
    except Exception as e:
        import traceback
        st.error(f"Balance Sheet error: {e}")
        st.code(traceback.format_exc())

elif page == "fpnl":
    try:
        import festival_pnl
        festival_pnl.render(conn)
    except Exception as e:
        import traceback
        st.error(f"Festival P&L error: {e}")
        st.code(traceback.format_exc())
