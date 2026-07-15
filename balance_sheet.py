"""
def _f(amt):
balance_sheet.py — Balance Sheet as at 31 March 2026
Piranjeri Temples Family Trust

Uses a SINGLE SQL query for all balances to avoid pg8000 connection state issues
with multiple sequential conn.run() calls.

Fund balance logic:
  L-01 Corpus Fund      — direct ledger CR balance (opening only)
  L-02 Renovation Fund  — L-02 opening CR + I-06 donations CR − E-07 expense DR
  L-03 Non-Corpus Fund  — DERIVED = Total Assets − L-01 − L-02 − Liabilities
                          (plug; guarantees BS balances; = opening NCF + FY I&E net)
  L-04, L-05            — direct ledger CR balance (should both = 0 after corrections)
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


def render(conn):
    st.header("Balance Sheet")
    date_from, date_to, fy = date_fy_selector("bs")
    st.subheader(f"Piranjeri Temples Family Trust — As at {date_to.strftime('%d %b %Y')}")
    st.divider()

    # ── Single query: all account balances needed for BS ──────────────────────
    sql = """
        SELECT
            COALESCE(SUM(CASE WHEN account_id =  1 THEN debit_amount - credit_amount ELSE 0 END), 0) AS a01,
            COALESCE(SUM(CASE WHEN account_id =  2 THEN debit_amount - credit_amount ELSE 0 END), 0) AS a02,
            COALESCE(SUM(CASE WHEN account_id =  3 THEN debit_amount - credit_amount ELSE 0 END), 0) AS a03,
            COALESCE(SUM(CASE WHEN account_id =  4 THEN debit_amount - credit_amount ELSE 0 END), 0) AS a04,
            COALESCE(SUM(CASE WHEN account_id = 36 THEN debit_amount - credit_amount ELSE 0 END), 0) AS a05,
            COALESCE(SUM(CASE WHEN account_id = 11 THEN credit_amount - debit_amount ELSE 0 END), 0) AS l01_cr,
            COALESCE(SUM(CASE WHEN account_id = 12 THEN credit_amount - debit_amount ELSE 0 END), 0) AS l02_opening_cr,
            COALESCE(SUM(CASE WHEN account_id = 10 THEN credit_amount - debit_amount ELSE 0 END), 0) AS i06_cr,
            COALESCE(SUM(CASE WHEN account_id = 19 THEN debit_amount - credit_amount ELSE 0 END), 0) AS e07_dr,
            COALESCE(SUM(CASE WHEN account_id = 32 THEN credit_amount - debit_amount ELSE 0 END), 0) AS l04_cr,
            COALESCE(SUM(CASE WHEN account_id = 33 THEN credit_amount - debit_amount ELSE 0 END), 0) AS l05_cr
        FROM ledger_entries
        WHERE fy = :fy
          AND account_id IN (1, 2, 3, 4, 36, 10, 11, 12, 19, 32, 33)
    """
    try:
        rows = conn.run(sql, fy=fy)
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    if not rows:
        st.error("No data returned from database.")
        return

    r = rows[0]
    a01, a02, a03, a04, a05 = [float(x) for x in r[0:5]]
    l01_cr, l02_opening_cr, i06_cr, e07_dr, l04_cr, l05_cr = [float(x) for x in r[5:11]]

    # ── Compute fund balances ─────────────────────────────────────────────────
    l02_cr = l02_opening_cr + i06_cr - e07_dr   # Renovation Fund closing

    total_assets = a01 + a02 + a03 + a04 + a05
    total_liab   = max(l04_cr, 0) + max(l05_cr, 0)

    # L-03 Non-Corpus Fund: derived as plug
    l03_cr = total_assets - l01_cr - l02_cr - total_liab

    total_funds      = l01_cr + l02_cr + l03_cr
    total_liab_funds = total_funds + total_liab

    # ── Build display rows ────────────────────────────────────────────────────
    assets_rows = [
        ("A-01", "Cash in Hand",                  a01),
        ("A-02", "Cash at Bank — Savings",   a02),
        ("A-03", "Fixed Deposits",                 a03),
        ("A-04", "Accrued Interest on FD",         a04),
        ("A-05", "Advance to Priest — Manikandan", a05),
    ]
    fund_rows = [
        ("L-01", "Corpus Fund",     l01_cr),
        ("L-02", "Renovation Fund", l02_cr),
        ("L-03", "Non-Corpus Fund", l03_cr),
    ]
    liab_rows = []
    if abs(l04_cr) > 0.005:
        liab_rows.append(("L-04", "Loan from Trustees",  l04_cr))
    if abs(l05_cr) > 0.005:
        liab_rows.append(("L-05", "Audit Fees Payable", l05_cr))

    # ── Render helper ─────────────────────────────────────────────────────────
    def render_section(title, item_rows, total, total_label):
        if title:
            st.markdown(f"**{title}**")
        for code, name, bal in item_rows:
            if abs(bal) < 0.005:
                continue
            bal_str = f"(₹{abs(bal):,.2f})" if bal < 0 else f"₹{bal:,.2f}"
            color   = "color:#dc2626;" if bal < 0 else ""
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
                f"<span style='padding-left:12px'>{code} &nbsp; {name}</span>"
                f"<span style='font-family:monospace;{color}'>{bal_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        tot_str = f"(₹{abs(total):,.2f})" if total < 0 else f"₹{total:,.2f}"
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-weight:700;"
            f"border-top:1px solid #ccc;padding-top:4px;margin-top:4px'>"
            f"<span>{total_label}</span>"
            f"<span style='font-family:monospace'>{tot_str}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    col1, col2 = st.columns(2)

    with col2:
        st.markdown("### \U0001f4b0 Assets")
        render_section("", assets_rows, total_assets, "Total Assets")

    with col1:
        st.markdown("### \U0001f3db️ Funds & Liabilities")
        render_section("Funds", fund_rows, total_funds, "Total Funds")
        st.markdown("<br>", unsafe_allow_html=True)
        render_section("Liabilities", liab_rows, total_liab, "Total Liabilities")
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-weight:700;"
            f"border-top:2px solid #888;padding-top:6px;margin-top:8px;font-size:1rem'>"
            f"<span>Total Funds &amp; Liabilities</span>"
            f"<span style='font-family:monospace'>₹{total_liab_funds:,.2f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    diff = abs(total_assets - total_liab_funds)
    if diff < 0.50:
        st.success(f"✅ Balance Sheet balances — ₹{total_assets:,.2f}")
    else:
        st.warning(
            f"⚠️ Difference: ₹{diff:,.2f} — "
            f"Assets ₹{total_assets:,.2f} vs Funds+Liabilities ₹{total_liab_funds:,.2f}"
        )

    # ── Download ──────────────────────────────────────────────────────────────
    rows_out = (
        [(c, n, b, "Asset")     for c, n, b in assets_rows] +
        [(c, n, b, "Fund")      for c, n, b in fund_rows] +
        [(c, n, b, "Liability") for c, n, b in liab_rows]
    )
    csv = pd.DataFrame(rows_out, columns=["Code","Account","Balance","Side"]
                       ).to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download Balance Sheet (CSV)", csv,
                       "balance_sheet_FY2526.csv", "text/csv")
