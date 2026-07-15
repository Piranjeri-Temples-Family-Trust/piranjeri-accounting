"""
trial_balance.py — Piranjeri Temples Family Trust Accounting
Trial Balance view: reads from ledger_entries, groups by account type.

Usage: call render(conn) from the main app.py tab.
"""

import streamlit as st
import pandas as pd


def render(conn):
    """Render the Trial Balance tab."""

    st.header("Trial Balance — FY 2025-26")

    fy = "2025-26"

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

    total_dr = 0.0
    total_cr = 0.0

    for gtype in group_order:
        gdf = df[df["account_type"] == gtype].copy()
        if gdf.empty:
            continue

        st.subheader(group_labels.get(gtype, gtype))

        display = gdf[["code", "name", "dr_balance", "cr_balance"]].copy()
        display.columns = ["Code", "Account", "Dr Balance (₹)", "Cr Balance (₹)"]
        display = display.reset_index(drop=True)

        # Format numbers
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

        total_dr += grp_dr
        total_cr += grp_cr
        st.divider()

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
