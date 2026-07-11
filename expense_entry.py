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
            SELECT f.id, f.code, f.name, f.fund_source_id
            FROM festivals f WHERE f.is_active ORDER BY f.name
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
            SELECT sa.major_head_id, sa.festival_id, sa.description,
                   sa.default_amount, sa.notes,
                   mh.code AS mh_code, mh.name AS mh_name,
                   f.name AS festival_name
            FROM standing_amounts sa
            JOIN major_heads mh ON mh.id = sa.major_head_id
            LEFT JOIN festivals f ON f.id = sa.festival_id
            WHERE sa.is_active ORDER BY mh.code, sa.description
        """)
        return [dict(r) for r in cur.fetchall()]


def _load_recent_entries(limit: int = 20) -> list:
    with _cursor() as cur:
        cur.execute("""
            SELECT et.id, et.txn_date, et.amount, et.payment_mode,
                   et.description, et.paid_to,
                   mh.code AS mh_code, mh.name AS mh_name,
                   fs.code AS fund_code, fv.name AS festival_name,
                   et.entered_by
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id = et.major_head_id
            JOIN fund_sources fs ON fs.id = et.fund_source_id
            LEFT JOIN festivals fv ON fv.id = et.festival_id
            ORDER BY et.created_at DESC LIMIT %s
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


# ── CSS ────────────────────────────────────────────────────────────────────────

def _inject_css():
    st.markdown("""
    <style>
    /* Compact form card */
    .expense-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.2rem 1.4rem 0.8rem;
        margin-bottom: 0.8rem;
    }
    .section-label {
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #94a3b8;
        margin-bottom: 0.4rem;
    }
    /* Tighten Streamlit widget spacing */
    div[data-testid="stForm"] .stSelectbox,
    div[data-testid="stForm"] .stDateInput,
    div[data-testid="stForm"] .stNumberInput,
    div[data-testid="stForm"] .stTextInput {
        margin-bottom: 0 !important;
    }
    div[data-testid="stForm"] label {
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        color: #475569 !important;
        margin-bottom: 2px !important;
    }
    /* Standing hint badge */
    .hint-box {
        background: #f0fdf4;
        border-left: 3px solid #22c55e;
        border-radius: 4px;
        padding: 0.45rem 0.7rem;
        font-size: 0.78rem;
        color: #166534;
        margin-top: 1.6rem;
    }
    /* Recent entry row */
    .entry-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.55rem 0.9rem;
        border-radius: 7px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        margin-bottom: 0.45rem;
        font-size: 0.82rem;
    }
    .entry-date { color: #64748b; font-size: 0.75rem; }
    .entry-head { font-weight: 600; color: #1e293b; }
    .entry-amount { font-weight: 700; color: #0f172a; font-size: 0.95rem; }
    .entry-badge {
        display: inline-block;
        background: #e0f2fe;
        color: #0369a1;
        border-radius: 4px;
        padding: 1px 6px;
        font-size: 0.68rem;
        font-weight: 600;
        margin-left: 4px;
    }
    /* Page title */
    .page-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.9rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    /* Submit button */
    div[data-testid="stForm"] .stFormSubmitButton button {
        background: #1e40af !important;
        color: white !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 0.4rem 1.4rem !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
    }
    </style>
    """, unsafe_allow_html=True)


# ── Main render function ───────────────────────────────────────────────────────

