"""
journal_book.py — Journal Book (all double-entry postings)
Piranjeri Temples Family Trust — FY 2025-26
Shows every transaction with its Dr and Cr legs and narration.
"""

import streamlit as st
import pandas as pd
from datetime import date


def render(conn):
    st.header("📖 Journal Book — FY 2025-26")
    st.caption("All accounting entries — both debit and credit legs of each transaction.")
    st.divider()

    fy = "2025-26"

    # ── Filters ───────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
    with col1:
        date_from = st.date_input("From", value=date(2025, 4, 1),
                                  min_value=date(2025, 4, 1), max_value=date(2026, 3, 31))
    with col2:
        date_to = st.date_input("To", value=date(2026, 3, 31),
                                min_value=date(2025, 4, 1), max_value=date(2026, 3, 31))
    with col3:
        # Batch filter
        try:
            batch_rows = conn.run(
                "SELECT DISTINCT batch_id FROM ledger_entries "
                "WHERE fy = :fy ORDER BY batch_id",
                fy=fy,
            )
            batch_list = ["All"] + [r[0] for r in batch_rows]
        except Exception:
            batch_list = ["All"]
        selected_batch = st.selectbox("Batch", batch_list)
    with col4:
        search = st.text_input("Search narration", placeholder="e.g. Abhishekam")

    if date_from > date_to:
        st.error("'From' date must be on or before 'To' date.")
        return

    # ── Query ─────────────────────────────────────────────────────────────────
    sql = """
        SELECT
            le.entry_date,
            le.batch_id,
            le.source_type,
            le.narration,
            a.code       AS account_code,
            a.name       AS account_name,
            le.debit_amount,
            le.credit_amount,
            le.id
        FROM ledger_entries le
        JOIN accounts a ON a.id = le.account_id
        WHERE le.fy = :fy
          AND le.entry_date BETWEEN :date_from AND :date_to
        ORDER BY le.entry_date, le.batch_id, le.id
    """

    try:
        rows = conn.run(sql, fy=fy, date_from=date_from, date_to=date_to)
        cols = [c["name"] for c in conn.columns]
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    df = pd.DataFrame(rows, columns=cols)
    df["debit_amount"]  = df["debit_amount"].astype(float)
    df["credit_amount"] = df["credit_amount"].astype(float)

    # Apply filters
    if selected_batch != "All":
        df = df[df["batch_id"] == selected_batch]
    if search.strip():
        df = df[df["narration"].str.contains(search.strip(), case=False, na=False)]

    if df.empty:
        st.info("No entries found for the selected filters.")
        return

    # ── Metrics ───────────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Entries", f"{len(df):,}")
    m2.metric("Total Debits", f"₹{df['debit_amount'].sum():,.2f}")
    m3.metric("Total Credits", f"₹{df['credit_amount'].sum():,.2f}")

    st.divider()

    # ── Display ───────────────────────────────────────────────────────────────
    display = df.copy()
    display["entry_date"] = pd.to_datetime(display["entry_date"]).dt.strftime("%d-%b-%Y")
    display["debit_amount"]  = display["debit_amount"].apply(
        lambda x: f"₹{x:,.2f}" if x > 0 else "—")
    display["credit_amount"] = display["credit_amount"].apply(
        lambda x: f"₹{x:,.2f}" if x > 0 else "—")

    display = display.drop(columns=["id"])
    display.columns = ["Date", "Batch", "Source", "Narration",
                       "Account Code", "Account Name", "Dr (₹)", "Cr (₹)"]
    display = display.reset_index(drop=True)

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Narration":    st.column_config.TextColumn(width="large"),
            "Account Name": st.column_config.TextColumn(width="medium"),
        },
        height=600,
    )

    st.caption(f"Showing {len(df):,} entries.")

    # ── Download ──────────────────────────────────────────────────────────────
    csv = display.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download Journal Book (CSV)", csv,
                       "journal_book_FY2526.csv", "text/csv")
