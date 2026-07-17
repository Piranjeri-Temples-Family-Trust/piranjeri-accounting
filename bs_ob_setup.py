"""
bs_ob_setup.py — Year-End Opening Balance Setup
Admin-only page. Calculates closing balances from ledger and saves
as opening balances for the new FY into bs_ob_config table.
"""
import streamlit as st


def render_ob_setup():
    st.title("⚙️ Year-End Opening Balance Setup")
    st.caption("Use this page after 31 March each year to set up opening balances for the new financial year.")

    if st.session_state.get("user") != "admin3":
        st.error("Administrator access required (admin3 only).")
        return

    conn = st.session_state.get("conn")
    if not conn:
        st.error("Database not connected. Please refresh the page.")
        return

    # ── Current OB configuration ──────────────────────────────────────────────
    st.subheader("Current Opening Balance Configuration")
    try:
        rows = conn.run(
            "SELECT fy, l01, l02, l03, l04, l05, set_by, TO_CHAR(set_at,'DD-Mon-YYYY HH24:MI') "
            "FROM bs_ob_config ORDER BY fy DESC"
        )
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows, columns=[
                "FY", "Corpus Fund", "Renovation Fund", "Non-Corpus Fund",
                "Trustee Loan", "Audit Payable", "Set By", "Set At"
            ])
            for col in ["Corpus Fund", "Renovation Fund", "Non-Corpus Fund", "Trustee Loan", "Audit Payable"]:
                df[col] = df[col].apply(lambda x: f"₹{float(x):,.2f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.warning("No opening balance configuration found. Run the SQL setup script first.")
            return
    except Exception as e:
        st.error(f"Error reading bs_ob_config: {e}")
        return

    st.divider()

    # ── Generate new OB ───────────────────────────────────────────────────────
    st.subheader("Generate Opening Balances for New Financial Year")

    col1, col2 = st.columns(2)
    with col1:
        existing_fys = [r[0] for r in rows]
        source_fy = st.selectbox("Financial year that just ended", existing_fys)
    with col2:
        parts = source_fy.split("-")
        target_fy = f"{int(parts[0])+1}-{str(int(parts[1])+1).zfill(2)}"
        st.text_input("New FY to set up (auto-calculated)", value=target_fy, disabled=True)

    corpus_fund = st.number_input(
        "Corpus Fund (L-01) — only change if new corpus contributions were made this year",
        value=166005.00, min_value=0.0, format="%.2f"
    )

    st.info(
        "Clicking Calculate will read ALL ledger entries for the selected FY, "
        "compute closing balances, and show them for your review before saving."
    )

    if st.button("🔄 Calculate Closing Balances", type="primary"):
        try:
            # Single query: all asset closings + renovation movements + L-04/L-05 net
            result = conn.run("""
                SELECT
                    SUM(CASE WHEN account_id = 1  THEN debit - credit ELSE 0 END) AS a01,
                    SUM(CASE WHEN account_id = 2  THEN debit - credit ELSE 0 END) AS a02,
                    SUM(CASE WHEN account_id = 3  THEN debit - credit ELSE 0 END) AS a03,
                    SUM(CASE WHEN account_id = 4  THEN debit - credit ELSE 0 END) AS a04,
                    SUM(CASE WHEN account_id = 36 THEN debit - credit ELSE 0 END) AS a05,
                    SUM(CASE WHEN account_id = 10 THEN credit - debit ELSE 0 END) AS renov_inc,
                    SUM(CASE WHEN account_id = 19 THEN debit - credit ELSE 0 END) AS renov_exp,
                    SUM(CASE WHEN account_id = 34 THEN credit - debit ELSE 0 END) AS l04_net,
                    SUM(CASE WHEN account_id = 35 THEN credit - debit ELSE 0 END) AS l05_net
                FROM ledger_entries
                WHERE fy = :fy
            """, fy=source_fy)

            if not result or result[0][0] is None:
                st.error(f"No ledger entries found for FY {source_fy}. Cannot calculate.")
                return

            r = result[0]
            a01 = float(r[0] or 0)
            a02 = float(r[1] or 0)
            a03 = float(r[2] or 0)
            a04 = float(r[3] or 0)
            a05 = float(r[4] or 0)
            renov_inc = float(r[5] or 0)
            renov_exp = float(r[6] or 0)
            l04_net = float(r[7] or 0)
            l05_net = float(r[8] or 0)

            # Get source FY L-02 opening from bs_ob_config (already fetched above)
            src_ob = next((row for row in rows if row[0] == source_fy), None)
            l02_ob = float(src_ob[2]) if src_ob else 0.0

            # Calculate closing balances
            total_assets = a01 + a02 + a03 + a04 + a05
            l02_closing = round(l02_ob + renov_inc - renov_exp, 2)
            l03_closing = round(total_assets - corpus_fund - l02_closing - l04_net - l05_net, 2)
            # L-03 is negative when deficit (debit balance), positive when surplus

            # Store pending values in session state
            st.session_state["ob_pending"] = {
                "source_fy": source_fy,
                "target_fy": target_fy,
                "l01": round(corpus_fund, 2),
                "l02": l02_closing,
                "l03": l03_closing,
                "l04": round(l04_net, 2),
                "l05": round(l05_net, 2),
                "total_assets": round(total_assets, 2),
            }

        except Exception as e:
            st.error(f"Calculation error: {e}")
            return

    # ── Show results and confirm ──────────────────────────────────────────────
    if "ob_pending" in st.session_state:
        ob = st.session_state["ob_pending"]

        st.success(f"Closing balances for FY {ob['source_fy']} calculated successfully!")
        st.markdown(f"""
| Account | Amount | Side |
|---|---|---|
| **Total Assets** | **₹{ob['total_assets']:,.2f}** | Dr |
| L-01 Corpus Fund | ₹{ob['l01']:,.2f} | Cr |
| L-02 Renovation Fund | ₹{ob['l02']:,.2f} | Cr |
| L-03 Non-Corpus Fund | ₹{abs(ob['l03']):,.2f} | {'Dr (deficit)' if ob['l03'] < 0 else 'Cr (surplus)'} |
| L-04 Trustee Loan | ₹{ob['l04']:,.2f} | Cr |
| L-05 Audit Fees Payable | ₹{ob['l05']:,.2f} | Cr |
        """)

        # Verify balance
        check = ob["l01"] + ob["l02"] + ob["l03"] + ob["l04"] + ob["l05"]
        if abs(check - ob["total_assets"]) < 1.0:
            st.success(f"✓ Balance check passed — Assets = Funds + Liabilities = ₹{ob['total_assets']:,.2f}")
        else:
            st.error(f"⚠ Balance check FAILED. Assets ₹{ob['total_assets']:,.2f} ≠ Funds+Liabilities ₹{check:,.2f}. Do not save — contact developer.")
            return

        st.warning(
            f"These values will be saved as **opening balances for FY {ob['target_fy']}**. "
            "The Balance Sheet will use these figures automatically."
        )

        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button(f"✅ Confirm & Save for FY {ob['target_fy']}", type="primary"):
                try:
                    conn.run("""
                        INSERT INTO bs_ob_config (fy, l01, l02, l03, l04, l05, set_by, set_at)
                        VALUES (:fy, :l01, :l02, :l03, :l04, :l05, :user, NOW())
                        ON CONFLICT (fy) DO UPDATE
                            SET l01=:l01, l02=:l02, l03=:l03, l04=:l04, l05=:l05,
                                set_by=:user, set_at=NOW()
                    """,
                    fy=ob["target_fy"],
                    l01=ob["l01"], l02=ob["l02"], l03=ob["l03"],
                    l04=ob["l04"], l05=ob["l05"],
                    user=st.session_state.get("user", "admin3"))

                    del st.session_state["ob_pending"]
                    st.success(
                        f"Opening balances for FY {ob['target_fy']} saved. "
                        "The Balance Sheet page will now use these values automatically."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Save error: {e}")
        with col_b:
            if st.button("✖ Cancel"):
                del st.session_state["ob_pending"]
                st.rerun()
