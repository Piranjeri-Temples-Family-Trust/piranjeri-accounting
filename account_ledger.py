"""
account_ledger.py — Piranjeri Temples Family Trust Accounting
Account Ledger view: filter by account, show all entries with running balance.

Usage: call render(conn) from the main app.py tab.
"""

import streamlit as st
import pandas as pd
from datetime import date


def render(conn):
    """Render the Account Ledger tab."""

    st.header("Account Ledger — FY 2025-26")

    fy = "2025-26"

    # ── Load accounts list ──────────────────────────────────────────────────
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a.code || ' — ' || a.name AS label
                FROM accounts a
                ORDER BY a.id
                """
            )
            account_rows = cur.fetchall()
    except Exception as e:
        st.error(f"Database error loading accounts: {e}")
        return

    if not account_rows:
        st.info("No accounts found.")
        return

    account_options = {label: aid for aid, label in account_rows}

    # ── Filters ─────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([3, 2, 2])

    with col1:
        selected_label = st.selectbox("Account", list(account_options.keys()))
    with col2:
        date_from = st.date_input(
            "From",
            value=date(2025, 4, 1),
            min_value=date(2025, 4, 1),
            max_value=date(2026, 3, 31),
        )
    with col3:
        date_to = st.date_input(
            "To",
            value=date(2026, 3, 31),
            min_value=date(2025, 4, 1),
            max_value=date(2026, 3, 31),
        )

    if date_from > date_to:
        st.error("'From' date must be on or before 'To' date.")
        return

    account_id = account_options[selected_label]

    # ── Query ────────────────────────────────────────────────────────────────
    sql = """
        SELECT
            le.id,
            le.entry_date,
            le.narration,
            le.batch_id,
            le.source_type,
            le.debit_amount,
            le.credit_amount
        FROM ledger_entries le
        WHERE le.fy = %s
          AND le.account_id = %s
          AND le.entry_date BETWEEN %s AND %s
        ORDER BY le.entry_date, le.id
    """

    try:
        with conn.cursor() as cur:
            cur.execute(sql, (fy, account_id, date_from, date_to))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    if not rows:
        st.info("No entries found for the selected account and date range.")
        return

    df = pd.DataFrame(rows, columns=cols)

    # ── Opening balance before date_from ────────────────────────────────────
    ob_sql = """
        SELECT COALESCE(SUM(debit_amount) - SUM(credit_amount), 0) AS opening_net
        FROM ledger_entries
        WHERE fy = %s
          AND account_id = %s
          AND entry_date < %s
    """

    try:
        with conn.cursor() as cur:
            cur.execute(ob_sql, (fy, account_id, date_from))
            opening_net = cur.fetchone()[0] or 0.0
    except Exception as e:
        st.error(f"Error loading opening balance: {e}")
        return

    # ── Running balance ──────────────────────────────────────────────────────
    running = float(opening_net)
    running_balances = []
    for _, row in df.iterrows():
        running += float(row["debit_amount"]) - float(row["credit_amount"])
        running_balances.append(running)
    df["running_balance"] = running_balances

    # ── Summary metrics ──────────────────────────────────────────────────────
    total_dr = df["debit_amount"].sum()
    total_cr = df["credit_amount"].sum()
    closing = running_balances[-1] if running_balances else opening_net

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Opening Balance", f"₹{opening_net:,.2f}")
    m2.metric("Total Debits", f"₹{total_dr:,.2f}")
    m3.metric("Total Credits", f"₹{total_cr:,.2f}")
    m4.metric("Closing Balance", f"₹{closing:,.2f}")

    st.divider()

    # ── Display table ─────────────────────────────────────────────────────────
    display = df.copy()
    display["entry_date"] = pd.to_datetime(display["entry_date"]).dt.strftime("%d-%b-%Y")

    # Format amounts
    display["debit_amount"] = display["debit_amount"].apply(
        lambda x: f"{x:,.2f}" if x else "—"
    )
    display["credit_amount"] = display["credit_amount"].apply(
        lambda x: f"{x:,.2f}" if x else "—"
    )
    display["running_balance"] = display["running_balance"].apply(
        lambda x: f"{x:,.2f}"
    )

    display = display.drop(columns=["id"])
    display.columns = ["Date", "Narration", "Batch", "Source", "Dr (₹)", "Cr (₹)", "Balance (₹)"]
    display = display.reset_index(drop=True)

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Narration": st.column_config.TextColumn(width="large"),
        },
    )

    st.caption(f"{len(df)} entries shown.")

    # ── Download ──────────────────────────────────────────────────────────────
    csv = display.to_csv(index=False).encode("utf-8")
    account_code = selected_label.split(" — ")[0]
    st.download_button(
        "⬇ Download Ledger (CSV)",
        data=csv,
        file_name=f"ledger_{account_code}_FY2526.csv",
        mime="text/csv",
    )
