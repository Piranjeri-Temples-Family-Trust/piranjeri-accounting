# expense_entry.py — Piranjeri Temples Trust Accounting
# Expense entry module for Agent 1 data capture
# Embed in accounting app: from expense_entry import render_expense_entry

import streamlit as st
import psycopg2
import psycopg2.extras
from datetime import date, datetime
from contextlib import contextmanager


# ── DB connection ──────────────────────────────────────────────────────────────

@contextmanager
def _cursor():
    dsn = st.secrets["neon"]["dsn"]
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fy_for_date(d: date) -> str:
    """Return FY string e.g. '2025-26' for a given date (April–March year)."""
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[2:]}"
    else:
        return f"{d.year - 1}-{str(d.year)[2:]}"


@st.cache_data(ttl=300)
def _load_fund_sources() -> list:
    with _cursor() as cur:
        cur.execute("SELECT id, code, name FROM fund_sources WHERE is_active ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=300)
def _load_festivals() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT f.id, f.code, f.name, f.fund_source_id, fs.code AS fs_code
            FROM festivals f
            JOIN fund_sources fs ON fs.id = f.fund_source_id
            WHERE f.is_active
            ORDER BY f.name
        """)
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=300)
def _load_major_heads() -> list:
    with _cursor() as cur:
        cur.execute("SELECT id, code, name FROM major_heads WHERE is_active ORDER BY code")
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=300)
def _load_standing_amounts() -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT sa.id, sa.description, sa.major_head_id, sa.festival_id,
                   sa.default_amount, sa.notes,
                   mh.code AS mh_code, mh.name AS mh_name,
                   f.name AS festival_name
            FROM standing_amounts sa
            JOIN major_heads mh ON mh.id = sa.major_head_id
            LEFT JOIN festivals f ON f.id = sa.festival_id
            WHERE sa.is_active
            ORDER BY mh.code, sa.description
        """)
        return [dict(r) for r in cur.fetchall()]


def _load_recent_entries(limit: int = 15) -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT et.id, et.txn_date, et.amount, et.payment_mode,
                   et.description, et.paid_to,
                   mh.code AS mh_code, mh.name AS mh_name,
                   fs.code AS fund_code,
                   fv.name AS festival_name,
                   et.entered_by
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id = et.major_head_id
            JOIN fund_sources fs ON fs.id = et.fund_source_id
            LEFT JOIN festivals fv ON fv.id = et.festival_id
            ORDER BY et.created_at DESC
            LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]


