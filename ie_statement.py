"""
ie_statement.py — Income & Expenditure Statement for FY 2025-26
Piranjeri Temples Family Trust
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


def render(conn):
    st.header("Income & Expenditure Statement")
    date_from, date_to, fy = date_fy_selector("ie")
    st.subheader(f"Piranjeri Temples Family Trust — FY {fy} ({date_from.strftime('%d %b %Y')} – {date_to.strftime('%d %b %Y')})")
    st.divider()

    sql = """
        SELECT a.id, a.code, a.name, a.account_type,
               COALESCE(SUM(le.debit_amount),  0) AS total_dr,
               COALESCE(SUM(le.credit_amount), 0) AS total_cr
        FROM accounts a
        LEFT JOIN ledger_entries le
               ON le.account_id = a.id AND le.fy = :fy
        WHERE a.account_type IN ('INCOME', 'EXPENDITURE')
          AND a.id NOT IN (22, 23, 24, 25, 26, 27, 28, 29, 30)   -- exclude zero-activity accounts E-10 to E-18
        GROUP BY a.id, a.code, a.name, a.account_type
        ORDER BY a.account_type DESC, a.id
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

    income_df = df[df["account_type"] == "INCOME"].copy()
    exp_df    = df[df["account_type"] == "EXPENDITURE"].copy()

    # Income: net is negative (CR > DR) → display as positive
    income_df["amount"] = (income_df["total_cr"] - income_df["total_dr"]).abs()
    # Expenditure: net is positive (DR > CR)
    exp_df["amount"] = (exp_df["total_dr"] - exp_df["total_cr"]).abs()

    total_income = income_df["amount"].sum()
    total_exp    = exp_df["amount"].sum()
    surplus      = total_income - total_exp

    col1, col2 = st.columns(2)

    # ── INCOME column ─────────────────────────────────────────────────────────
    with col1:
        st.markdown("""
        <div style='background:rgba(34,197,94,0.07); border-radius:10px;
                    padding:16px; border:1px solid rgba(34,197,94,0.2);'>
        """, unsafe_allow_html=True)
        st.markdown("### 📥 Income")
        for _, row in income_df.iterrows():
            if row["amount"] > 0:
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;padding:5px 0;"
                    f"border-bottom:1px solid rgba(34,197,94,0.1)'>"
                    f"<span style='font-size:0.9rem'>{row['code']} &nbsp; {row['name']}</span>"
                    f"<span style='font-family:monospace;font-size:0.9rem'>₹{row['amount']:,.2f}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-weight:700;"
            f"border-top:2px solid rgba(34,197,94,0.4);padding-top:8px;margin-top:4px'>"
            f"<span>Total Income</span>"
            f"<span style='font-family:monospace'>₹{total_income:,.2f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if surplus >= 0:
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;margin-top:6px;color:#16a34a'>"
                f"<span><b>Surplus</b></span>"
                f"<span style='font-family:monospace'><b>₹{surplus:,.2f}</b></span>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between;font-weight:700;"
                f"border-top:2px solid #16a34a;padding-top:6px;margin-top:6px'>"
                f"<span>Grand Total</span>"
                f"<span style='font-family:monospace'>₹{total_exp + surplus:,.2f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    # ── EXPENDITURE column ────────────────────────────────────────────────────
    with col2:
        st.markdown("""
        <div style='background:rgba(239,68,68,0.07); border-radius:10px;
                    padding:16px; border:1px solid rgba(239,68,68,0.2);'>
        """, unsafe_allow_html=True)
        st.markdown("### 📤 Expenditure")
        for _, row in exp_df.iterrows():
            if row["amount"] > 0:
                st.markdown(
                    f"<div style='display:flex;justify-content:space-between;padding:5px 0;"
                    f"border-bottom:1px solid rgba(239,68,68,0.1)'>"
                    f"<span style='font-size:0.9rem'>{row['code']} &nbsp; {row['name']}</span>"
                    f"<span style='font-family:monospace;font-size:0.9rem'>₹{row['amount']:,.2f}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-weight:700;"
            f"border-top:2px solid rgba(239,68,68,0.4);padding-top:8px;margin-top:4px'>"
            f"<span>Total Expenditure</span>"
            f"<span style='font-family:monospace'>₹{total_exp:,.2f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if surplus < 0:
            deficit = abs(surplus)
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;margin-top:6px;color:#dc2626'>"
                f"<span><b>Deficit</b></span>"
                f"<span style='font-family:monospace'><b>₹{deficit:,.2f}</b></span>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between;font-weight:700;"
                f"border-top:2px solid #dc2626;padding-top:6px;margin-top:6px'>"
                f"<span>Grand Total</span>"
                f"<span style='font-family:monospace'>₹{total_income + deficit:,.2f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;font-weight:700;"
                f"border-top:2px solid #ccc;padding-top:6px;margin-top:6px'>"
                f"<span>Grand Total</span>"
                f"<span style='font-family:monospace'>₹{total_exp + surplus:,.2f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    if surplus >= 0:
        st.success(f"✅ Surplus for FY 2025-26: ₹{surplus:,.2f}")
    else:
        st.error(f"⚠️ Deficit for FY 2025-26: ₹{abs(surplus):,.2f}")

    # Download
    out = pd.concat([
        income_df[["code", "name", "amount"]].assign(type="Income"),
        exp_df[["code", "name", "amount"]].assign(type="Expenditure"),
    ])
    csv = out.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download I&E Statement (CSV)", csv,
                       "ie_statement_FY2526.csv", "text/csv")
