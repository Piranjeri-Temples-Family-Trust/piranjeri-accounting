"""
balance_sheet.py v6 — reads opening balances from bs_ob_config (DB)
instead of hard-coded _OB dict.
Format: T-account — Liabilities/Funds LEFT | Assets RIGHT
"""
import streamlit as st
from ptft_utils import date_fy_selector


def fmt(v):
    """Format as ₹ with commas, no sign."""
    return f"₹{abs(v):,.2f}"


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
    # date_fy_selector returns (start_date, end_date, fy_string) — extract FY string
    fy = fy_result[2] if isinstance(fy_result, (tuple, list)) else fy_result

    # Single query: ledger aggregates + OB from bs_ob_config (LEFT JOIN keeps it one call)
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
    a01 = float(r[0] or 0)
    a02 = float(r[1] or 0)
    a03 = float(r[2] or 0)
    a04 = float(r[3] or 0)
    a05 = float(r[4] or 0)
    i06_cr = float(r[5] or 0)
    e07_dr = float(r[6] or 0)

    # Opening balances from bs_ob_config
    if r[7] is None:
        st.error(
            f"No opening balances configured for FY {fy}. "
            "Please ask the administrator to run ⚙️ Year-End Setup."
        )
        return

    ob_l01 = float(r[7])
    ob_l02 = float(r[8])
    ob_l03 = float(r[9])    # negative = deficit (debit balance)
    ob_l04 = float(r[10])
    ob_l05 = float(r[11])

    # Fund closing balances
    l01 = ob_l01                            # Corpus Fund — unchanged unless new contributions
    l02 = ob_l02 + i06_cr - e07_dr         # Renovation Fund — OB + movements this year
    total_assets = a01 + a02 + a03 + a04 + a05
    l03 = total_assets - l01 - l02 - ob_l04 - ob_l05   # PLUG — Non-Corpus Fund
    l04 = ob_l04
    l05 = ob_l05
    total_fl = l01 + l02 + l03 + l04 + l05

    year_end = fy.split("-")[1]
    st.markdown(f"### Balance Sheet as at 31 March 20{year_end}")
    st.markdown("---")

    col_l, col_r = st.columns(2)

    # LEFT COLUMN — Funds & Liabilities
    with col_l:
        st.markdown("#### Funds & Liabilities")

        # Corpus Fund
        st.markdown(f"**Corpus Fund**")
        st.markdown(f"&nbsp;&nbsp;&nbsp;Opening balance: {fmt(ob_l01)}")
        st.markdown(f"&nbsp;&nbsp;&nbsp;Additions: Nil")
        cl, cv = st.columns([3, 1])
        cl.markdown("**Corpus Fund Total**"); cv.markdown(f"**{fmt(l01)}**")
        st.markdown("")

        # Renovation Fund
        st.markdown(f"**Renovation Fund**")
        st.markdown(f"&nbsp;&nbsp;&nbsp;Opening balance: {fmt(ob_l02)}")
        st.markdown(f"&nbsp;&nbsp;&nbsp;Add: Renovation income: {fmt(i06_cr)}")
        st.markdown(f"&nbsp;&nbsp;&nbsp;Less: Renovation expenditure: ({fmt(e07_dr)})")
        cl, cv = st.columns([3, 1])
        cl.markdown("**Renovation Fund Total**"); cv.markdown(f"**{fmt(l02)}**")
        st.markdown("")

        # Non-Corpus Fund
        l03_label = "Non-Corpus Fund (Deficit)" if l03 < 0 else "Non-Corpus Fund"
        l03_movement = l03 - ob_l03
        st.markdown(f"**{l03_label}**")
        st.markdown(f"&nbsp;&nbsp;&nbsp;Opening balance: {fmt(abs(ob_l03))} {'Dr' if ob_l03 < 0 else 'Cr'}")
        if l03_movement < 0:
            st.markdown(f"&nbsp;&nbsp;&nbsp;Add: Deficit for year: {fmt(abs(l03_movement))}")
        else:
            st.markdown(f"&nbsp;&nbsp;&nbsp;Add: Surplus for year: {fmt(l03_movement)}")
        cl, cv = st.columns([3, 1])
        cl.markdown(f"**{l03_label} Total**"); cv.markdown(f"**{fmt(l03)} {'(Dr)' if l03 < 0 else ''}**")
        st.markdown("")

        if l04 != 0:
            st.markdown(f"**Loan from Trustees**")
            cl, cv = st.columns([3, 1])
            cl.markdown("Loan from Trustees"); cv.markdown(fmt(l04))

        if l05 != 0:
            st.markdown(f"**Audit Fees Payable**")
            cl, cv = st.columns([3, 1])
            cl.markdown("Audit Fees Payable"); cv.markdown(fmt(l05))

        st.markdown("---")
        cl, cv = st.columns([3, 1])
        cl.markdown("**TOTAL**"); cv.markdown(f"**{fmt(total_fl)}**")

    # RIGHT COLUMN — Assets
    with col_r:
        st.markdown("#### Assets")
        assets = [
            ("Cash in Hand", a01),
            ("Cash at Bank — IOB Savings", a02),
            ("Fixed Deposits", a03),
            ("Accrued Interest on FD", a04),
        ]
        if a05 != 0:
            assets.append(("Advance to Priest — Manikandan", a05))

        for label, val in assets:
            cl, cv = st.columns([3, 1])
            cl.markdown(label); cv.markdown(fmt(val))

        st.markdown("---")
        cl, cv = st.columns([3, 1])
        cl.markdown("**TOTAL**"); cv.markdown(f"**{fmt(total_assets)}**")

    # Balance check
    st.markdown("---")
    if abs(total_fl - total_assets) < 1.0:
        st.success(f"✓ Balance Sheet balances — Total {fmt(total_assets)}")
    else:
        st.error(
            f"⚠ Balance Sheet does NOT balance — "
            f"Funds+Liabilities {fmt(total_fl)} ≠ Assets {fmt(total_assets)}. "
            "Contact administrator."
        )

    # ── Download buttons ──────────────────────────────────────────
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
        ("Cash in Hand",              "Asset",       a01),
        ("Cash at Bank — IOB Savings","Asset",       a02),
        ("Fixed Deposits",            "Asset",       a03),
        ("Accrued Interest on FD",    "Asset",       a04),
        ("Advance to Priest",         "Asset",       a05),
        ("Total Assets",              "",            total_assets),
        ("Corpus Fund",               "Fund",        l01),
        ("Renovation Fund",           "Fund",        l02),
        ("Non-Corpus Fund",           "Fund",        l03),
        ("Loan from Trustees",        "Liability",   l04),
        ("Audit Fees Payable",        "Liability",   l05),
        ("Total Funds & Liabilities", "",            total_fl),
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
