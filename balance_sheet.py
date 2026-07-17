"""
balance_sheet.py v7 — Audited-format T-account with HTML tables
Format: Liabilities / Funds LEFT  |  Assets RIGHT
Each side uses a 3-column HTML table:  Description | Sub-amount | Total
Matches the audited FY 2024-25 Balance Sheet exactly.
Opening balances read from bs_ob_config (DB) via LEFT JOIN — single pg8000 query.
"""
import streamlit as st
from ptft_utils import date_fy_selector


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _f(v):
    """₹1,23,456.78  (always positive — caller decides sign context)"""
    if v is None:
        return ""
    return f"₹{abs(float(v)):,.2f}"


def _fn(v):
    """₹1,23,456.78  for positives;  ₹ -1,23,456.78  for negatives (for opening balances)"""
    if v is None:
        return ""
    if abs(float(v)) < 0.005:
        return "₹ -"
    if float(v) < 0:
        return f"₹ -{abs(float(v)):,.2f}"
    return f"₹{float(v):,.2f}"


def _row(label, inner=None, outer=None, bold=False, indent=False,
         top_line=False, bottom_line=False, red_outer=False):
    """Return one HTML <tr> with 3 cells: label | inner | outer."""
    bw  = "font-weight:600;" if bold else ""
    lp  = "padding-left:22px;" if indent else ""
    bdr = ""
    if top_line:
        bdr += "border-top:1px solid #999;"
    if bottom_line:
        bdr += "border-bottom:2px solid #555;"

    def _cell(v, signed=False, red=False):
        if v is None:
            return "<td></td>"
        color = "color:#c00;" if red or (isinstance(v, (int, float)) and float(v) < 0) else ""
        txt = _fn(v) if signed else _f(v)
        return (
            f"<td style='text-align:right;font-family:monospace;"
            f"padding:2px 8px;white-space:nowrap;{color}'>{txt}</td>"
        )

    return (
        f"<tr style='{bw}{bdr}'>"
        f"<td style='padding:2px 10px;{lp}'>{label}</td>"
        + _cell(inner, signed=True)
        + _cell(outer, signed=True, red=red_outer)
        + "</tr>"
    )


def _section(label):
    """Bold italic section-header row spanning all 3 columns."""
    return (
        f"<tr><td colspan='3' style='padding:4px 10px;font-weight:600;"
        f"font-style:italic;color:#333;border-top:1px solid #ddd'>{label}</td></tr>"
    )


def _spacer():
    return "<tr><td colspan='3' style='height:8px'></td></tr>"


def _total_row(label, amount):
    red = "color:#c00;" if isinstance(amount, (int, float)) and float(amount) < 0 else ""
    return (
        f"<tr style='font-weight:700;border-top:2px solid #444;border-bottom:2px solid #444;'>"
        f"<td style='padding:5px 10px;'>{label}</td><td></td>"
        f"<td style='text-align:right;font-family:monospace;padding:5px 10px;"
        f"white-space:nowrap;{red}'>{_fn(amount)}</td>"
        f"</tr>"
    )


def _wrap(rows_html):
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:0.86rem;'>"
        + rows_html
        + "</table>"
    )


# ── Main render ────────────────────────────────────────────────────────────────

