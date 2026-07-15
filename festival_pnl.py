"""
festival_pnl.py — Festival-wise Income & Expenditure (P&L drill-down)
Piranjeri Temples Family Trust — FY 2025-26
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


# Fund → (income account_id, expense account_id, display name)
FUND_MAP = {
    "NPK":    (5,  13, "Nithya Pooja Fund"),
    "PRO":    (6,  14, "Pradosham Fund"),
    "GSS":    (7,  17, "Garuda Seva Fund"),
    "VARU":   (8,  18, "Varushabhishekam Fund"),
    "PANGUNI":(9,  15, "Panguni Uthram Fund"),
    "RENOV":  (10, 19, "Renovation Fund"),
}


def _fetch(conn, account_id, fy):
    rows = conn.run(
        "SELECT COALESCE(SUM(debit_amount),0) AS dr, "
        "       COALESCE(SUM(credit_amount),0) AS cr "
        "FROM ledger_entries "
        "WHERE fy = :fy AND account_id = :aid",
        fy=fy, aid=account_id,
    )
    dr = float(rows[0][0]) if rows else 0.0
    cr = float(rows[0][1]) if rows else 0.0
    return dr, cr


def render(conn):
    st.header("Festival P&L Drill-down")
    date_from, date_to, fy = date_fy_selector("fpnl")
    st.subheader(f"Piranjeri Temples Family Trust — FY {fy}")
    st.divider()

    summary_rows = []

    for code, (inc_id, exp_id, name) in FUND_MAP.items():
        inc_dr, inc_cr = _fetch(conn, inc_id, fy)
        exp_dr, exp_cr = _fetch(conn, exp_id, fy)

        income = inc_cr - inc_dr          # income accounts are CR normal
        expense = exp_dr - exp_cr         # expense accounts are DR normal
        surplus = income - expense

        summary_rows.append({
            "Fund": name,
            "Income (₹)": income,
            "Expenditure (₹)": expense,
            "Surplus / (Deficit) (₹)": surplus,
        })

        with st.expander(f"{'✅' if surplus >= 0 else '⚠️'}  {name}  —  {'Surplus' if surplus >= 0 else 'Deficit'} ₹{abs(surplus):,.2f}"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Income", f"₹{income:,.2f}")
            c2.metric("Expenditure", f"₹{expense:,.2f}")
            delta_str = f"₹{abs(surplus):,.2f}"
            if surplus >= 0:
                c3.metric("Surplus", delta_str, delta=delta_str)
            else:
                c3.metric("Deficit", delta_str, delta=f"-{delta_str}")

            # Ledger detail for income account
            st.markdown("**Income entries**")
            try:
                inc_rows = conn.run(
                    "SELECT entry_date, narration, credit_amount "
                    "FROM ledger_entries "
                    "WHERE fy = :fy AND account_id = :aid AND credit_amount > 0 "
                    "ORDER BY entry_date LIMIT 5",
                    fy=fy, aid=inc_id,
                )
                if inc_rows:
                    idf = pd.DataFrame(inc_rows, columns=["Date", "Narration", "Amount"])
                    idf["Amount"] = idf["Amount"].astype(float).apply(lambda x: f"₹{x:,.2f}")
                    st.dataframe(idf, hide_index=True, use_container_width=True)
                    st.caption("(Showing first 5 entries)")
            except Exception as e:
                st.caption(f"Could not load detail: {e}")

    # ── Summary table ─────────────────────────────────────────────────────────
    st.divider()
    st.markdown("""
    <div style='background:rgba(99,102,241,0.07); border-radius:10px;
                padding:16px 18px; border:1px solid rgba(99,102,241,0.18); margin-bottom:8px;'>
    """, unsafe_allow_html=True)
    st.markdown("### Summary")
    sdf = pd.DataFrame(summary_rows)
    totals = {
        "Fund": "TOTAL",
        "Income (₹)": sdf["Income (₹)"].sum(),
        "Expenditure (₹)": sdf["Expenditure (₹)"].sum(),
        "Surplus / (Deficit) (₹)": sdf["Surplus / (Deficit) (₹)"].sum(),
    }
    sdf = pd.concat([sdf, pd.DataFrame([totals])], ignore_index=True)

    def color_surplus(val):
        if isinstance(val, float):
            return "color: green; font-weight:bold" if val >= 0 else "color: red; font-weight:bold"
        return ""

    styled = (
        sdf.style
        .format({
            "Income (₹)": "₹{:,.2f}",
            "Expenditure (₹)": "₹{:,.2f}",
            "Surplus / (Deficit) (₹)": "₹{:,.2f}",
        })
        .map(color_surplus, subset=["Surplus / (Deficit) (₹)"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("</div>", unsafe_allow_html=True)

    csv = sdf.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download Festival P&L (CSV)", csv,
                       "festival_pnl_FY2526.csv", "text/csv")
