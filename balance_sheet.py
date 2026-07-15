"""
balance_sheet.py — Balance Sheet as at 31 March 2026
Piranjeri Temples Family Trust

Renovation Fund (L-02): not directly updated in ledger during the year.
  Closing = Opening CR  +  I-06 donations CR  −  E-07 expenditure DR
  Accounts: L-02 id=12, I-06 id=10, E-07 id=19

Non-Corpus Fund (L-03): absorbs FY I&E surplus/deficit.
  Closing = Opening CR balance  +  FY I&E net (surplus positive, deficit negative)
  Exclude I-06 and E-07 from I&E net (those go to Renovation Fund).
  Account: L-03 id=31
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


def _fetch_single_net(conn, account_ids, fy):
    """Return {account_id: (DR-CR) net} for given IDs."""
    ids_str = ','.join(str(i) for i in account_ids)
    rows = conn.run(
        f"SELECT a.id, "
        f"COALESCE(SUM(le.debit_amount),0) AS dr, "
        f"COALESCE(SUM(le.credit_amount),0) AS cr "
        f"FROM accounts a "
        f"LEFT JOIN ledger_entries le ON le.account_id = a.id AND le.fy = :fy "
        f"WHERE a.id IN ({ids_str}) "
        f"GROUP BY a.id",
        fy=fy,
    )
    return {int(r[0]): float(r[1]) - float(r[2]) for r in rows}


def render(conn):
    st.header("Balance Sheet")
    date_from, date_to, fy = date_fy_selector("bs")
    st.subheader(f"Piranjeri Temples Family Trust — As at {date_to.strftime('%d %b %Y')}")
    st.divider()

    # ── Main BS query ─────────────────────────────────────────────────────────
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
    df["net"] = df["total_dr"] - df["total_cr"]   # positive = DR balance

    assets_df = df[df["account_type"] == "ASSET"].copy()
    funds_df  = df[df["account_type"] == "FUND"].copy()
    liab_df   = df[df["account_type"] == "LIABILITY"].copy()

    # Assets: DR balance (net) is the balance
    assets_df["balance"] = assets_df["net"]

    # Liabilities: CR balance → balance = -net (positive amount owed)
    liab_df["balance"] = -liab_df["net"]

    # Funds: initialise as CR balance (-net); L-02 and L-03 are overridden below
    funds_df["balance"] = -funds_df["net"]

    # ── L-02 Renovation Fund closing balance ──────────────────────────────────
    # Closing CR = L-02 opening CR  +  I-06 donations CR  −  E-07 expenditure DR
    try:
        adj = _fetch_single_net(conn, [10, 19], fy)   # I-06 id=10, E-07 id=19
        i06_net = adj.get(10, 0.0)   # negative (income CR)
        e07_net = adj.get(19, 0.0)   # positive (expense DR)

        l02_mask = funds_df["id"] == 12
        if l02_mask.any():
            l02_net = float(funds_df.loc[l02_mask, "net"].iloc[0])
            # CR balances: L-02 CR = -l02_net, I-06 CR = -i06_net, E-07 DR = e07_net
            l02_closing_cr = (-l02_net) + (-i06_net) - e07_net
            funds_df.loc[l02_mask, "balance"] = l02_closing_cr
    except Exception as ex:
        st.caption(f"Renovation Fund adjustment error: {ex}")

    # ── L-03 Non-Corpus Fund closing balance ──────────────────────────────────
    # Closing CR = L-03 opening CR  +  FY I&E net surplus (income − expenditure)
    # Excludes I-06 and E-07 (those belong to Renovation Fund above)
    try:
        ie_sql = """
            SELECT
                COALESCE(SUM(
                    CASE WHEN a.account_type = 'INCOME'
                         THEN le.credit_amount - le.debit_amount ELSE 0 END
                ), 0)
                - COALESCE(SUM(
                    CASE WHEN a.account_type = 'EXPENDITURE'
                         THEN le.debit_amount - le.credit_amount ELSE 0 END
                ), 0)  AS ie_net
            FROM accounts a
            LEFT JOIN ledger_entries le ON le.account_id = a.id AND le.fy = :fy
            WHERE a.account_type IN ('INCOME', 'EXPENDITURE')
              AND a.id NOT IN (10, 19)
        """
        ie_rows = conn.run(ie_sql, fy=fy)
        ie_net = float(ie_rows[0][0]) if ie_rows else 0.0
        # ie_net: positive = surplus, negative = deficit

        l03_mask = funds_df["id"] == 31
        if l03_mask.any():
            l03_net = float(funds_df.loc[l03_mask, "net"].iloc[0])
            l03_cr_opening = -l03_net        # e.g. +91875.40 net → -91875.40 CR (debit-balance fund)
            l03_closing_cr = l03_cr_opening + ie_net
            funds_df.loc[l03_mask, "balance"] = l03_closing_cr
    except Exception as ex:
        st.caption(f"Non-Corpus Fund adjustment error: {ex}")

    # ── Totals ────────────────────────────────────────────────────────────────
    total_assets     = assets_df[assets_df["balance"] > 0]["balance"].sum()
    total_funds      = funds_df["balance"].sum()     # signed: debit-balance funds reduce total
    total_liab       = liab_df[liab_df["balance"] > 0]["balance"].sum()
    total_liab_funds = total_funds + total_liab

    # ── Render helper ─────────────────────────────────────────────────────────
    def render_section(title, section_df, total, total_label):
        if title:
            st.markdown(f"**{title}**")
        for _, row in section_df.iterrows():
            bal = row["balance"]
            if abs(bal) < 0.005:
                continue
            if bal < 0:
                bal_str = f"(₹{abs(bal):,.2f})"
                color   = "color:#dc2626;"
            else:
                bal_str = f"₹{bal:,.2f}"
                color   = ""
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:3px 0'>"
                f"<span style='padding-left:12px'>{row['code']} &nbsp; {row['name']}</span>"
                f"<span style='font-family:monospace;{color}'>{bal_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        if total < 0:
            total_str = f"(₹{abs(total):,.2f})"
        else:
            total_str = f"₹{total:,.2f}"
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-weight:700;"
            f"border-top:1px solid #ccc;padding-top:4px;margin-top:4px'>"
            f"<span>{total_label}</span>"
            f"<span style='font-family:monospace'>{total_str}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    col1, col2 = st.columns(2)

    with col2:
        st.markdown("### 💰 Assets")
        render_section("", assets_df, total_assets, "Total Assets")

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
        st.success(f"✅ Balance Sheet balances — ₹{total_assets:,.2f}")
    else:
        st.warning(
            f"⚠️ Difference: ₹{diff:,.2f} — "
            f"Assets ₹{total_assets:,.2f} vs Funds+Liabilities ₹{total_liab_funds:,.2f}"
        )

    # Download
    out = pd.concat([
        assets_df[["code","name","balance"]].assign(side="Asset"),
        funds_df[["code","name","balance"]].assign(side="Fund"),
        liab_df[["code","name","balance"]].assign(side="Liability"),
    ])
    csv = out.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download Balance Sheet (CSV)", csv,
                       "balance_sheet_FY2526.csv", "text/csv")