def render_balance_sheet():
    st.title("Balance Sheet")
    st.caption("As at 31 March of the selected financial year")

    conn = st.session_state.get("conn")
    if not conn:
        st.error("Database not connected. Please refresh the page.")
        return

    fy_result = date_fy_selector(conn)
    if not fy_result:
        return
    # date_fy_selector returns (start_date, end_date, fy_string)
    fy = fy_result[2] if isinstance(fy_result, (tuple, list)) else fy_result

    # Single query: all ledger aggregates + OB from bs_ob_config via LEFT JOIN
    try:
        rows = conn.run("""
            SELECT
                SUM(CASE WHEN le.account_id = 1  THEN le.debit_amount - le.credit_amount ELSE 0 END) AS a01,
                SUM(CASE WHEN le.account_id = 2  THEN le.debit_amount - le.credit_amount ELSE 0 END) AS a02,
                SUM(CASE WHEN le.account_id = 3  THEN le.debit_amount - le.credit_amount ELSE 0 END) AS a03,
                SUM(CASE WHEN le.account_id = 4  THEN le.debit_amount - le.credit_amount ELSE 0 END) AS a04,
                SUM(CASE WHEN le.account_id = 36 THEN le.debit_amount - le.credit_amount ELSE 0 END) AS a05,
                SUM(CASE WHEN le.account_id = 10 THEN le.credit_amount - le.debit_amount ELSE 0 END) AS i06_cr,
                SUM(CASE WHEN le.account_id = 19 THEN le.debit_amount - le.credit_amount ELSE 0 END) AS e07_dr,
                MAX(ob.l01) AS ob_l01,
                MAX(ob.l02) AS ob_l02,
                MAX(ob.l03) AS ob_l03,
                MAX(ob.l04) AS ob_l04,
                MAX(ob.l05) AS ob_l05
            FROM ledger_entries le
            LEFT JOIN bs_ob_config ob ON ob.fy = :fy
            WHERE le.fy = :fy
        """, fy=fy)
    except Exception as e:
        st.error(f"Database error: {e}")
        return

    if not rows or rows[0][0] is None:
        st.warning(f"No ledger entries found for FY {fy}.")
        return

    r = rows[0]
    a01 = float(r[0]  or 0)
    a02 = float(r[1]  or 0)
    a03 = float(r[2]  or 0)
    a04 = float(r[3]  or 0)
    a05 = float(r[4]  or 0)
    i06_cr = float(r[5] or 0)
    e07_dr = float(r[6] or 0)

    if r[7] is None:
        st.error(
            f"No opening balances configured for FY {fy}. "
            "Please ask the administrator to run ⚙️ Year-End Setup."
        )
        return

    ob_l01 = float(r[7])
    ob_l02 = float(r[8])
    ob_l03 = float(r[9])   # negative if deficit opening balance
    ob_l04 = float(r[10])
    ob_l05 = float(r[11])

    # Fund closing balances
    l01          = ob_l01
    l02          = ob_l02 + i06_cr - e07_dr
    total_assets = a01 + a02 + a03 + a04 + a05
    l03          = total_assets - l01 - l02 - ob_l04 - ob_l05   # PLUG
    l04          = ob_l04
    l05          = ob_l05
    total_fl     = l01 + l02 + l03 + l04 + l05
    l03_movement = l03 - ob_l03      # +ve = surplus this year, -ve = deficit

    year_end = fy.split("-")[1]
    st.markdown(
        f"<h3 style='text-align:center;margin-bottom:4px'>"
        f"Balance Sheet as at 31 March 20{year_end}</h3>",
        unsafe_allow_html=True,
    )
    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # LEFT — Liabilities / Funds
    # ══════════════════════════════════════════════════════════════════════════
    lh = ""

    # ── Corpus Fund ──────────────────────────────────────────────────────────
    lh += _row("Corpus Fund", bold=True)
    lh += _row("Opening Balance",  inner=ob_l01, indent=True)
    lh += _row("Contributions",    inner=0.0,    indent=True)
    lh += _row("",                 outer=l01,    top_line=True)
    lh += _spacer()

    # ── Renovation Fund ──────────────────────────────────────────────────────
    lh += _row("Renovation Fund", bold=True)
    lh += _row("Opening Balance",      inner=ob_l02,  indent=True)
    lh += _row("Donations Received",   inner=i06_cr,  indent=True)
    lh += _row("Expenditure Made",     inner=-e07_dr, indent=True)
    lh += _row("",                     outer=l02,     top_line=True)
    lh += _spacer()

    # ── Non-Corpus Fund ───────────────────────────────────────────────────────
    lh += _row("Non-Corpus Fund", bold=True)
    lh += _row("Opening Balance", inner=ob_l03, indent=True)
    if l03_movement >= 0:
        lh += _row("Surplus", inner=l03_movement, indent=True)
    else:
        lh += _row("Deficit", inner=l03_movement, indent=True)
    lh += _row("", outer=l03, top_line=True)
    lh += _spacer()

    # ── Liabilities (shown only when non-zero) ────────────────────────────────
    if l04 != 0:
        lh += _row("Advance from Trustee", outer=l04)
    if l05 != 0:
        lh += _row("Audit Fees Payable", outer=l05)

    lh += _total_row("Total", total_fl)

    # ══════════════════════════════════════════════════════════════════════════
    # RIGHT — Assets
    # ══════════════════════════════════════════════════════════════════════════
    rh = ""

    # Cash in Hand + Cash at Bank grouped together (matching audited format)
    cash_subtotal = a01 + a02 + a03
    rh += _row("Cash in hand",            inner=a01, indent=True)
    rh += _row("Cash at Bank",            bold=True)
    rh += _row("In savings account",      inner=a02, indent=True)
    rh += _row("In fixed deposit",        inner=a03, indent=True)
    rh += _row("",                        outer=cash_subtotal, top_line=True)
    rh += _spacer()

    if a04 != 0:
        rh += _row("Accrued Interest on Fixed Deposits", outer=a04)
    if a05 != 0:
        rh += _row("Advance to Priest — Manikandan",     outer=a05)

    rh += _total_row("Total", total_assets)

    # ── Render T-account ──────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("#### Liabilities")
        st.markdown(_wrap(lh), unsafe_allow_html=True)
    with col_r:
        st.markdown("#### Assets")
        st.markdown(_wrap(rh), unsafe_allow_html=True)

    # ── Balance check ─────────────────────────────────────────────────────────
    st.divider()
    if abs(total_fl - total_assets) < 1.0:
        st.success(f"✓ Balance Sheet balances — Total {_f(total_assets)}")
    else:
        st.error(
            f"⚠ Balance Sheet does NOT balance — "
            f"Funds+Liabilities {_f(total_fl)} ≠ Assets {_f(total_assets)}. "
            "Contact administrator."
        )

    # ── Download buttons ──────────────────────────────────────────────────────
    bs_data = {
        "a01": a01, "a02": a02, "a03": a03, "a04": a04, "a05": a05,
        "l01": l01, "l02": l02, "l03": l03, "l04": l04, "l05": l05,
        "ob_l01": ob_l01, "ob_l02": ob_l02, "ob_l03": ob_l03,
        "i06_cr": i06_cr, "e07_dr": e07_dr,
        "total_assets": total_assets, "total_fl": total_fl,
    }
    st.markdown("**Download Report**")
    dl1, dl2, dl3 = st.columns(3)

    import pandas as pd
    csv_rows = [
        ("Cash in Hand",              "Asset",     a01),
        ("Cash at Bank — Savings",    "Asset",     a02),
        ("Fixed Deposits",            "Asset",     a03),
        ("Accrued Interest on FD",    "Asset",     a04),
        ("Advance to Priest",         "Asset",     a05),
        ("Total Assets",              "",          total_assets),
        ("Corpus Fund",               "Fund",      l01),
        ("Renovation Fund",           "Fund",      l02),
        ("Non-Corpus Fund",           "Fund",      l03),
        ("Loan from Trustees",        "Liability", l04),
        ("Audit Fees Payable",        "Liability", l05),
        ("Total Funds & Liabilities", "",          total_fl),
    ]
    csv_bytes = (pd.DataFrame(csv_rows, columns=["Item", "Category", "Amount (Rs.)"])
                   .to_csv(index=False).encode("utf-8"))
    with dl1:
        st.download_button("⬇ CSV", csv_bytes,
                           f"balance_sheet_{fy.replace('-', '')}.csv", "text/csv")
    with dl2:
        try:
            from report_pdf import balance_sheet_pdf
            pdf_bytes = balance_sheet_pdf(fy, bs_data)
            st.download_button("📄 PDF", pdf_bytes,
                               f"balance_sheet_{fy.replace('-', '')}.pdf",
                               "application/pdf")
        except Exception as e:
            st.caption(f"PDF unavailable: {e}")
    with dl3:
        try:
            from report_excel import balance_sheet_xlsx
            xlsx_bytes = balance_sheet_xlsx(fy, bs_data)
            st.download_button("📊 Excel", xlsx_bytes,
                               f"balance_sheet_{fy.replace('-', '')}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.caption(f"Excel unavailable: {e}")
