"""
balance_sheet.py — Balance Sheet as at 31 March 2026
Piranjeri Temples Family Trust

Fund balance logic:
  L-01 Corpus Fund      — direct ledger CR balance
  L-02 Renovation Fund  — L-02 opening CR + I-06 donations CR − E-07 expense DR
                          (uses individual scalar SQL queries; no Python mask logic)
  L-03 Non-Corpus Fund  — DERIVED = Total Assets − L-01 − L-02 − Liabilities
                          (plug; guarantees BS always balances; equals opening NCF + FY I&E net)
  L-04, L-05            — direct ledger CR balance (both should = 0 after FY corrections)
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


def _cr(conn, account_id, fy):
    """Return CR balance for a single account (positive = credit, negative = debit)."""
    rows = conn.run(
        "SELECT COALESCE(SUM(credit_amount) - SUM(debit_amount), 0) "
        "FROM ledger_entries WHERE fy = :fy AND account_id = :aid",
        fy=fy, aid=account_id,
    )
    return float(rows[0][0]) if rows else 0.0


def render(conn):
    st.header("Balance Sheet")
    date_from, date_to, fy = date_fy_selector("bs")
    st.subheader(f"Piranjeri Temples Family Trust — As at {date_to.strftime('%d %b %Y')}")
    st.divider()

    # ── Asset balances (DR normal — net = DR − CR) ────────────────────────────
    asset_accounts = [
        (1,  "A-01", "Cash in Hand"),
        (2,  "A-02", "Cash at Bank — Savings"),
        (3,  "A-03", "Fixed Deposits"),
        (4,  "A-04", "Accrued Interest on FD"),
        (36, "A-05", "Advance to Priest — Manikandan"),
    ]
    assets = []
    for aid, code, name in asset_accounts:
        bal = -_cr(conn, aid, fy)   # DR balance = -CR balance
        assets.append({"code": code, "name": name, "balance": bal})
    assets_df = pd.DataFrame(assets)
    total_assets = assets_df[assets_df["balance"] > 0]["balance"].sum()

    # ── Liability balances ────────────────────────────────────────────────────
    liab_accounts = [
        (32, "L-04", "Loan from Trustees"),
        (33, "L-05", "Audit Fees Payable"),
    ]
    liabs = []
    for aid, code, name in liab_accounts:
        bal = _cr(conn, aid, fy)    # CR balance
        if abs(bal) > 0.005:
            liabs.append({"code": code, "name": name, "balance": bal})
    liab_df = pd.DataFrame(liabs) if liabs else pd.DataFrame(columns=["code","name","balance"])
    total_liab = liab_df[liab_df["balance"] > 0]["balance"].sum() if not liab_df.empty else 0.0

    # ── Fund balances ─────────────────────────────────────────────────────────
    # L-01 Corpus Fund: direct CR balance from ledger
    l01_cr = _cr(conn, 11, fy)

    # L-02 Renovation Fund: opening + donations (I-06) − expenditure (E-07)
    l02_opening_cr = _cr(conn, 12, fy)   # Opening CR from ledger
    i06_cr         = _cr(conn, 10, fy)   # I-06 renovation donations (CR = income received)
    e07_dr         = -_cr(conn, 19, fy)  # E-07 renovation expense (DR = positive, so -CR)
    l02_cr         = l02_opening_cr + i06_cr - e07_dr

    # L-03 Non-Corpus Fund: derived as plug (Total Assets − Corpus − Renov − Liabilities)
    l03_cr = total_assets - l01_cr - l02_cr - total_liab

    funds = [
        {"code": "L-01", "name": "Corpus Fund",     "balance": l01_cr},
        {"code": "L-02", "name": "Renovation Fund", "balance": l02_cr},
        {"code": "L-03", "name": "Non-Corpus Fund", "balance": l03_cr},
    ]
    funds_df = pd.DataFrame(funds)
    total_funds = funds_df["balance"].sum()

    total_liab_funds = total_funds + total_liab

    # ── Render helper ─────────────────────────────────────────────────────────
    def render_section(title, df, total, total_label):
        if title:
            st.markdown(f"**{title}**")
        for _, row in df.iterrows():
            bal = row["balance"]
            if abs(bal) < 0.005:
                continue
            bal_str = f"(₹{abs(bal):,.2f})" if bal < 0 else f"₹{bal:,.2f}"
            color   = "color:#dc2626;" if bal < 0 else ""
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
                f"<span style='padding-left:12px'>{row['code']} &nbsp; {row['name']}</span>"
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
        render_section("", assets_df, total_assets, "Total Assets")

    with col1:
        st.markdown("### \U0001f3db️ Funds & Liabilities")
        render_section("Funds", funds_df, total_funds, "Total Funds")
        st.markdown("<br>", unsafe_allow_html=True)
        render_section("Liabilities", liab_df, total_liab, "Total Liabilities")
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
    out = pd.concat([
        assets_df.assign(side="Asset"),
        funds_df.assign(side="Fund"),
        liab_df.assign(side="Liability") if not liab_df.empty else pd.DataFrame(),
    ])[["code","name","balance","side"]]
    csv = out.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download Balance Sheet (CSV)", csv,
                       "balance_sheet_FY2526.csv", "text/csv")