def render_expense_entry(user: str):

    _inject_css()

    fund_sources  = _load_fund_sources()
    all_festivals = _load_festivals()
    major_heads   = _load_major_heads()
    standing_amts = _load_standing_amounts()

    tab_new, tab_standing, tab_recent = st.tabs(["✏️ New Expense", "📌 Standing Amounts", "🕐 Recent Entries"])

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 1 — New Expense
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_new:
        st.markdown('<div class="page-title">🧾 Record Expense</div>', unsafe_allow_html=True)

        with st.form("expense_form", clear_on_submit=True):

            # Row 1 — Date | Payment | Fund | Festival
            c1, c2, c3, c4 = st.columns([1.2, 1, 1.4, 1.4])
            with c1:
                txn_date = st.date_input("Date", value=date.today(), max_value=date.today())
                fy = _fy_for_date(txn_date)
                st.caption(f"FY {fy}")
            with c2:
                payment_mode = st.selectbox("Mode", ["CASH", "CHEQUE", "BANK_TRANSFER"],
                    format_func=lambda x: {"CASH": "Cash", "CHEQUE": "Cheque", "BANK_TRANSFER": "Bank Tfr"}[x])
            with c3:
                fs_options = {fs["id"]: f"{fs['code']} — {fs['name']}" for fs in fund_sources}
                fund_source_id = st.selectbox("Fund", options=list(fs_options.keys()),
                    format_func=lambda x: fs_options[x])
            with c4:
                filtered_fests = [f for f in all_festivals if f["fund_source_id"] == fund_source_id]
                fest_options = {None: "— General —"}
                fest_options.update({f["id"]: f["name"] for f in filtered_fests})
                festival_id = st.selectbox("Festival", options=list(fest_options.keys()),
                    format_func=lambda x: fest_options[x])

            # Row 2 — Major Head | Amount | Standing hint
            c5, c6, c7 = st.columns([2, 1, 1.8])
            with c5:
                mh_options = {mh["id"]: f"{mh['code']} — {mh['name']}" for mh in major_heads}
                major_head_id = st.selectbox("Head", options=list(mh_options.keys()),
                    format_func=lambda x: mh_options[x])
            with c6:
                amount = st.number_input("Amount (₹)", min_value=1.0, max_value=500000.0,
                    step=50.0, format="%.2f")
            with c7:
                matches = [s for s in standing_amts
                    if s["major_head_id"] == major_head_id
                    and (festival_id is None or s["festival_id"] == festival_id)]
                if matches:
                    hint = " · ".join(f"₹{s['default_amount']:,.0f} ({s['description']})" for s in matches)
                    st.markdown(f'<div class="hint-box">📌 <b>Standing:</b> {hint}</div>',
                        unsafe_allow_html=True)

            # Row 3 — Conditional payment ref | Description | Paid To
            c8, c9, c10 = st.columns([1, 1.5, 1.5])
            cheque_no = utr_ref_no = None
            with c8:
                if payment_mode == "CHEQUE":
                    cheque_no = st.text_input("Cheque No.", max_chars=30) or None
                elif payment_mode == "BANK_TRANSFER":
                    utr_ref_no = st.text_input("UTR Ref.", max_chars=40) or None
                else:
                    st.empty()
            with c9:
                description = st.text_input("Description", max_chars=50,
                    placeholder="e.g. April flowers NPK") or None
            with c10:
                paid_to = st.text_input("Paid To", max_chars=50,
                    placeholder="e.g. Subramania Pillai & Son") or None

            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("💾 Save Expense", type="primary")

        if submitted:
            errors = []
            if payment_mode == "CHEQUE" and not cheque_no:
                errors.append("Cheque number required.")
            if payment_mode == "BANK_TRANSFER" and not utr_ref_no:
                errors.append("UTR / Reference number required.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                try:
                    new_id = _save_expense({
                        "txn_date": txn_date, "fy": fy,
                        "fund_source_id": fund_source_id, "festival_id": festival_id,
                        "major_head_id": major_head_id, "amount": float(amount),
                        "payment_mode": payment_mode, "cheque_no": cheque_no,
                        "utr_ref_no": utr_ref_no, "description": description,
                        "paid_to": paid_to, "entered_by": user,
                    })
                    st.success(f"✅ Saved — #{new_id} · ₹{amount:,.2f} · {mh_options[major_head_id]}")
                    st.cache_data.clear()
                except Exception as exc:
                    st.error(f"Save failed: {exc}")

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 2 — Standing Amounts
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_standing:
        st.caption("Default amounts for recurring expenses — use as reference when entering monthly bills.")
        if not standing_amts:
            st.info("No standing amounts configured.")
        else:
            by_festival: dict = {}
            for s in standing_amts:
                key = s.get("festival_name") or "General"
                by_festival.setdefault(key, []).append(s)

            for fest_name, items in sorted(by_festival.items()):
                with st.expander(f"**{fest_name}**", expanded=True):
                    rows = [{
                        "Head": f"{i['mh_code']} {i['mh_name']}",
                        "Item": i["description"],
                        "₹ Default": f"{i['default_amount']:,.2f}",
                        "Notes": i["notes"] or "",
                    } for i in items]
                    st.dataframe(rows, use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Recent Entries
    # ═══════════════════════════════════════════════════════════════════════════
    with tab_recent:
        try:
            entries = _load_recent_entries(20)
        except Exception as exc:
            st.error(f"Could not load: {exc}")
            entries = []

        if not entries:
            st.info("No entries yet.")
        else:
            for e in entries:
                mode_badge = {"CASH": "💵", "CHEQUE": "🏦", "BANK_TRANSFER": "🔁"}.get(e["payment_mode"], "")
                desc_str = f" · {e['description']}" if e.get("description") else ""
                paid_str = f" → {e['paid_to']}" if e.get("paid_to") else ""
                fest_str = f'<span class="entry-badge">{e["festival_name"]}</span>' if e.get("festival_name") else ""
                st.markdown(f"""
                <div class="entry-row">
                  <div>
                    <span class="entry-date">{e['txn_date'].strftime('%d %b %Y')}</span>
                    &nbsp;·&nbsp;
                    <span style="color:#0369a1;font-size:0.72rem">{e['fund_code']}</span>
                    {fest_str}
                    <br>
                    <span class="entry-head">{e['mh_code']} {e['mh_name']}</span>
                    <span style="color:#64748b;font-size:0.78rem">{desc_str}{paid_str}</span>
                  </div>
                  <div style="text-align:right">
                    <span class="entry-amount">₹{float(e['amount']):,.2f}</span>
                    <br>
                    <span style="color:#94a3b8;font-size:0.72rem">{mode_badge} {e['entered_by']}</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
