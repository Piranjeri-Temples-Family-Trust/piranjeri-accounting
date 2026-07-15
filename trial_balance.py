"""
trial_balance.py — Piranjeri Temples Family Trust Accounting
Trial Balance view: reads from ledger_entries, groups by account type.

Usage: call render(conn) from the main app.py tab.
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


def render(conn):
    """Render the Trial Balance tab."""

    st.header("Trial Balance")

    date_from, date_to, fy = date_fy_selector("tb")
    st.divider()

    sql = """
        SELECT
            a.id          AS account_id,
            a.code        AS code,
            a.name        AS name,
            a.account_type,
            COALESCE(SUM(le.debit_amount),  0) AS total_dr,
            COALESCE(SUM(le.credit_amount), 0) AS total_cr
        FROM accounts a
        LEFT JOIN ledger_entries le
               ON le.account_id = a.id
              AND le.fy = :fy
        WHERE a.id NOT IN (22, 23, 24, 26)   -- exclude E-10,E-11,E-12,E-14 (zero activity; mapped by trustees)
        GROUP BY a.id, a.code, a.name, a.account_type
        ORDER BY a.id
    """

    try:
        rows = conn.run(sql, fy=fy)
        cols = [c["name"] for c in conn.columns]
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    if not rows:
        st.info("No ledger entries found for FY 2025-26.")
        return

    df = pd.DataFrame(rows, columns=cols)
    df["total_dr"] = df["total_dr"].astype(float)
    df["total_cr"] = df["total_cr"].astype(float)
    df["net"] = df["total_dr"] - df["total_cr"]

    # For normal-balance display: show DR balance accounts in DR col, CR in CR col
    def split_balance(row):
        net = row["net"]
        if net >= 0:
            return net, 0.0
        else:
            return 0.0, abs(net)

    df[["dr_balance", "cr_balance"]] = df.apply(
        split_balance, axis=1, result_type="expand"
    )

    # Group order
    group_order = ["ASSET", "INCOME", "EXPENDITURE", "FUND", "LIABILITY"]
    group_labels = {
        "ASSET":       "Assets",
        "INCOME":      "Income",
        "EXPENDITURE": "Expenditure",
        "FUND":        "Funds",
        "LIABILITY":   "Liabilities",
    }
    group_colors = {
        "ASSET":       "rgba(99,102,241,0.06)",
        "INCOME":      "rgba(34,197,94,0.07)",
        "EXPENDITURE": "rgba(239,68,68,0.06)",
        "FUND":        "rgba(234,179,8,0.06)",
        "LIABILITY":   "rgba(168,85,247,0.06)",
    }
    group_border = {
        "ASSET":       "rgba(99,102,241,0.2)",
        "INCOME":      "rgba(34,197,94,0.25)",
        "EXPENDITURE": "rgba(239,68,68,0.2)",
        "FUND":        "rgba(234,179,8,0.25)",
        "LIABILITY":   "rgba(168,85,247,0.2)",
    }

    total_dr = 0.0
    total_cr = 0.0

    for gtype in group_order:
        gdf = df[df["account_type"] == gtype].copy()
        if gdf.empty:
            continue

        bg  = group_colors.get(gtype, "rgba(99,102,241,0.05)")
        bdr = group_border.get(gtype, "rgba(99,102,241,0.15)")

        st.markdown(
            f"<div style='background:{bg}; border-radius:10px; padding:14px 16px 10px 16px; "
            f"border:1px solid {bdr}; margin-bottom:12px;'>",
            unsafe_allow_html=True,
        )

        st.subheader(group_labels.get(gtype, gtype))

        display = gdf[["code", "name", "dr_balance", "cr_balance"]].copy()
        display.columns = ["Code", "Account", "Dr Balance (₹)", "Cr Balance (₹)"]
        display = display.reset_index(drop=True)

        display["Dr Balance (₹)"] = display["Dr Balance (₹)"].apply(
            lambda x: f"{x:,.2f}" if x else "—"
        )
        display["Cr Balance (₹)"] = display["Cr Balance (₹)"].apply(
            lambda x: f"{x:,.2f}" if x else "—"
        )

        st.dataframe(display, use_container_width=True, hide_index=True)

        grp_dr = gdf["dr_balance"].sum()
        grp_cr = gdf["cr_balance"].sum()

        col1, col2 = st.columns(2)
        with col1:
            if grp_dr:
                st.markdown(f"**Sub-total Dr: ₹{grp_dr:,.2f}**")
        with col2:
            if grp_cr:
                st.markdown(f"**Sub-total Cr: ₹{grp_cr:,.2f}**")

        st.markdown("</div>", unsafe_allow_html=True)

        total_dr += grp_dr
        total_cr += grp_cr

    # Grand total row
    st.subheader("Grand Total")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Debits (₹)", f"{total_dr:,.2f}")
    with col2:
        st.metric("Total Credits (₹)", f"{total_cr:,.2f}")

    diff = abs(total_dr - total_cr)
    if diff < 0.01:
        st.success("✅ Trial Balance is in balance.")
    else:
        st.error(f"⚠️ Out of balance by ₹{diff:,.2f}")

    # Download button
    download_df = df[["code", "name", "account_type", "total_dr", "total_cr", "net"]].copy()
    download_df.columns = ["Code", "Account", "Type", "Total Dr", "Total Cr", "Net"]
    csv = download_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇ Download Trial Balance (CSV)",
        data=csv,
        file_name="trial_balance_FY2526.csv",
        mime="text/csv",
    )
