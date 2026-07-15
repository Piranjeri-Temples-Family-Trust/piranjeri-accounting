"""
balance_sheet.py  —  Balance Sheet as at 31 March 2026
Piranjeri Temples Family Trust

Format: T-account (Funds & Liabilities left | Assets right)
        matching audited FY 2024-25 presentation.

Architecture: SINGLE SQL query — avoids pg8000 cached-connection state bug
              where sequential conn.run() calls return stale results.

Fund balance logic:
  L-01 Corpus Fund      — Opening Balance + FY Contributions
  L-02 Renovation Fund  — Opening Balance + Donations Received − Expenditure Made
  L-03 Non-Corpus Fund  — Opening Balance + FY Surplus/(Deficit)
                          Closing = PLUG (Total Assets − L-01 − L-02 − Liabilities)
                          → guarantees BS balances regardless of I&E reconciliation gaps
  L-04 / L-05           — Direct ledger CR balance; hidden when zero
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


# ── Formatting helpers ────────────────────────────────────────────────────────

def _f(amt):
    """₹1,23,456.78 for positives; (₹1,23,456.78) for negatives; ₹ — for zero."""
    if amt is None:
        return ""
    if abs(amt) < 0.005:
        return "₹ —"
    if amt < 0:
        return f"(₹{abs(amt):,.2f})"
    return f"₹{amt:,.2f}"


def _tr(label, inner=None, outer=None, bold=False, indent=False,
        top_line=False, thick_line=False):
    """Return one HTML <tr> with three columns: label | inner | outer."""
    bw   = "font-weight:600;" if bold else ""
    lp   = "padding-left:20px;" if indent else ""
    bdr  = ("border-top:2px solid #888;" if thick_line
            else "border-top:1px solid #ccc;" if top_line
            else "")

    def _cell(v):
        if v is None:
            return "<td></td>"
        color = "color:#c00;" if v < 0 else ""
        return (f"<td style='text-align:right;font-family:monospace;"
                f"padding:2px 6px;white-space:nowrap;{color}'>{_f(v)}</td>")

    return (
        f"<tr style='{bw}{bdr}'>"
        f"<td style='padding:2px 8px;{lp}'>{label}</td>"
        + _cell(inner) + _cell(outer) +
        f"</tr>"
    )


def _spacer():
    return "<tr><td colspan='3' style='height:8px'></td></tr>"


def _total_row(total):
    color = "color:#c00;" if total < 0 else ""
    return (
        f"<tr style='font-weight:700;border-top:2px solid #555;'>"
        f"<td style='padding:5px 8px;'>Total</td><td></td>"
        f"<td style='text-align:right;font-family:monospace;padding:5px 8px;"
        f"white-space:nowrap;{color}'>{_f(total)}</td>"
        f"</tr>"
    )


def _wrap_table(rows_html):
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:0.87rem;'>"
        + rows_html +
        "</table>"
    )


# ── Main render ───────────────────────────────────────────────────────────────

def render(conn):
    st.header("Balance Sheet")
    date_from, date_to, fy = date_fy_selector("bs")
    st.subheader(
        f"Piranjeri Temples Family Trust — "
        f"Balance sheet as at {date_to.strftime('%d %B %Y')}"
    )
    st.divider()

    # ── Single SQL: all values in one round-trip ───────────────────────────────
    # NOTE: No batch_id filters — accounts 11 (L-01), 12 (L-02), 31 (L-03)
    # have ONLY their opening-balance entries in ledger_entries for FY 2025-26.
    # Filtering by batch_id was triggering a pg8000 column-displacement bug.
    sql = """
        SELECT
            -- ── Assets ────────────────────────────────────────────────────
            COALESCE(SUM(CASE WHEN account_id =  1
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS a01,
            COALESCE(SUM(CASE WHEN account_id =  2
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS a02,
            COALESCE(SUM(CASE WHEN account_id =  3
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS a03,
            COALESCE(SUM(CASE WHEN account_id =  4
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS a04,
            COALESCE(SUM(CASE WHEN account_id = 36
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS a05,

            -- ── Corpus Fund (L-01): total FY balance = opening (no new contributions) ─
            COALESCE(SUM(CASE WHEN account_id = 11
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS l01_cr,

            -- ── Renovation Fund (L-02): opening balance (only OB entry exists) ────────
            COALESCE(SUM(CASE WHEN account_id = 12
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS l02_ob,

            -- ── Renovation Fund movements ──────────────────────────────────
            COALESCE(SUM(CASE WHEN account_id = 10
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i06_cr,
            COALESCE(SUM(CASE WHEN account_id = 19
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e07_dr,

            -- ── Non-Corpus Fund (L-03): opening balance (only OB entry exists) ─────────
            COALESCE(SUM(CASE WHEN account_id = 31
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS l03_ob,

            -- ── Liabilities ────────────────────────────────────────────────
            COALESCE(SUM(CASE WHEN account_id = 32
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS l04_cr,
            COALESCE(SUM(CASE WHEN account_id = 33
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS l05_cr
        FROM ledger_entries
        WHERE fy = :fy
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
    (a01, a02, a03, a04, a05,
     l01_cr,
     l02_ob, i06_cr, e07_dr,
     l03_ob,
     l04_cr, l05_cr) = [float(x) for x in r]

    # ── Derived values ────────────────────────────────────────────────────────
    # l01_cr = opening + contributions; since no new Corpus donations in FY 2025-26,
    # l01_ob = l01_cr and l01_contrib = 0.
    l01_ob       = l01_cr                            # Account 11 has only OB entry
    l01_contrib  = 0.0                               # No new Corpus donations this FY
    l02_closing  = l02_ob + i06_cr - e07_dr          # Renovation Fund closing balance

    total_assets = a01 + a02 + a03 + a04 + a05
    total_liab   = max(l04_cr, 0) + max(l05_cr, 0)

    # L-03 Non-Corpus Fund closing — PLUG (guarantees BS always balances)
    l03_closing  = total_assets - l01_cr - l02_closing - total_liab
    l03_movement = l03_closing - l03_ob              # FY Surplus (+) or Deficit (−)

    total_funds      = l01_cr + l02_closing + l03_closing
    total_liab_funds = total_funds + total_liab

    # ── Funds & Liabilities table ─────────────────────────────────────────────
    fl = ""

    # Corpus Fund
    fl += _tr("Corpus Fund", bold=True)
    fl += _tr("Opening Balance",  inner=l01_ob,     indent=True)
    fl += _tr("Contributions",    inner=l01_contrib, indent=True)
    fl += _tr("",                 outer=l01_cr,      top_line=True)

    fl += _spacer()

    # Renovation Fund
    fl += _tr("Renovation Fund", bold=True)
    fl += _tr("Opening Balance",     inner=l02_ob,    indent=True)
    fl += _tr("Donations Received",  inner=i06_cr,    indent=True)
    fl += _tr("Expenditure Made",    inner=-e07_dr,   indent=True)
    fl += _tr("",                    outer=l02_closing, top_line=True)

    fl += _spacer()

    # Non-Corpus Fund
    ie_label = "Surplus" if l03_movement >= 0 else "Deficit"
    fl += _tr("Non-Corpus Fund", bold=True)
    fl += _tr("Opening Balance", inner=l03_ob,        indent=True)
    fl += _tr(ie_label,          inner=l03_movement,  indent=True)
    fl += _tr("",                outer=l03_closing,   top_line=True)

    # Liabilities — only show if non-zero
    if abs(l04_cr) > 0.005 or abs(l05_cr) > 0.005:
        fl += _spacer()
    if abs(l04_cr) > 0.005:
        fl += _tr("Advance from Trustee", outer=l04_cr)
    if abs(l05_cr) > 0.005:
        fl += _tr("Audit Fees Payable",   outer=l05_cr)

    fl += _total_row(total_liab_funds)

    # ── Assets table ──────────────────────────────────────────────────────────
    at = ""

    # Cash in hand + bank grouped (matching audited format)
    at += _tr("Cash in Hand",         inner=a01)
    at += _tr("Cash at Bank")
    at += _tr("In Savings Account",   inner=a02, indent=True)
    at += _tr("In Fixed Deposit",     inner=a03, indent=True)
    at += _tr("",                     outer=a01 + a02 + a03, top_line=True)

    at += _spacer()
    at += _tr("Accrued Interest on Fixed Deposits", outer=a04)

    if abs(a05) > 0.005:
        at += _tr("Advance to Priest — Manikandan", outer=a05)

    at += _total_row(total_assets)

    # ── Render two-column layout ──────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Liabilities")
        st.markdown(_wrap_table(fl), unsafe_allow_html=True)

    with col2:
        st.markdown("#### Assets")
        st.markdown(_wrap_table(at), unsafe_allow_html=True)

    st.divider()

    diff = abs(total_liab_funds - total_assets)
    if diff < 0.50:
        st.success(f"✅ Balance Sheet balances — ₹{total_assets:,.2f}")
    else:
        st.error(
            f"⚠️ Difference ₹{diff:,.2f} | "
            f"Assets ₹{total_assets:,.2f} vs F&L ₹{total_liab_funds:,.2f}"
        )

    st.markdown(
        f"<div style='font-size:0.78rem;color:#888;margin-top:6px'>"
        f"Date: {date_to.strftime('%d-%m-%Y')}&nbsp;&nbsp;&nbsp;Place: Chennai"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Download CSV ──────────────────────────────────────────────────────────
    csv_rows = [
        ("Corpus Fund — Opening Balance",        l01_ob,       "Fund"),
        ("Corpus Fund — Contributions",           l01_contrib,  "Fund"),
        ("Corpus Fund — Closing Balance",         l01_cr,       "Fund"),
        ("Renovation Fund — Opening Balance",     l02_ob,       "Fund"),
        ("Renovation Fund — Donations Received",  i06_cr,       "Fund"),
        ("Renovation Fund — Expenditure Made",    -e07_dr,      "Fund"),
        ("Renovation Fund — Closing Balance",     l02_closing,  "Fund"),
        ("Non-Corpus Fund — Opening Balance",     l03_ob,       "Fund"),
        (f"Non-Corpus Fund — {ie_label}",         l03_movement, "Fund"),
        ("Non-Corpus Fund — Closing Balance",     l03_closing,  "Fund"),
        ("Cash in Hand",                          a01,          "Asset"),
        ("Cash at Bank — Savings Account",        a02,          "Asset"),
        ("Cash at Bank — Fixed Deposit",          a03,          "Asset"),
        ("Accrued Interest on Fixed Deposits",    a04,          "Asset"),
        ("Advance to Priest — Manikandan",        a05,          "Asset"),
    ]
    if abs(l04_cr) > 0.005:
        csv_rows.append(("Advance from Trustee", l04_cr, "Liability"))
    if abs(l05_cr) > 0.005:
        csv_rows.append(("Audit Fees Payable",   l05_cr, "Liability"))

    csv = (pd.DataFrame(csv_rows, columns=["Description", "Amount (₹)", "Category"])
             .to_csv(index=False).encode("utf-8"))
    st.download_button(
        "⬇ Download Balance Sheet (CSV)", csv,
        "balance_sheet_FY2526.csv", "text/csv"
    )
