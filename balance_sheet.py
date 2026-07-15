"""
balance_sheet.py — Balance Sheet as at 31 March 2026
Piranjeri Temples Family Trust
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


def render(conn):
    st.header("Balance Sheet")
    date_from, date_to, fy = date_fy_selector("bs")
    st.subheader(f"Piranjeri Temples Family Trust — As at {date_to.strftime('%d %b %Y')}")
    st.divider()

    sql = """
        SELECT a.id, a.code, a.name, a.account_type,
               COALESCE(SUM(le.debit_amount),  0) AS total_dr,
               COALESCE(SUM(le.credit_amount), 0) AS total_cr
        FROM accounts a
        LEFT JOIN ledger_entries le
               ON le.account_id = a.id AND le.fy = :fy
        WHERE a.account_type IN ('ASSET', 'FUND', 'LIABILITY')
        GROUP BY a.id, a.code, a.name, a.account_type
        ORDER BY a.account_type, a.id
    """

    try:
        rows = conn.run(sql, fy=fy)
        cols = [c["name"] for c in conn.columns]
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    df = pd.DataFrame(rows, columns=cols)
    df["total_dr"] = df["total_dr"].astype(float)
    df["total_cr"] = df["total_cr"].astype(float)
    df["net"] = df["total_dr"] - df["total_cr"]

    assets_df = df[df["account_type"] == "ASSET"].copy()
    funds_df  = df[df["account_type"] == "FUND"].copy()
    liab_df   = df[df["account_type"] == "LIABILITY"].copy()

    # Assets: positive net = DR balance (normal for assets)
    assets_df["balance"] = assets_df["net"]

    # Funds/Liabilities: negative net = CR balance (normal) → show as positive
    funds_df["balance"] = (-funds_df["net"]).abs()
    liab_df["balance"]  = (-liab_df["net"]).abs()

    total_assets = assets_df[assets_df["balance"] > 0]["balance"].sum()
    total_funds  = funds_df["balance"].sum()
    total_liab   = liab_df["balance"].sum()
    total_liab_funds = total_funds + total_liab

    def render_section(title, section_df, total, total_label):
        st.markdown(f"**{title}**")
        for _, row in section_df.iterrows():
            if abs(row["balance"]) > 0.005:
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
                    f"<span style='padding-left:12px'>{row['code']} &nbsp; {row['name']}</span>"
                    f"<span style='font-family:monospace'>₹{row['balance']:,.2f}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-weight:700;"
            f"border-top:1px solid #ccc;padding-top:4px;margin-top:4px'>"
            f"<span>{total_label}</span>"
            f"<span style='font-family:monospace'>₹{total:,.2f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    col1, col2 = st.columns(2)

    # ── ASSETS (right side) ───────────────────────────────────────────────────
    with col2:
        st.markdown("### 💰 Assets")
        render_section("", assets_df, total_assets, "Total Assets")

    # ── FUNDS & LIABILITIES (left side) ──────────────────────────────────────
    with col1:
        st.markdown("### 🏛️ Funds & Liabilities")
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
    if diff < 1.0:
        st.success(f"✅ Balance Sheet balances. Total: ₹{total_assets:,.2f}")
    else:
        st.warning(f"⚠️ Difference: ₹{diff:,.2f} — Assets ₹{total_assets:,.2f} vs Funds+Liabilities ₹{total_liab_funds:,.2f}")

    # Download
    out = pd.concat([
        assets_df[["code","name","balance"]].assign(side="Asset"),
        funds_df[["code","name","balance"]].assign(side="Fund"),
        liab_df[["code","name","balance"]].assign(side="Liability"),
    ])
    csv = out.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download Balance Sheet (CSV)", csv,
                       "balance_sheet_FY2526.csv", "text/csv")
