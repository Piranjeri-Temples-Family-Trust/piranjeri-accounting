"""
ie_statement.py — Income & Expenditure Account for FY 2025-26
Piranjeri Temples Family Trust

Format: T-account — Expenditure on LEFT | Income on RIGHT
        Matching audited FY 2024-25 presentation.

Key rules (from audited FY 2024-25):
  • Renovation income (I-06, acct 10) and Renovation expenditure (E-07, acct 19)
    are EXCLUDED — they appear in the Renovation Fund on the Balance Sheet.
  • Aadi Pooram expenditure (E-04, acct 16) IS shown separately on the left side.
  • Aadi Pooram donations are included under Nithya Pooja (I-01) — collected
    under the NPK fund; no separate income account exists.
  • "Excess of Income over Expenditure" / "Excess of Expenditure over Income"
    appears as a balancing figure on the SHORT side (left if surplus, right if deficit).
  • Both columns total to the same Grand Total.
"""

import streamlit as st
import pandas as pd
from ptft_utils import date_fy_selector


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _f(amt):
    """₹1,23,456.78 for positives; (₹1,23,456.78) for negatives; ₹ — for zero."""
    if amt is None:
        return ""
    if abs(amt) < 0.005:
        return "₹ —"
    if amt < 0:
        return f"(₹{abs(amt):,.2f})"
    return f"₹{amt:,.2f}"


def _tr(label, inner=None, outer=None, bold=False, indent=False, top_line=False):
    bw  = "font-weight:600;" if bold else ""
    lp  = "padding-left:20px;" if indent else ""
    bdr = "border-top:1px solid #bbb;" if top_line else ""

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


def _section_header(title):
    return (
        f"<tr><td colspan='3' style='padding:4px 8px;font-weight:600;"
        f"font-style:italic;color:#555;font-size:0.82rem'>{title}</td></tr>"
    )


def _grand_total(label, total):
    return (
        f"<tr style='font-weight:700;border-top:2px solid #444;"
        f"border-bottom:2px solid #444;'>"
        f"<td style='padding:5px 8px;'>{label}</td><td></td>"
        f"<td style='text-align:right;font-family:monospace;"
        f"padding:5px 8px;white-space:nowrap;'>{_f(total)}</td>"
        f"</tr>"
    )


def _wrap(rows_html):
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:0.87rem;'>"
        + rows_html + "</table>"
    )


# ── Main render ────────────────────────────────────────────────────────────────

