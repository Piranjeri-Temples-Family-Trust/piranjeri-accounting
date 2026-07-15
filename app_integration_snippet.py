"""
app_integration_snippet.py
==========================
Add the Trial Balance and Account Ledger tabs to your existing app.py.

STEP 1 — Copy trial_balance.py and account_ledger.py into the same folder as app.py.

STEP 2 — At the top of app.py, add these two imports alongside your existing ones:

    import trial_balance
    import account_ledger

STEP 3 — Find where your existing tabs are defined. It will look something like:

    tab1, tab2, tab3 = st.tabs(["Journal Entry", "Bank Statement", "Edit/Void"])

    Change it to add the two new tabs:

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Journal Entry",
        "Trial Balance",       # NEW
        "Account Ledger",      # NEW
        "Bank Statement",
        "Edit/Void",
    ])

STEP 4 — Inside the new tab blocks, call the render functions:

    with tab4:   # (use whatever tab variable name Trial Balance gets)
        trial_balance.render(conn)

    with tab5:   # (use whatever tab variable name Account Ledger gets)
        account_ledger.render(conn)

    (conn is your existing psycopg2 connection object — the same one used by
    Journal Entry and the other tabs.)

STEP 5 — Commit and push to GitHub. Streamlit Cloud will redeploy automatically.

That's all. No database changes needed — both views read from ledger_entries only.
"""

# ── Minimal standalone example (for reference / local testing) ───────────────
# If you want to test these views in isolation before integrating, create a
# test_views.py with:

import streamlit as st
import psycopg2

@st.cache_resource
def get_connection():
    dsn = st.secrets["neon"]["dsn"]
    return psycopg2.connect(dsn)

conn = get_connection()

tab_tb, tab_al = st.tabs(["Trial Balance", "Account Ledger"])

import trial_balance
import account_ledger

with tab_tb:
    trial_balance.render(conn)

with tab_al:
    account_ledger.render(conn)