def _save_expense(rec: dict) -> int:
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO expense_transactions
                (txn_date, fy, fund_source_id, festival_id, major_head_id,
                 amount, payment_mode, cheque_no, utr_ref_no,
                 description, paid_to, entered_by)
            VALUES
                (%(txn_date)s, %(fy)s, %(fund_source_id)s, %(festival_id)s, %(major_head_id)s,
                 %(amount)s, %(payment_mode)s, %(cheque_no)s, %(utr_ref_no)s,
                 %(description)s, %(paid_to)s, %(entered_by)s)
            RETURNING id
        """, rec)
        return cur.fetchone()["id"]


# ── Main render function ───────────────────────────────────────────────────────

def render_expense_entry(user: str):
    """Render the expense entry section. Call from main app with logged-in username."""

    st.header("📋 Expense Entry")

    fund_sources  = _load_fund_sources()
    all_festivals = _load_festivals()
    major_heads   = _load_major_heads()
    standing_amts = _load_standing_amounts()

    # ── Tabs: New Entry | Standing Amounts | Recent Entries ──────────────────
    tab_new, tab_standing, tab_recent = st.tabs(
        ["New Expense", "Standing Amounts", "Recent Entries"]
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — New Expense Entry
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_new:
        with st.form("expense_form", clear_on_submit=True):

            col1, col2 = st.columns(2)

            with col1:
                txn_date = st.date_input(
                    "Transaction Date",
                    value=date.today(),
                    max_value=date.today(),
                )
                fy = _fy_for_date(txn_date)
                st.caption(f"Financial Year: **{fy}**")

            with col2:
                payment_mode = st.selectbox(
                    "Payment Mode",
                    options=["CASH", "CHEQUE", "BANK_TRANSFER"],
                    format_func=lambda x: {"CASH": "Cash", "CHEQUE": "Cheque",
                                           "BANK_TRANSFER": "Bank Transfer"}[x],
                )

            # ── Fund Source & Festival ──────────────────────────────────────
            st.divider()
            col3, col4 = st.columns(2)

            with col3:
                fs_options = {fs["id"]: f"{fs['code']} — {fs['name']}" for fs in fund_sources}
                fund_source_id = st.selectbox(
                    "Fund Source",
                    options=list(fs_options.keys()),
                    format_func=lambda x: fs_options[x],
                )

            with col4:
                # Filter festivals to selected fund source
                filtered_fests = [f for f in all_festivals if f["fund_source_id"] == fund_source_id]
                fest_options = {None: "— Not festival-specific —"}
                fest_options.update({f["id"]: f["name"] for f in filtered_fests})

                festival_id = st.selectbox(
                    "Festival / Sub-Festival",
                    options=list(fest_options.keys()),
                    format_func=lambda x: fest_options[x],
                )

            # ── Major Head ─────────────────────────────────────────────────
            mh_options = {mh["id"]: f"{mh['code']} — {mh['name']}" for mh in major_heads}
            major_head_id = st.selectbox(
                "Major Head (Expense Category)",
                options=list(mh_options.keys()),
                format_func=lambda x: mh_options[x],
            )

            # ── Amount ─────────────────────────────────────────────────────
            st.divider()
            col5, col6 = st.columns(2)

            with col5:
                amount = st.number_input(
                    "Amount (₹)",
                    min_value=1.0,
                    max_value=500000.0,
                    step=0.50,
                    format="%.2f",
                )

            with col6:
                # Suggest standing amount if major head matches
                matches = [
                    s for s in standing_amts
                    if s["major_head_id"] == major_head_id
                    and (festival_id is None or s["festival_id"] == festival_id)
                ]
                if matches:
                    st.info(
                        "**Standing amount** for this head:\n"
                        + "\n".join(
                            f"• {s['description']}: ₹{s['default_amount']:,.2f}"
                            for s in matches
                        )
                    )

            # ── Payment-mode conditional fields ────────────────────────────
            cheque_no  = None
            utr_ref_no = None

            if payment_mode == "CHEQUE":
                cheque_no = st.text_input("Cheque Number", max_chars=30)
                if cheque_no:
                    cheque_no = cheque_no.strip() or None

            elif payment_mode == "BANK_TRANSFER":
                utr_ref_no = st.text_input("UTR / Reference Number", max_chars=40)
                if utr_ref_no:
                    utr_ref_no = utr_ref_no.strip() or None

            # ── Description & Paid To ──────────────────────────────────────
            st.divider()
            col7, col8 = st.columns(2)

            with col7:
                description = st.text_input(
                    "Description (optional, max 50 chars)",
                    max_chars=50,
                    placeholder="e.g. April flowers NPK",
                )
                description = description.strip() or None

            with col8:
                paid_to = st.text_input(
                    "Paid To (optional, max 50 chars)",
                    max_chars=50,
                    placeholder="e.g. Subramania Pillai & Son",
                )
                paid_to = paid_to.strip() or None

            # ── Submit ─────────────────────────────────────────────────────
            submitted = st.form_submit_button("💾 Save Expense", type="primary")

        if submitted:
            # Validation
            errors = []
            if payment_mode == "CHEQUE" and not cheque_no:
                errors.append("Cheque number is required for cheque payments.")
            if payment_mode == "BANK_TRANSFER" and not utr_ref_no:
                errors.append("UTR / Reference number is required for bank transfers.")

            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    rec = {
                        "txn_date":      txn_date,
                        "fy":            fy,
                        "fund_source_id": fund_source_id,
                        "festival_id":   festival_id,
                        "major_head_id": major_head_id,
                        "amount":        float(amount),
                        "payment_mode":  payment_mode,
                        "cheque_no":     cheque_no,
                        "utr_ref_no":    utr_ref_no,
                        "description":   description,
                        "paid_to":       paid_to,
                        "entered_by":    user,
                    }
                    new_id = _save_expense(rec)
                    st.success(
                        f"✅ Expense saved (ID #{new_id}) — "
                        f"₹{amount:,.2f} under {mh_options[major_head_id]}"
                    )
                    # Clear caches so Recent Entries refreshes
                    st.cache_data.clear()
                except Exception as exc:
                    st.error(f"Failed to save: {exc}")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Standing Amounts Reference
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_standing:
        st.subheader("Standing / Recurring Amounts")
        st.caption("Pre-configured default amounts for regular expenses. Use as reference when entering the month's bills.")

        if not standing_amts:
            st.info("No standing amounts configured.")
        else:
            # Group by festival
            by_festival: dict = {}
            for s in standing_amts:
                key = s.get("festival_name") or "General"
                by_festival.setdefault(key, []).append(s)

            for fest_name, items in sorted(by_festival.items()):
                with st.expander(fest_name, expanded=True):
                    rows = []
                    for item in items:
                        rows.append({
                            "Head": f"{item['mh_code']} — {item['mh_name']}",
                            "Description": item["description"],
                            "Default Amount (₹)": f"{item['default_amount']:,.2f}",
                            "Notes": item["notes"] or "",
                        })
                    st.table(rows)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Recent Entries
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_recent:
        st.subheader("Recent Expense Entries")

        try:
            entries = _load_recent_entries(limit=20)
        except Exception as exc:
            st.error(f"Could not load entries: {exc}")
            entries = []

        if not entries:
            st.info("No expense entries yet.")
        else:
            for e in entries:
                with st.container():
                    c1, c2, c3 = st.columns([2, 3, 2])
                    with c1:
                        st.markdown(
                            f"**{e['txn_date'].strftime('%d %b %Y')}**  \n"
                            f"`{e['fund_code']}` › {e['festival_name'] or '—'}"
                        )
                    with c2:
                        st.markdown(
                            f"{e['mh_code']} — {e['mh_name']}  \n"
                            + (f"*{e['description']}*" if e["description"] else "")
                            + (f"  ›  {e['paid_to']}" if e["paid_to"] else "")
                        )
                    with c3:
                        st.markdown(
                            f"**₹{float(e['amount']):,.2f}**  \n"
                            f"{e['payment_mode']}  ·  {e['entered_by']}"
                        )
                st.divider()