def render(conn):
    st.header("Income & Expenditure Account")
    date_from, date_to, fy = date_fy_selector("ie")
    st.subheader(
        f"Piranjeri Temples Family Trust — "
        f"Income and Expenditure Account for the year ended "
        f"{date_to.strftime('%d %B %Y')}"
    )
    st.divider()

    # ── SQL ── income accounts 5-9 (I-01..I-05) + 37,38,39 (I-07,I-08,I-09)
    #          expenditure accounts 13-18 (E-01..E-06) + 20,21 (E-08,E-09)
    # Excluded: acct 10 (I-06 Renovation income), acct 19 (E-07 Renovation exp)
    # I-07 (acct 37): Aadi Pooram donations — reclassified from I-01 via CORR-AADI-FY2526
    # I-08 (acct 38): Interest on Savings Bank — reclassified from I-01 via CORR-BINT-FY2526
    # I-09 (acct 39): Interest on Fixed Deposits — reclassified from I-01 via CORR-BINT-FY2526
    sql = """
        SELECT
            COALESCE(SUM(CASE WHEN account_id =  5
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i01,
            COALESCE(SUM(CASE WHEN account_id =  6
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i02,
            COALESCE(SUM(CASE WHEN account_id =  7
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i03,
            COALESCE(SUM(CASE WHEN account_id =  8
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i04,
            COALESCE(SUM(CASE WHEN account_id =  9
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i05,
            COALESCE(SUM(CASE WHEN account_id = 37
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i07,
            COALESCE(SUM(CASE WHEN account_id = 38
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i08,
            COALESCE(SUM(CASE WHEN account_id = 39
                THEN credit_amount - debit_amount ELSE 0 END), 0) AS i09,
            COALESCE(SUM(CASE WHEN account_id = 13
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e01,
            COALESCE(SUM(CASE WHEN account_id = 14
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e02,
            COALESCE(SUM(CASE WHEN account_id = 15
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e03,
            COALESCE(SUM(CASE WHEN account_id = 16
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e04,
            COALESCE(SUM(CASE WHEN account_id = 17
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e05,
            COALESCE(SUM(CASE WHEN account_id = 18
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e06,
            COALESCE(SUM(CASE WHEN account_id = 20
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e08,
            COALESCE(SUM(CASE WHEN account_id = 21
                THEN debit_amount - credit_amount ELSE 0 END), 0) AS e09
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

    (i01, i02, i03, i04, i05, i07, i08, i09,
     e01, e02, e03, e04, e05, e06, e08, e09) = [float(x) for x in rows[0]]

    # ── Derived totals ─────────────────────────────────────────────────────────
    total_donations = i01 + i07 + i02 + i03 + i04 + i05
    total_interest  = i08 + i09
    total_income    = total_donations + total_interest
    festival_exp    = e01 + e02 + e03 + e04 + e05 + e06
    other_exp       = e08 + e09
    total_exp       = festival_exp + other_exp
    ie_result       = total_income - total_exp        # +ve = surplus, -ve = deficit
    grand_total     = max(total_income, total_exp)

    surplus_label  = ("Excess of Income over Expenditure"
                      if ie_result >= 0
                      else "Excess of Expenditure over Income")
    balancing_amt  = abs(ie_result)

    # ── EXPENDITURE table (LEFT) ───────────────────────────────────────────────
    el = ""
    el += _section_header("Expenditure towards")

    if e01 > 0.005:
        el += _tr("Nithya Pooja",       inner=e01, indent=True)
    if e04 > 0.005:
        el += _tr("Aadi Pooram",        inner=e04, indent=True)
    if e02 > 0.005:
        el += _tr("Pradosham",          inner=e02, indent=True)
    if e05 > 0.005:
        el += _tr("Garuda Seva",        inner=e05, indent=True)
    if e06 > 0.005:
        el += _tr("Varushabhishekam",   inner=e06, indent=True)
    if e03 > 0.005:
        el += _tr("Panguni Uthram",     inner=e03, indent=True)

    el += _tr("Sub-total", outer=festival_exp, top_line=True, bold=True)
    el += _spacer()

    el += _section_header("Other Expenses")
    if e08 > 0.005:
        el += _tr("Bank Charges",  inner=e08, indent=True)
    if e09 > 0.005:
        el += _tr("Audit Fees",    inner=e09, indent=True)
    el += _tr("Sub-total", outer=other_exp, top_line=True, bold=True)
    el += _spacer()

    # Balancing figure on expenditure side when income exceeds expenditure
    if ie_result >= 0:
        el += _tr(surplus_label, outer=balancing_amt, bold=True)
        el += _spacer()

    el += _grand_total("Total", grand_total)

    # ── INCOME table (RIGHT) ───────────────────────────────────────────────────
    ir = ""
    ir += _section_header("Donations received for")

    if i01 > 0.005:
        ir += _tr("Nithya Pooja",      inner=i01, indent=True)
    if i07 > 0.005:
        ir += _tr("Aadi Pooram",       inner=i07, indent=True)
    if i02 > 0.005:
        ir += _tr("Pradosham",         inner=i02, indent=True)
    if i03 > 0.005:
        ir += _tr("Garuda Seva",       inner=i03, indent=True)
    if i04 > 0.005:
        ir += _tr("Varushabhishekam",  inner=i04, indent=True)
    if i05 > 0.005:
        ir += _tr("Panguni Uthram",    inner=i05, indent=True)

    ir += _tr("Sub-total", outer=total_donations, top_line=True, bold=True)
    ir += _spacer()

    # Interest income section (matches audited FY 2024-25 format)
    if i08 > 0.005 or i09 > 0.005:
        if i08 > 0.005:
            ir += _tr("Interest on Savings Bank",    outer=i08)
        if i09 > 0.005:
            ir += _tr("Interest on Fixed Deposits",  outer=i09)
        ir += _spacer()

    # Balancing figure on income side when expenditure exceeds income
    if ie_result < 0:
        ir += _tr(surplus_label, outer=balancing_amt, bold=True)
        ir += _spacer()

    ir += _grand_total("Total", grand_total)

    # ── Render T-account ───────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Expenditure")
        st.markdown(_wrap(el), unsafe_allow_html=True)
    with col2:
        st.markdown("#### Income")
        st.markdown(_wrap(ir), unsafe_allow_html=True)

    st.divider()

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Income",      f"₹{total_income:,.2f}")
    m2.metric("Total Expenditure", f"₹{total_exp:,.2f}")
    m3.metric(surplus_label[:35],  f"₹{balancing_amt:,.2f}")

    st.info(
        "ℹ️  **Notes:** "
        "Renovation Fund income & expenditure are excluded — "
        "they are shown in the Renovation Fund balance on the Balance Sheet.  "
        "Bank interest (SB + FD) is shown separately as Interest Income."
    )

    # ── Download CSV ───────────────────────────────────────────────────────────
    csv_rows = [
        ("Nithya Pooja Donations",         i01,             "Income"),
        ("Aadi Pooram Donations",          i07,             "Income"),
        ("Pradosham Donations",            i02,             "Income"),
        ("Garuda Seva Donations",          i03,             "Income"),
        ("Varushabhishekam Donations",     i04,             "Income"),
        ("Panguni Uthram Donations",       i05,             "Income"),
        ("Festival Donations Sub-total",   total_donations, "Income"),
        ("Interest on Savings Bank",       i08,             "Income"),
        ("Interest on Fixed Deposits",     i09,             "Income"),
        ("Total Income",                   total_income,    "Income"),
        ("Nithya Pooja Expenditure",       e01,          "Expenditure"),
        ("Aadi Pooram Expenditure",        e04,          "Expenditure"),
        ("Pradosham Expenditure",          e02,          "Expenditure"),
        ("Garuda Seva Expenditure",        e05,          "Expenditure"),
        ("Varushabhishekam Expenditure",   e06,          "Expenditure"),
        ("Panguni Uthram Expenditure",     e03,          "Expenditure"),
        ("Festival Expenditure Sub-total", festival_exp, "Expenditure"),
        ("Bank Charges",                   e08,          "Other Expenses"),
        ("Audit Fees",                     e09,          "Other Expenses"),
        ("Other Expenses Sub-total",       other_exp,    "Other Expenses"),
        ("Total Expenditure",              total_exp,    "Expenditure"),
        (surplus_label,                    ie_result,    "Result"),
    ]
    csv = (pd.DataFrame(csv_rows, columns=["Description", "Amount (₹)", "Category"])
             .to_csv(index=False).encode("utf-8"))
    st.download_button(
        "⬇ Download I&E Statement (CSV)", csv,
        f"ie_statement_{fy.replace('-', '')}.csv", "text/csv"
    )
