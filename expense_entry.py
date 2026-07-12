# expense_entry.py — Piranjeri Temples Trust Accounting v3
# Tabs: New Expense | New Income | Manikandan A/C | Account Ledger | Trial Balance | Edit/Void
import streamlit as st
import pg8000.dbapi as _pg
from urllib.parse import urlparse, unquote
from datetime import date
from contextlib import contextmanager
from collections import defaultdict
import csv
import io
import os

# ── DB ─────────────────────────────────────────────────────────────────────────
def _connect():
    dsn = os.environ.get("NEON_DSN") or st.secrets["neon"]["dsn"]
    u = urlparse(dsn)
    return _pg.connect(
        host=u.hostname, database=u.path.lstrip("/"),
        user=unquote(u.username or ""), password=unquote(u.password or ""),
        port=u.port or 5432, ssl_context=True,
    )

@contextmanager
def _cursor():
    conn = _connect()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def _rows(cur):
    if not cur.description: return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def _row(cur):
    if not cur.description: return None
    row = cur.fetchone()
    return None if row is None else dict(zip([d[0] for d in cur.description], row))

def _fy(d: date) -> str:
    return f"{d.year}-{str(d.year+1)[2:]}" if d.month >= 4 else f"{d.year-1}-{str(d.year)[2:]}"

# ── Cached lookups ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _fund_sources():
    with _cursor() as c:
        c.execute("SELECT id,code,name FROM fund_sources WHERE is_active ORDER BY name")
        return _rows(c)

@st.cache_data(ttl=300)
def _festivals():
    with _cursor() as c:
        c.execute("SELECT id,code,name,fund_source_id FROM festivals WHERE is_active ORDER BY name")
        return _rows(c)

@st.cache_data(ttl=300)
def _major_heads():
    with _cursor() as c:
        c.execute("SELECT id,code,name FROM major_heads WHERE is_active ORDER BY code")
        return _rows(c)

# ── Write helpers ──────────────────────────────────────────────────────────────
def _save_expense(rec):
    with _cursor() as c:
        c.execute("""
            INSERT INTO expense_transactions
              (txn_date,fy,fund_source_id,festival_id,major_head_id,amount,
               payment_mode,cheque_no,utr_ref_no,description,paid_to,entered_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (rec["txn_date"],rec["fy"],rec["fund_source_id"],rec["festival_id"],
              rec["major_head_id"],rec["amount"],rec["payment_mode"],rec["cheque_no"],
              rec["utr_ref_no"],rec["description"],rec["paid_to"],rec["entered_by"]))
        return _row(c)["id"]

def _save_income(rec):
    with _cursor() as c:
        c.execute("""
            INSERT INTO income_transactions
              (txn_date,fy,book_no,receipt_no,donor_name,
               total_amount,bank_amount,cash_amount,payment_mode,
               fund_source_id,festival_id,income_type,entered_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (rec["txn_date"],rec["fy"],rec.get("book_no"),rec.get("receipt_no"),
              rec.get("donor_name"),rec["total_amount"],
              rec.get("bank_amount",0),rec.get("cash_amount",0),
              rec["payment_mode"],rec["fund_source_id"],rec.get("festival_id"),
              rec.get("income_type","DONATION"),rec["entered_by"]))
        return _row(c)["id"]

# ── Priest float ───────────────────────────────────────────────────────────────
def _priest_balance(fy_str):
    with _cursor() as c:
        c.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN txn_type='ADVANCE' THEN amount ELSE 0 END),0) advances,
              COALESCE(SUM(CASE WHEN txn_type='EXPENSE' THEN amount ELSE 0 END),0) expenses
            FROM priest_float WHERE fy=%s
        """, (fy_str,))
        r = _row(c)
        return float(r["advances"]), float(r["expenses"])

def _priest_ledger(fy_str):
    with _cursor() as c:
        c.execute("""
            SELECT pf.id,pf.txn_date,pf.txn_type,pf.amount,pf.description,
                   pf.payment_mode,pf.cheque_no,
                   mh.code mh_code, fs.code fund_code
            FROM priest_float pf
            LEFT JOIN major_heads mh ON mh.id=pf.major_head_id
            LEFT JOIN fund_sources fs ON fs.id=pf.fund_source_id
            WHERE pf.fy=%s ORDER BY pf.txn_date, pf.id
        """, (fy_str,))
        return _rows(c)

def _save_priest(rec):
    with _cursor() as c:
        c.execute("""
            INSERT INTO priest_float
              (txn_date,fy,txn_type,amount,major_head_id,fund_source_id,festival_id,
               description,payment_mode,cheque_no,utr_ref_no,entered_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (rec["txn_date"],rec["fy"],rec["txn_type"],rec["amount"],
              rec["major_head_id"],rec["fund_source_id"],rec["festival_id"],
              rec["description"],rec["payment_mode"],rec["cheque_no"],
              rec["utr_ref_no"],rec["entered_by"]))
        return _row(c)["id"]

# ── Account Ledger ─────────────────────────────────────────────────────────────
def _expense_ledger(mh_id, date_from, date_to):
    with _cursor() as c:
        c.execute("""
            SELECT et.id, et.txn_date, et.description, et.paid_to,
                   et.amount, et.payment_mode, fv.name festival_name
            FROM expense_transactions et
            LEFT JOIN festivals fv ON fv.id=et.festival_id
            WHERE et.major_head_id=%s
              AND et.txn_date >= %s AND et.txn_date <= %s
            ORDER BY et.txn_date, et.id
        """, (mh_id, date_from, date_to))
        return _rows(c)

def _income_ledger(fs_id, date_from, date_to):
    with _cursor() as c:
        c.execute("""
            SELECT it.id, it.txn_date, it.donor_name, it.receipt_no,
                   it.total_amount, it.payment_mode, it.income_type,
                   fv.name festival_name
            FROM income_transactions it
            LEFT JOIN festivals fv ON fv.id=it.festival_id
            WHERE it.fund_source_id=%s
              AND it.txn_date >= %s AND it.txn_date <= %s
            ORDER BY it.txn_date, it.id
        """, (fs_id, date_from, date_to))
        return _rows(c)

# ── Trial Balance ──────────────────────────────────────────────────────────────
def _trial_balance(date_from, date_to):
    with _cursor() as c:
        c.execute("""
            SELECT mh.code, mh.name, COALESCE(SUM(et.amount),0) total
            FROM major_heads mh
            LEFT JOIN expense_transactions et ON et.major_head_id=mh.id
              AND et.txn_date >= %s AND et.txn_date <= %s
            WHERE mh.is_active
            GROUP BY mh.id, mh.code, mh.name
            ORDER BY mh.code
        """, (date_from, date_to))
        exp_rows = _rows(c)
    with _cursor() as c:
        c.execute("""
            SELECT fs.code, fs.name, COALESCE(SUM(it.total_amount),0) total
            FROM fund_sources fs
            LEFT JOIN income_transactions it ON it.fund_source_id=fs.id
              AND it.txn_date >= %s AND it.txn_date <= %s
            WHERE fs.is_active
            GROUP BY fs.id, fs.code, fs.name
            ORDER BY fs.code
        """, (date_from, date_to))
        inc_rows = _rows(c)
    return exp_rows, inc_rows

# ── Bank statement functions ───────────────────────────────────────────────────
def _bank_opening(fy_str):
    """Return opening balances for a FY. Returns None if table missing or no row."""
    try:
        with _cursor() as c:
            c.execute("""
                SELECT savings_balance, fixed_deposit_balance, cash_balance, as_at, notes
                FROM bank_opening_balances WHERE fy=%s
            """, (fy_str,))
            return _row(c)
    except Exception:
        return None

def _bank_movements(date_from, date_to):
    """All bank-mode credits and debits for a period, sorted by date."""
    rows = []
    # Credits from income_transactions (bank_amount > 0)
    with _cursor() as c:
        c.execute("""
            SELECT txn_date AS dt,
                   COALESCE(donor_name, income_type, 'Income') AS narration,
                   bank_amount AS credit, 0.00 AS debit,
                   'INCOME' AS src, payment_mode AS mode
            FROM income_transactions
            WHERE bank_amount > 0
              AND txn_date >= %s AND txn_date <= %s
        """, (date_from, date_to))
        rows += _rows(c)
    # Credits from receipts table (cheque or bank_transfer)
    try:
        with _cursor() as c:
            c.execute("""
                SELECT issue_date::date AS dt,
                       name || ' — ' || purpose AS narration,
                       amount AS credit, 0.00 AS debit,
                       'RECEIPT' AS src, payment AS mode
                FROM receipts
                WHERE payment IN ('cheque','bank_transfer')
                  AND (status IS NULL OR status != 'CANCELLED')
                  AND issue_date >= %s AND issue_date <= %s
            """, (str(date_from), str(date_to)))
            rows += _rows(c)
    except Exception:
        pass
    # Debits from expense_transactions (cheque or bank transfer)
    with _cursor() as c:
        c.execute("""
            SELECT et.txn_date AS dt,
                   COALESCE(et.description, mh.name) AS narration,
                   0.00 AS credit, et.amount AS debit,
                   'EXPENSE' AS src, et.payment_mode AS mode
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id = et.major_head_id
            WHERE et.payment_mode IN ('CHEQUE','BANK_TRANSFER')
              AND et.txn_date >= %s AND et.txn_date <= %s
        """, (date_from, date_to))
        rows += _rows(c)
    # Sort by date
    rows.sort(key=lambda r: r["dt"])
    return rows

def _bank_csv(movements, opening, d_from, d_to):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"Bank Statement — Savings Account",
                f"Period: {d_from.strftime('%d %b %Y')} to {d_to.strftime('%d %b %Y')}"])
    w.writerow([])
    w.writerow(["Date","Narration","Source","Mode","Credit ₹","Debit ₹","Balance ₹"])
    bal = float(opening)
    w.writerow(["Opening Balance","","","","","", f"{bal:.2f}"])
    for r in movements:
        cr = float(r["credit"])
        dr = float(r["debit"])
        bal = bal + cr - dr
        dt = r["dt"].strftime("%d %b %Y") if hasattr(r["dt"], "strftime") else str(r["dt"])
        w.writerow([dt, r.get("narration",""), r.get("src",""),
                    r.get("mode",""),
                    f"{cr:.2f}" if cr else "", f"{dr:.2f}" if dr else "",
                    f"{bal:.2f}"])
    w.writerow(["Closing Balance","","","","","", f"{bal:.2f}"])
    return out.getvalue()

# ── All Expenses ledger (no account filter) ────────────────────────────────────
def _all_expenses_ledger(date_from, date_to):
    with _cursor() as c:
        c.execute("""
            SELECT et.id, et.txn_date, et.description, et.paid_to,
                   et.amount, et.payment_mode,
                   mh.code mh_code, mh.name mh_name,
                   fv.name festival_name
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id=et.major_head_id
            LEFT JOIN festivals fv ON fv.id=et.festival_id
            WHERE et.txn_date >= %s AND et.txn_date <= %s
            ORDER BY et.txn_date, mh.code, et.id
        """, (date_from, date_to))
        return _rows(c)

# ── Receipts table (Piranjeri-Receipts app) ────────────────────────────────────
def _receipts_summary(date_from, date_to):
    """Grouped by purpose from the receipts table. Returns [] on any error."""
    try:
        with _cursor() as c:
            c.execute("""
                SELECT purpose, COUNT(*) cnt, SUM(amount) total
                FROM receipts
                WHERE (status IS NULL OR status != 'CANCELLED')
                  AND issue_date >= %s AND issue_date <= %s
                GROUP BY purpose ORDER BY total DESC
            """, (str(date_from), str(date_to)))
            return _rows(c)
    except Exception:
        return []

def _receipts_ledger(date_from, date_to, purpose=None):
    """Line-level receipts. Filter by purpose if given."""
    try:
        with _cursor() as c:
            if purpose:
                c.execute("""
                    SELECT serial, issue_date, name, amount, purpose, payment
                    FROM receipts
                    WHERE (status IS NULL OR status != 'CANCELLED')
                      AND issue_date >= %s AND issue_date <= %s
                      AND purpose = %s
                    ORDER BY issue_date, serial
                """, (str(date_from), str(date_to), purpose))
            else:
                c.execute("""
                    SELECT serial, issue_date, name, amount, purpose, payment
                    FROM receipts
                    WHERE (status IS NULL OR status != 'CANCELLED')
                      AND issue_date >= %s AND issue_date <= %s
                    ORDER BY issue_date, serial
                """, (str(date_from), str(date_to)))
            return _rows(c)
    except Exception:
        return []

# ── Edit / Void ────────────────────────────────────────────────────────────────
def _search_expenses(fy_str, q="", limit=50):
    with _cursor() as c:
        c.execute("""
            SELECT et.id, et.txn_date, et.amount, et.payment_mode,
                   et.description, et.paid_to, et.cheque_no,
                   et.fund_source_id, et.festival_id, et.major_head_id,
                   mh.code mh_code, mh.name mh_name,
                   fs.code fund_code, fv.name festival_name, et.entered_by
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id=et.major_head_id
            JOIN fund_sources fs ON fs.id=et.fund_source_id
            LEFT JOIN festivals fv ON fv.id=et.festival_id
            WHERE et.fy=%s
              AND (%s='' OR et.description ILIKE %s OR CAST(et.id AS TEXT)=%s)
            ORDER BY et.txn_date DESC, et.id DESC LIMIT %s
        """, (fy_str, q, f"%{q}%", q, limit))
        return _rows(c)

def _update_expense(txn_id, upd):
    with _cursor() as c:
        c.execute("""
            UPDATE expense_transactions SET
              txn_date=%s, fund_source_id=%s, festival_id=%s, major_head_id=%s,
              amount=%s, payment_mode=%s, cheque_no=%s,
              description=%s, paid_to=%s
            WHERE id=%s
        """, (upd["txn_date"],upd["fund_source_id"],upd["festival_id"],
              upd["major_head_id"],upd["amount"],upd["payment_mode"],
              upd["cheque_no"],upd["description"],upd["paid_to"],txn_id))

def _void_expense(txn_id):
    with _cursor() as c:
        c.execute("DELETE FROM expense_transactions WHERE id=%s", (txn_id,))

# ── HTML table helper (no pandas) ──────────────────────────────────────────────
def _ledger_table(rows_html, extra_foot=""):
    st.markdown(f"""
    <table style="width:100%;border-collapse:collapse;font-size:.8rem">
    <thead><tr style="background:#1e40af;color:white">
      <th style="padding:6px 8px;text-align:left">Date</th>
      <th style="padding:6px 8px;text-align:left">Description</th>
      <th style="padding:6px 8px;text-align:left">Ref</th>
      <th style="padding:6px 8px;text-align:right">Debit ₹</th>
      <th style="padding:6px 8px;text-align:right">Credit ₹</th>
      <th style="padding:6px 8px;text-align:right">Balance ₹</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
    {extra_foot}
    </table>
    """, unsafe_allow_html=True)

def _tr(date_str, desc, ref, debit, credit, balance):
    dr = f"<td style='text-align:right;color:#991b1b;padding:5px 8px'>{debit}</td>"
    cr = f"<td style='text-align:right;color:#166534;padding:5px 8px'>{credit}</td>"
    bl = f"<td style='text-align:right;font-weight:600;padding:5px 8px'>{balance}</td>"
    return (f"<tr style='border-bottom:1px solid #e2e8f0'>"
            f"<td style='padding:5px 8px'>{date_str}</td>"
            f"<td style='padding:5px 8px'>{desc}</td>"
            f"<td style='padding:5px 8px;color:#64748b'>{ref}</td>"
            f"{dr}{cr}{bl}</tr>")

# ── CSV helper (no pandas / openpyxl needed) ───────────────────────────────────
def _expense_csv(txns, account_name, d_from, d_to):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"Account: {account_name}",
                f"Period: {d_from.strftime('%d %b %Y')} to {d_to.strftime('%d %b %Y')}"])
    w.writerow([])
    w.writerow(["Date","Description","Paid To","Festival","Payment Mode","Amount ₹","Balance ₹"])
    running = 0.0
    for r in txns:
        amt = float(r["amount"])
        running += amt
        w.writerow([
            r["txn_date"].strftime("%d %b %Y"),
            r.get("description",""),
            r.get("paid_to",""),
            r.get("festival_name",""),
            r.get("payment_mode",""),
            f"{amt:.2f}",
            f"{running:.2f}",
        ])
    w.writerow([])
    w.writerow(["","","","","TOTAL", f"{running:.2f}",""])
    return out.getvalue()

def _all_expenses_csv(txns, d_from, d_to):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"All Expense Accounts",
                f"Period: {d_from.strftime('%d %b %Y')} to {d_to.strftime('%d %b %Y')}"])
    w.writerow([])
    w.writerow(["Date","Account Code","Account Name","Description","Paid To","Festival","Mode","Amount ₹"])
    for r in txns:
        w.writerow([
            r["txn_date"].strftime("%d %b %Y"),
            r.get("mh_code",""),
            r.get("mh_name",""),
            r.get("description",""),
            r.get("paid_to",""),
            r.get("festival_name",""),
            r.get("payment_mode",""),
            f"{float(r['amount']):.2f}",
        ])
    return out.getvalue()

def _receipts_csv(txns, d_from, d_to):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"Receipts / Donations",
                f"Period: {d_from.strftime('%d %b %Y')} to {d_to.strftime('%d %b %Y')}"])
    w.writerow([])
    w.writerow(["Receipt No","Date","Donor Name","Purpose","Mode","Amount ₹"])
    for r in txns:
        w.writerow([
            r.get("serial",""),
            r.get("issue_date",""),
            r.get("name",""),
            r.get("purpose",""),
            r.get("payment",""),
            f"{float(r['amount']):.2f}",
        ])
    return out.getvalue()

def _income_csv(txns, account_name, d_from, d_to):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"Fund: {account_name}",
                f"Period: {d_from.strftime('%d %b %Y')} to {d_to.strftime('%d %b %Y')}"])
    w.writerow([])
    w.writerow(["Date","Donor / Narration","Receipt No","Festival","Mode","Amount ₹","Balance ₹"])
    running = 0.0
    for r in txns:
        amt = float(r["total_amount"])
        running += amt
        w.writerow([
            r["txn_date"].strftime("%d %b %Y"),
            r.get("donor_name",""),
            r.get("receipt_no",""),
            r.get("festival_name",""),
            r.get("payment_mode",""),
            f"{amt:.2f}",
            f"{running:.2f}",
        ])
    w.writerow([])
    w.writerow(["","","","","TOTAL", f"{running:.2f}",""])
    return out.getvalue()

# ── Festival breakdown widget (reused in multiple tabs) ────────────────────────
def _festival_breakdown(txns, amt_key):
    """Show festival subtotals for a list of transaction dicts."""
    fest_totals = defaultdict(float)
    grand = 0.0
    for r in txns:
        a = float(r.get(amt_key, 0))
        grand += a
        fest_totals[r.get("festival_name") or "General (No Festival)"] += a
    if not fest_totals:
        return
    st.markdown("**Festival-wise Breakdown**")
    fb_rows = ""
    for fname, ftotal in sorted(fest_totals.items(), key=lambda x: -x[1]):
        pct = ftotal / grand * 100 if grand else 0
        fb_rows += (f"<tr style='border-bottom:1px solid #e0e7ff'>"
                    f"<td style='padding:5px 8px'>{fname}</td>"
                    f"<td style='text-align:right;padding:5px 8px'>₹{ftotal:,.2f}</td>"
                    f"<td style='text-align:right;padding:5px 8px;color:#64748b'>{pct:.1f}%</td>"
                    f"</tr>")
    st.markdown(f"""
    <table style="width:100%;border-collapse:collapse;font-size:.82rem;margin-bottom:.5rem">
    <thead><tr style="background:#7c3aed;color:white">
      <th style="padding:6px 8px">Festival</th>
      <th style="text-align:right;padding:6px 8px">Amount ₹</th>
      <th style="text-align:right;padding:6px 8px">%</th>
    </tr></thead>
    <tbody>{fb_rows}</tbody>
    </table>
    """, unsafe_allow_html=True)

# ── CSS ────────────────────────────────────────────────────────────────────────
def _css():
    st.markdown("""<style>
    .balance-card{background:#1e40af;color:white;border-radius:10px;padding:1rem 1.4rem;
                  margin-bottom:1rem;display:flex;justify-content:space-between;align-items:center}
    .bal-num{font-size:1.6rem;font-weight:700}
    .bal-label{font-size:.75rem;opacity:.8}
    div[data-testid="stForm"] label{font-size:.78rem!important;font-weight:600!important;color:#475569!important}
    </style>""", unsafe_allow_html=True)

# ── Main ───────────────────────────────────────────────────────────────────────
def render_expense_entry(user: str):
    _css()
    fs_list   = _fund_sources()
    fest_list = _festivals()
    mh_list   = _major_heads()

    fs_by_id   = {f["id"]: f for f in fs_list}
    mh_by_id   = {m["id"]: m for m in mh_list}

    tabs = st.tabs(["✏️ New Expense", "💰 New Income", "👤 Manikandan A/C",
                    "📒 Account Ledger", "⚖️ Trial Balance", "🏦 Bank Statement", "🔧 Edit/Void"])

    # ═══════════════════════════════════════════════════════════
    # TAB 1 — New Expense
    # ═══════════════════════════════════════════════════════════
    with tabs[0]:
        st.markdown("#### ✏️ Record Expense")
        c1, c2, c3 = st.columns([1.2, 1, 1])
        with c1:
            txn_date = st.date_input("Date", value=date.today(), max_value=date.today(), key="ne_date")
            st.caption(f"FY {_fy(txn_date)}")
        with c2:
            mode = st.selectbox("Mode", ["CASH","CHEQUE","BANK_TRANSFER"],
                format_func=lambda x: {"CASH":"Cash","CHEQUE":"Cheque","BANK_TRANSFER":"Bank Tfr"}[x],
                key="ne_mode")
        with c3:
            fs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            fs_id = st.selectbox("Fund", list(fs_opts), format_func=lambda x: fs_opts[x], key="ne_fs")

        c4, c5 = st.columns([2, 1])
        with c4:
            mh_opts = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
            mh_id = st.selectbox("Account (Head)", list(mh_opts), format_func=lambda x: mh_opts[x], key="ne_mh")
        with c5:
            amount = st.number_input("Amount (₹)", min_value=1.0, max_value=500000.0,
                step=50.0, format="%.2f", key="ne_amount")

        ff = [f for f in fest_list if f["fund_source_id"] == fs_id]
        fo = {None: "— General —"} | {f["id"]: f["name"] for f in ff}
        fest_id = st.selectbox("Festival", list(fo), format_func=lambda x: fo[x], key="ne_fest")

        c6, c7, c8 = st.columns([1, 1.5, 1.5])
        cheque_no = utr = None
        with c6:
            if mode == "CHEQUE":
                cheque_no = st.text_input("Cheque No.", max_chars=30, key="ne_chq") or None
            elif mode == "BANK_TRANSFER":
                utr = st.text_input("UTR Ref.", max_chars=40, key="ne_utr") or None
        with c7:
            desc = st.text_input("Description", max_chars=60,
                placeholder="e.g. Flowers for Garuda Seva", key="ne_desc") or None
        with c8:
            paid_to = st.text_input("Paid To", max_chars=50, key="ne_paid") or None

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Expense", type="primary", key="ne_save"):
            errs = []
            if mode == "CHEQUE" and not cheque_no: errs.append("Cheque number required.")
            if mode == "BANK_TRANSFER" and not utr: errs.append("UTR required.")
            if errs:
                for e in errs: st.error(e)
            else:
                try:
                    nid = _save_expense({
                        "txn_date": txn_date, "fy": _fy(txn_date),
                        "fund_source_id": fs_id, "festival_id": fest_id,
                        "major_head_id": mh_id, "amount": float(amount),
                        "payment_mode": mode, "cheque_no": cheque_no,
                        "utr_ref_no": utr, "description": desc,
                        "paid_to": paid_to, "entered_by": user
                    })
                    st.success(f"✅ Saved #{nid} · ₹{amount:,.2f} · {mh_opts[mh_id]}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Save failed: {ex}")

    # ═══════════════════════════════════════════════════════════
    # TAB 2 — New Income
    # ═══════════════════════════════════════════════════════════
    with tabs[1]:
        st.markdown("#### 💰 Record Income / Collection")
        i1, i2, i3 = st.columns([1.2, 1, 1.2])
        with i1:
            i_date = st.date_input("Date", value=date.today(), max_value=date.today(), key="ni_date")
        with i2:
            i_mode = st.selectbox("Mode", ["CASH","CHEQUE","BANK_TRANSFER","BOTH"],
                format_func=lambda x: {"CASH":"Cash","CHEQUE":"Cheque",
                                       "BANK_TRANSFER":"Bank Tfr","BOTH":"Bank+Cash"}[x],
                key="ni_mode")
        with i3:
            i_fs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            i_fs = st.selectbox("Fund", list(i_fs_opts), format_func=lambda x: i_fs_opts[x], key="ni_fs")

        i4, i5 = st.columns([2, 1])
        with i4:
            i_ff = [f for f in fest_list if f["fund_source_id"] == i_fs]
            i_fo = {None: "— General —"} | {f["id"]: f["name"] for f in i_ff}
            i_fest = st.selectbox("Festival", list(i_fo), format_func=lambda x: i_fo[x], key="ni_fest")
        with i5:
            i_type = st.selectbox("Type", ["DONATION","INTEREST","OTHER"], key="ni_type")

        i6, i7, i8 = st.columns([1.5, 1, 1])
        with i6:
            i_donor = st.text_input("Donor / Narration", max_chars=80, key="ni_donor") or None
        with i7:
            i_rec = st.text_input("Receipt No.", max_chars=20, key="ni_rec") or None
        with i8:
            i_amt = st.number_input("Amount (₹)", min_value=1.0, max_value=1000000.0,
                step=100.0, format="%.2f", key="ni_amt")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Income", type="primary", key="ni_save"):
            try:
                amt_f = float(i_amt)
                if i_mode == "CASH":
                    bank_a, cash_a = 0.0, amt_f
                elif i_mode in ("CHEQUE","BANK_TRANSFER"):
                    bank_a, cash_a = amt_f, 0.0
                else:  # BOTH — split equally
                    bank_a = cash_a = round(amt_f / 2, 2)
                nid = _save_income({
                    "txn_date": i_date, "fy": _fy(i_date),
                    "book_no": None,
                    "receipt_no": int(i_rec) if i_rec and i_rec.isdigit() else None,
                    "donor_name": i_donor, "total_amount": amt_f,
                    "bank_amount": bank_a, "cash_amount": cash_a,
                    "payment_mode": i_mode, "fund_source_id": i_fs,
                    "festival_id": i_fest, "income_type": i_type,
                    "entered_by": user
                })
                st.success(f"✅ Income #{nid} · ₹{i_amt:,.2f} saved.")
                st.cache_data.clear()
                st.rerun()
            except Exception as ex:
                st.error(f"Save failed: {ex}")

    # ═══════════════════════════════════════════════════════════
    # TAB 3 — Manikandan A/C
    # ═══════════════════════════════════════════════════════════
    with tabs[2]:
        today = date.today()
        fy_str = _fy(today)
        try:
            adv, exp = _priest_balance(fy_str)
            balance = adv - exp
            bal_color = "#1e40af" if balance >= 0 else "#991b1b"
            st.markdown(f"""
            <div class="balance-card" style="background:{bal_color}">
              <div>
                <div class="bal-label">MANIKANDAN — CASH IN HAND &nbsp;·&nbsp; FY {fy_str}</div>
                <div class="bal-num">₹{balance:,.2f}</div>
              </div>
              <div style="text-align:right;font-size:.8rem;opacity:.85">
                Advances: ₹{adv:,.2f}<br>Settled: ₹{exp:,.2f}
              </div>
            </div>
            """, unsafe_allow_html=True)
        except Exception as ex:
            st.error(f"Error loading balance: {ex}")
            st.stop()

        action = st.radio("Action", ["Issue Advance","Record Settlement"],
                          horizontal=True, key="mani_action")

        if action == "Issue Advance":
            with st.form("adv_form", clear_on_submit=True):
                ca, cb, cc = st.columns([1.2, 1, 1.2])
                with ca: adate = st.date_input("Date", value=today, max_value=today)
                with cb: amode = st.selectbox("Mode", ["CHEQUE","BANK_TRANSFER"],
                    format_func=lambda x: {"CHEQUE":"Cheque","BANK_TRANSFER":"Bank Tfr"}[x])
                with cc: aamt = st.number_input("Amount (₹)", min_value=1.0,
                    max_value=200000.0, step=500.0, format="%.2f")
                achq  = st.text_input("Cheque / UTR No.", max_chars=40) or None
                adesc = st.text_input("Narration", max_chars=50,
                    placeholder="e.g. Monthly advance July 2026") or None
                aok = st.form_submit_button("💾 Record Advance", type="primary")
            if aok:
                try:
                    nid = _save_priest({
                        "txn_date": adate, "fy": _fy(adate), "txn_type": "ADVANCE",
                        "amount": float(aamt), "major_head_id": None,
                        "fund_source_id": None, "festival_id": None,
                        "description": adesc, "payment_mode": amode,
                        "cheque_no": achq if amode == "CHEQUE" else None,
                        "utr_ref_no": achq if amode == "BANK_TRANSFER" else None,
                        "entered_by": user
                    })
                    st.success(f"✅ Advance #{nid} · ₹{aamt:,.2f}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed: {ex}")
        else:
            with st.form("settle_form", clear_on_submit=True):
                s1, s2, s3, s4 = st.columns([1.2, 1.4, 1.4, 1])
                with s1: sdate = st.date_input("Date", value=today, max_value=today)
                with s2:
                    smh_opts = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
                    smh = st.selectbox("Head", list(smh_opts), format_func=lambda x: smh_opts[x])
                with s3:
                    sfs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
                    sfs = st.selectbox("Fund", list(sfs_opts), format_func=lambda x: sfs_opts[x])
                with s4: samt = st.number_input("₹", min_value=1.0,
                    max_value=200000.0, step=50.0, format="%.2f")
                sdesc = st.text_input("Description", max_chars=50) or None
                sok = st.form_submit_button("💾 Record Settlement", type="primary")
            if sok:
                try:
                    nid = _save_priest({
                        "txn_date": sdate, "fy": _fy(sdate), "txn_type": "EXPENSE",
                        "amount": float(samt), "major_head_id": smh,
                        "fund_source_id": sfs, "festival_id": None,
                        "description": sdesc, "payment_mode": None,
                        "cheque_no": None, "utr_ref_no": None, "entered_by": user
                    })
                    st.success(f"✅ Settlement #{nid} · ₹{samt:,.2f}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed: {ex}")

        # Running balance ledger
        st.markdown("---")
        st.markdown(f"**Account Statement — FY {fy_str}**")
        try:
            ledger = _priest_ledger(fy_str)
            if not ledger:
                st.info("No transactions yet.")
            else:
                running = 0.0
                rows_html = ""
                for r in ledger:
                    is_adv = r["txn_type"] == "ADVANCE"
                    amt = float(r["amount"])
                    running = running + amt if is_adv else running - amt
                    desc = r.get("description") or ""
                    ref  = f"Chq {r['cheque_no']}" if r.get("cheque_no") else (r.get("mh_code") or "")
                    dr   = f"₹{amt:,.2f}" if not is_adv else ""
                    cr   = f"₹{amt:,.2f}" if is_adv else ""
                    rows_html += _tr(r["txn_date"].strftime("%d %b %Y"),
                                     f"{'ADVANCE' if is_adv else 'SETTLEMENT'} — {desc}",
                                     ref, dr, cr, f"₹{running:,.2f}")
                foot = (f"<tfoot><tr style='font-weight:700;background:#f0fdf4'>"
                        f"<td colspan='3' style='padding:6px 8px'>Closing Balance</td>"
                        f"<td></td><td></td>"
                        f"<td style='text-align:right;padding:6px 8px'>₹{running:,.2f}</td>"
                        f"</tr></tfoot>")
                _ledger_table(rows_html, foot)
        except Exception as ex:
            st.error(f"Error: {ex}")

    # ═══════════════════════════════════════════════════════════
    # TAB 4 — Account Ledger
    # ═══════════════════════════════════════════════════════════
    with tabs[3]:
        st.markdown("#### 📒 Account Ledger")

        acct_type = st.radio("Account Type",
                             ["Expense Account (E-01, E-02 ...)","Income / Fund Account",
                              "Receipts / Donations (Apr 2026+)"],
                             horizontal=True, key="al_type")

        # Date range
        _today = date.today()
        _fy_yr = _today.year if _today.month >= 4 else _today.year - 1
        al1, al2 = st.columns(2)
        with al1: d_from = st.date_input("From", value=date(_fy_yr, 4, 1), key="al_from")
        with al2: d_to   = st.date_input("To",   value=_today, key="al_to")

        # ── EXPENSE ACCOUNTS ───────────────────────────────────────────────────
        if acct_type.startswith("Expense"):
            exp_scope = st.radio("View", ["Single Account", "ALL Accounts"],
                                 horizontal=True, key="al_scope")

            if exp_scope == "Single Account":
                mh_opts2 = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
                sel_mh = st.selectbox("Select Expense Account", list(mh_opts2),
                                      format_func=lambda x: mh_opts2[x], key="al_mh")
                if st.button("🔍 Show Ledger", key="al_exp"):
                    txns = _expense_ledger(sel_mh, d_from, d_to)
                    if not txns:
                        st.info("No transactions for this period.")
                    else:
                        acct_label = mh_opts2[sel_mh]
                        running = 0.0
                        rows_html = ""
                        for r in txns:
                            amt = float(r["amount"])
                            running += amt
                            desc = r.get("description") or ""
                            fest = r.get("festival_name") or ""
                            if fest: desc = f"{desc} [{fest}]".strip(" []") if desc else fest
                            ref  = r.get("paid_to") or r.get("payment_mode") or ""
                            rows_html += _tr(r["txn_date"].strftime("%d %b %Y"),
                                             desc, ref,
                                             f"₹{amt:,.2f}", "", f"₹{running:,.2f}")
                        foot = (f"<tfoot><tr style='font-weight:700;background:#fee2e2'>"
                                f"<td colspan='3' style='padding:6px 8px'>Total</td>"
                                f"<td style='text-align:right;padding:6px 8px'>₹{running:,.2f}</td>"
                                f"<td></td><td></td></tr></tfoot>")
                        _ledger_table(rows_html, foot)
                        st.caption(f"{len(txns)} transactions · Total ₹{running:,.2f}")
                        _festival_breakdown(txns, "amount")
                        csv_data = _expense_csv(txns, acct_label, d_from, d_to)
                        fname_csv = (f"{acct_label.split('—')[0].strip()}_"
                                     f"{d_from.strftime('%Y%m%d')}_to_{d_to.strftime('%Y%m%d')}.csv")
                        st.download_button("⬇️ Download CSV", data=csv_data,
                                           file_name=fname_csv, mime="text/csv")

            else:  # ALL Accounts
                if st.button("🔍 Show All Expenses", key="al_all"):
                    txns = _all_expenses_ledger(d_from, d_to)
                    if not txns:
                        st.info("No transactions for this period.")
                    else:
                        grand_total = sum(float(r["amount"]) for r in txns)
                        # Table with account column
                        rows_html = ""
                        for r in txns:
                            amt = float(r["amount"])
                            desc = r.get("description") or ""
                            fest = r.get("festival_name") or ""
                            accode = f"{r.get('mh_code','')} {r.get('mh_name','')}"
                            rows_html += (
                                f"<tr style='border-bottom:1px solid #e2e8f0'>"
                                f"<td style='padding:5px 8px'>{r['txn_date'].strftime('%d %b %Y')}</td>"
                                f"<td style='padding:5px 8px;color:#1e40af;font-weight:600'>{r.get('mh_code','')}</td>"
                                f"<td style='padding:5px 8px'>{desc}</td>"
                                f"<td style='padding:5px 8px;color:#64748b'>{fest}</td>"
                                f"<td style='padding:5px 8px;color:#64748b'>{r.get('paid_to','')}</td>"
                                f"<td style='text-align:right;padding:5px 8px;color:#991b1b'>₹{amt:,.2f}</td>"
                                f"</tr>"
                            )
                        foot = (f"<tfoot><tr style='font-weight:700;background:#fee2e2'>"
                                f"<td colspan='5' style='padding:6px 8px'>GRAND TOTAL</td>"
                                f"<td style='text-align:right;padding:6px 8px'>₹{grand_total:,.2f}</td>"
                                f"</tr></tfoot>")
                        st.markdown(f"""
                        <table style="width:100%;border-collapse:collapse;font-size:.8rem">
                        <thead><tr style="background:#1e40af;color:white">
                          <th style="padding:6px 8px">Date</th>
                          <th style="padding:6px 8px">Account</th>
                          <th style="padding:6px 8px">Description</th>
                          <th style="padding:6px 8px">Festival</th>
                          <th style="padding:6px 8px">Paid To</th>
                          <th style="text-align:right;padding:6px 8px">Amount ₹</th>
                        </tr></thead>
                        <tbody>{rows_html}</tbody>
                        {foot}
                        </table>
                        """, unsafe_allow_html=True)
                        st.caption(f"{len(txns)} transactions · Grand Total ₹{grand_total:,.2f}")

                        # Account-wise subtotals
                        st.markdown("**Account-wise Subtotals**")
                        acct_totals = defaultdict(float)
                        for r in txns:
                            acct_totals[f"{r.get('mh_code','')} — {r.get('mh_name','')}"] += float(r["amount"])
                        at_rows = ""
                        for aname, atotal in sorted(acct_totals.items()):
                            pct = atotal / grand_total * 100 if grand_total else 0
                            at_rows += (f"<tr style='border-bottom:1px solid #fecaca'>"
                                        f"<td style='padding:5px 8px'>{aname}</td>"
                                        f"<td style='text-align:right;padding:5px 8px'>₹{atotal:,.2f}</td>"
                                        f"<td style='text-align:right;padding:5px 8px;color:#64748b'>{pct:.1f}%</td>"
                                        f"</tr>")
                        st.markdown(f"""
                        <table style="width:100%;border-collapse:collapse;font-size:.82rem;margin-bottom:.5rem">
                        <thead><tr style="background:#991b1b;color:white">
                          <th style="padding:6px 8px">Account</th>
                          <th style="text-align:right;padding:6px 8px">Total ₹</th>
                          <th style="text-align:right;padding:6px 8px">%</th>
                        </tr></thead>
                        <tbody>{at_rows}</tbody>
                        </table>
                        """, unsafe_allow_html=True)

                        _festival_breakdown(txns, "amount")

                        csv_data = _all_expenses_csv(txns, d_from, d_to)
                        fname_csv = f"ALL_Expenses_{d_from.strftime('%Y%m%d')}_to_{d_to.strftime('%Y%m%d')}.csv"
                        st.download_button("⬇️ Download CSV", data=csv_data,
                                           file_name=fname_csv, mime="text/csv")

        # ── INCOME / FUND ACCOUNTS ─────────────────────────────────────────────
        elif acct_type.startswith("Income"):
            fs_opts2 = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            sel_fs = st.selectbox("Select Fund Account", list(fs_opts2),
                                  format_func=lambda x: fs_opts2[x], key="al_fs")
            if st.button("🔍 Show Ledger", key="al_inc"):
                txns = _income_ledger(sel_fs, d_from, d_to)
                if not txns:
                    st.info("No transactions for this period.")
                else:
                    acct_label = fs_opts2[sel_fs]
                    running = 0.0
                    rows_html = ""
                    for r in txns:
                        amt = float(r["total_amount"])
                        running += amt
                        desc = r.get("donor_name") or r.get("income_type","")
                        fest = r.get("festival_name") or ""
                        if fest: desc = f"{desc} [{fest}]".strip(" []") if desc else fest
                        ref  = f"Rec#{r['receipt_no']}" if r.get("receipt_no") else ""
                        rows_html += _tr(r["txn_date"].strftime("%d %b %Y"),
                                         desc, ref,
                                         "", f"₹{amt:,.2f}", f"₹{running:,.2f}")
                    foot = (f"<tfoot><tr style='font-weight:700;background:#dcfce7'>"
                            f"<td colspan='3' style='padding:6px 8px'>Total</td>"
                            f"<td></td>"
                            f"<td style='text-align:right;padding:6px 8px'>₹{running:,.2f}</td>"
                            f"<td></td></tr></tfoot>")
                    _ledger_table(rows_html, foot)
                    st.caption(f"{len(txns)} transactions · Total ₹{running:,.2f}")
                    _festival_breakdown(txns, "total_amount")
                    csv_data = _income_csv(txns, acct_label, d_from, d_to)
                    fname_csv = (f"{fs_opts2[sel_fs].split('—')[0].strip()}_"
                                 f"{d_from.strftime('%Y%m%d')}_to_{d_to.strftime('%Y%m%d')}.csv")
                    st.download_button("⬇️ Download CSV", data=csv_data,
                                       file_name=fname_csv, mime="text/csv")

        # ── RECEIPTS (Apr 2026+) ───────────────────────────────────────────────
        else:
            st.caption("Data from Piranjeri-Receipts app — automatically synced (same database)")
            purpose_opts = ["ALL"] + [
                "Nithya Pooja","Garuda Seva","Pradhosham","Sangabhishekam",
                "Panguni uthiram","Annadhanam","Kumbhabhishekam","Varushabhishekam",
                "Temple Renovation","General Donation","Bank Interest"
            ]
            sel_purpose = st.selectbox("Purpose / Festival", purpose_opts, key="al_purpose")

            if st.button("🔍 Show Receipts", key="al_rec"):
                purpose_filter = None if sel_purpose == "ALL" else sel_purpose
                txns = _receipts_ledger(d_from, d_to, purpose_filter)
                summary = _receipts_summary(d_from, d_to)

                if not txns and not summary:
                    st.warning("No receipts found — the receipts table may have a different name. "
                               "Check db.py in Piranjeri-Receipts repo for the actual table name.")
                elif not txns:
                    st.info("No receipts for this purpose / period.")
                else:
                    total = sum(float(r["amount"]) for r in txns)
                    rows_html = ""
                    for r in txns:
                        amt = float(r["amount"])
                        rows_html += (
                            f"<tr style='border-bottom:1px solid #e2e8f0'>"
                            f"<td style='padding:5px 8px'>{r.get('serial','')}</td>"
                            f"<td style='padding:5px 8px'>{r.get('issue_date','')}</td>"
                            f"<td style='padding:5px 8px'>{r.get('name','')}</td>"
                            f"<td style='padding:5px 8px'>{r.get('purpose','')}</td>"
                            f"<td style='padding:5px 8px;color:#64748b'>{r.get('payment','')}</td>"
                            f"<td style='text-align:right;padding:5px 8px;color:#166534'>₹{amt:,.2f}</td>"
                            f"</tr>"
                        )
                    foot = (f"<tfoot><tr style='font-weight:700;background:#dcfce7'>"
                            f"<td colspan='5' style='padding:6px 8px'>TOTAL</td>"
                            f"<td style='text-align:right;padding:6px 8px'>₹{total:,.2f}</td>"
                            f"</tr></tfoot>")
                    st.markdown(f"""
                    <table style="width:100%;border-collapse:collapse;font-size:.8rem">
                    <thead><tr style="background:#166534;color:white">
                      <th style="padding:6px 8px">Receipt No</th>
                      <th style="padding:6px 8px">Date</th>
                      <th style="padding:6px 8px">Donor</th>
                      <th style="padding:6px 8px">Purpose</th>
                      <th style="padding:6px 8px">Mode</th>
                      <th style="text-align:right;padding:6px 8px">Amount ₹</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                    {foot}
                    </table>
                    """, unsafe_allow_html=True)
                    st.caption(f"{len(txns)} receipts · Total ₹{total:,.2f}")

                    if summary and sel_purpose == "ALL":
                        st.markdown("**Purpose-wise Summary**")
                        sb_rows = ""
                        for r in summary:
                            sb_rows += (f"<tr style='border-bottom:1px solid #bbf7d0'>"
                                        f"<td style='padding:5px 8px'>{r['purpose']}</td>"
                                        f"<td style='text-align:right;padding:5px 8px'>{r['cnt']}</td>"
                                        f"<td style='text-align:right;padding:5px 8px'>₹{float(r['total']):,.2f}</td>"
                                        f"</tr>")
                        st.markdown(f"""
                        <table style="width:100%;border-collapse:collapse;font-size:.82rem">
                        <thead><tr style="background:#166534;color:white">
                          <th style="padding:6px 8px">Purpose</th>
                          <th style="text-align:right;padding:6px 8px">Count</th>
                          <th style="text-align:right;padding:6px 8px">Total ₹</th>
                        </tr></thead>
                        <tbody>{sb_rows}</tbody>
                        </table>
                        """, unsafe_allow_html=True)

                    csv_data = _receipts_csv(txns, d_from, d_to)
                    fname_csv = f"Receipts_{d_from.strftime('%Y%m%d')}_to_{d_to.strftime('%Y%m%d')}.csv"
                    st.download_button("⬇️ Download CSV", data=csv_data,
                                       file_name=fname_csv, mime="text/csv")

    # ═══════════════════════════════════════════════════════════
    # TAB 5 — Trial Balance
    # ═══════════════════════════════════════════════════════════
    with tabs[4]:
        st.markdown("#### ⚖️ Trial Balance")

        today = date.today()
        fy_start_year = today.year if today.month >= 4 else today.year - 1
        tb1, tb2 = st.columns(2)
        with tb1: tb_from = st.date_input("From", value=date(fy_start_year, 4, 1), key="tb_from")
        with tb2: tb_to   = st.date_input("To",   value=today, key="tb_to")

        if st.button("📊 Generate Trial Balance", type="primary", key="tb_load"):
            exp_rows, inc_rows = _trial_balance(tb_from, tb_to)

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Expenses — Debit Side**")
                total_exp = 0.0
                rows_html = ""
                for r in exp_rows:
                    amt = float(r["total"])
                    if amt > 0:
                        total_exp += amt
                        rows_html += (f"<tr style='border-bottom:1px solid #fecaca'>"
                                      f"<td style='padding:5px 8px'>{r['code']} {r['name']}</td>"
                                      f"<td style='text-align:right;padding:5px 8px'>₹{amt:,.2f}</td>"
                                      f"</tr>")
                if rows_html:
                    st.markdown(f"""
                    <table style="width:100%;border-collapse:collapse;font-size:.82rem">
                    <thead><tr style="background:#991b1b;color:white">
                      <th style="padding:6px 8px">Account</th>
                      <th style="text-align:right;padding:6px 8px">Amount ₹</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                    <tfoot><tr style="font-weight:700;background:#fee2e2">
                      <td style="padding:6px 8px">TOTAL EXPENSES</td>
                      <td style="text-align:right;padding:6px 8px">₹{total_exp:,.2f}</td>
                    </tr></tfoot>
                    </table>
                    """, unsafe_allow_html=True)
                else:
                    st.info("No expenses.")

            with col2:
                st.markdown("**Income — Credit Side**")
                total_inc = 0.0
                rows_html = ""
                for r in inc_rows:
                    amt = float(r["total"])
                    if amt > 0:
                        total_inc += amt
                        rows_html += (f"<tr style='border-bottom:1px solid #bbf7d0'>"
                                      f"<td style='padding:5px 8px'>{r['code']} {r['name']}</td>"
                                      f"<td style='text-align:right;padding:5px 8px'>₹{amt:,.2f}</td>"
                                      f"</tr>")

                # Also fetch receipts for this period
                rec_summary = _receipts_summary(tb_from, tb_to)
                total_rec = sum(float(r["total"]) for r in rec_summary) if rec_summary else 0.0
                total_inc_all = total_inc  # will be updated below

                if rows_html or rec_summary:
                    # Fund-based income (income_transactions)
                    if rows_html:
                        st.markdown(f"""
                        <table style="width:100%;border-collapse:collapse;font-size:.82rem">
                        <thead><tr style="background:#166534;color:white">
                          <th style="padding:6px 8px">Fund (Historical)</th>
                          <th style="text-align:right;padding:6px 8px">Amount ₹</th>
                        </tr></thead>
                        <tbody>{rows_html}</tbody>
                        <tfoot><tr style="font-weight:700;background:#dcfce7">
                          <td style="padding:6px 8px">Sub-total</td>
                          <td style="text-align:right;padding:6px 8px">₹{total_inc:,.2f}</td>
                        </tr></tfoot>
                        </table>
                        """, unsafe_allow_html=True)
                    # Receipts (receipts table)
                    if rec_summary:
                        st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
                        rec_rows = ""
                        for r in rec_summary:
                            rec_rows += (f"<tr style='border-bottom:1px solid #bbf7d0'>"
                                         f"<td style='padding:5px 8px'>{r['purpose']}"
                                         f" <span style='color:#64748b;font-size:.75rem'>({int(r['cnt'])} receipts)</span></td>"
                                         f"<td style='text-align:right;padding:5px 8px'>₹{float(r['total']):,.2f}</td>"
                                         f"</tr>")
                        st.markdown(f"""
                        <table style="width:100%;border-collapse:collapse;font-size:.82rem">
                        <thead><tr style="background:#0d9488;color:white">
                          <th style="padding:6px 8px">Receipts / Donations</th>
                          <th style="text-align:right;padding:6px 8px">Amount ₹</th>
                        </tr></thead>
                        <tbody>{rec_rows}</tbody>
                        <tfoot><tr style="font-weight:700;background:#ccfbf1">
                          <td style="padding:6px 8px">Sub-total</td>
                          <td style="text-align:right;padding:6px 8px">₹{total_rec:,.2f}</td>
                        </tr></tfoot>
                        </table>
                        """, unsafe_allow_html=True)
                    total_inc_all = total_inc + total_rec
                    st.markdown(f"""
                    <div style="background:#dcfce7;border-radius:6px;padding:.5rem .8rem;
                                font-weight:700;margin-top:.4rem">
                      TOTAL INCOME &nbsp;·&nbsp; ₹{total_inc_all:,.2f}
                    </div>""", unsafe_allow_html=True)
                else:
                    st.info("No income.")
                    total_inc_all = 0.0

            net = (total_inc + total_rec) - total_exp
            total_inc = total_inc + total_rec  # for summary card below
            net_color = "#166534" if net >= 0 else "#991b1b"
            net_label = "SURPLUS" if net >= 0 else "DEFICIT"
            st.markdown(f"""
            <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                        padding:.8rem 1.4rem;margin-top:1rem;display:flex;gap:3rem;flex-wrap:wrap">
              <div><div style="font-size:.7rem;color:#64748b">TOTAL INCOME</div>
                   <div style="font-weight:700;font-size:1.1rem;color:#166534">₹{total_inc:,.2f}</div></div>
              <div><div style="font-size:.7rem;color:#64748b">TOTAL EXPENSES</div>
                   <div style="font-weight:700;font-size:1.1rem;color:#991b1b">₹{total_exp:,.2f}</div></div>
              <div><div style="font-size:.7rem;color:#64748b">NET {net_label}</div>
                   <div style="font-weight:700;font-size:1.2rem;color:{net_color}">₹{abs(net):,.2f}</div></div>
            </div>
            """, unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════
    # TAB 6 — Bank Statement
    # ═══════════════════════════════════════════════════════════
    with tabs[5]:
        st.markdown("#### 🏦 Bank Statement — Savings Account")

        _today2 = date.today()
        _fy_yr2 = _today2.year if _today2.month >= 4 else _today2.year - 1
        cur_fy2 = f"{_fy_yr2}-{str(_fy_yr2+1)[2:]}"

        # FY selector
        bk_fy_opts = [cur_fy2, f"{_fy_yr2-1}-{str(_fy_yr2)[2:]}"]
        bk_fy = st.selectbox("Financial Year", bk_fy_opts, key="bk_fy")

        # Derive date range for selected FY
        bk_yr = int(bk_fy[:4])
        bk_d_from = date(bk_yr, 4, 1)
        bk_d_to   = date(bk_yr+1, 3, 31) if _today2 > date(bk_yr+1, 3, 31) else _today2

        bk1, bk2 = st.columns(2)
        with bk1: bk_from = st.date_input("From", value=bk_d_from, key="bk_from")
        with bk2: bk_to   = st.date_input("To",   value=bk_d_to,   key="bk_to")

        if st.button("📊 Generate Bank Statement", type="primary", key="bk_load"):
            ob = _bank_opening(bk_fy)
            if ob is None:
                st.warning("⚠️ Opening balance not found for this FY. "
                           "Please run `bank_setup.sql` in Neon SQL Editor first.")
            else:
                ob_savings = float(ob["savings_balance"])
                ob_fd      = float(ob["fixed_deposit_balance"])
                ob_cash    = float(ob["cash_balance"])

                # Opening balance cards
                st.markdown(f"""
                <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem">
                  <div style="background:#1e40af;color:white;border-radius:8px;
                              padding:.8rem 1.2rem;flex:1;min-width:160px">
                    <div style="font-size:.7rem;opacity:.8">OPENING SAVINGS BALANCE</div>
                    <div style="font-size:1.3rem;font-weight:700">₹{ob_savings:,.2f}</div>
                    <div style="font-size:.7rem;opacity:.7">as at {ob['as_at'].strftime('%d %b %Y')}</div>
                  </div>
                  <div style="background:#0d9488;color:white;border-radius:8px;
                              padding:.8rem 1.2rem;flex:1;min-width:160px">
                    <div style="font-size:.7rem;opacity:.8">FIXED DEPOSIT</div>
                    <div style="font-size:1.3rem;font-weight:700">₹{ob_fd:,.2f}</div>
                    <div style="font-size:.7rem;opacity:.7">as at {ob['as_at'].strftime('%d %b %Y')}</div>
                  </div>
                  <div style="background:#7c3aed;color:white;border-radius:8px;
                              padding:.8rem 1.2rem;flex:1;min-width:160px">
                    <div style="font-size:.7rem;opacity:.8">CASH IN HAND</div>
                    <div style="font-size:1.3rem;font-weight:700">₹{ob_cash:,.2f}</div>
                    <div style="font-size:.7rem;opacity:.7">as at {ob['as_at'].strftime('%d %b %Y')}</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)
                if ob.get("notes"):
                    st.caption(f"Source: {ob['notes']}")

                movements = _bank_movements(bk_from, bk_to)

                if not movements:
                    st.info("No bank transactions for this period.")
                else:
                    running = ob_savings
                    total_cr = total_dr = 0.0
                    rows_html = ""
                    for r in movements:
                        cr = float(r["credit"])
                        dr = float(r["debit"])
                        running = running + cr - dr
                        total_cr += cr
                        total_dr += dr
                        dt = r["dt"].strftime("%d %b %Y") if hasattr(r["dt"],"strftime") else str(r["dt"])
                        # Source badge
                        src = r.get("src","")
                        if src == "INCOME":
                            src_badge = "Fund"
                            badge_bg = "#dcfce7"
                            badge_fg = "#166534"
                        elif src == "RECEIPT":
                            src_badge = "Receipt"
                            badge_bg = "#ccfbf1"
                            badge_fg = "#0d9488"
                        else:
                            src_badge = "Expense"
                            badge_bg = "#fee2e2"
                            badge_fg = "#991b1b"
                        badge_html = (f"<span style=\"background:{badge_bg};color:{badge_fg};"
                                      f"padding:1px 5px;border-radius:3px;font-size:.72rem\">"
                                      f"{src_badge}</span>")
                        cr_cell = (f"<td style=\"text-align:right;padding:5px 8px;color:#166534\">&#8377;{cr:,.2f}</td>" if cr
                                   else "<td style=\"padding:5px 8px\"></td>")
                        dr_cell = (f"<td style=\"text-align:right;padding:5px 8px;color:#991b1b\">&#8377;{dr:,.2f}</td>" if dr
                                   else "<td style=\"padding:5px 8px\"></td>")
                        rows_html += (
                            f"<tr style=\"border-bottom:1px solid #e2e8f0\">"
                            f"<td style=\"padding:5px 8px\">{dt}</td>"
                            f"<td style=\"padding:5px 8px\">{r.get('narration','')[:55]}</td>"
                            f"<td style=\"padding:5px 8px\">{badge_html}</td>"
                            f"<td style=\"padding:5px 8px;color:#64748b;font-size:.78rem\">"
                            f"{(r.get('mode') or '').replace('_',' ')}</td>"
                            f"{cr_cell}{dr_cell}"
                            f"<td style=\"text-align:right;font-weight:600;padding:5px 8px\">&#8377;{running:,.2f}</td>"
                            f"</tr>"
                        )

                    foot = (
                        "<tfoot><tr style=\"font-weight:700;background:#f0fdf4\">"
                        "<td colspan=\"4\" style=\"padding:6px 8px\">CLOSING BALANCE</td>"
                        f"<td style=\"text-align:right;padding:6px 8px;color:#166534\">&#8377;{total_cr:,.2f}</td>"
                        f"<td style=\"text-align:right;padding:6px 8px;color:#991b1b\">&#8377;{total_dr:,.2f}</td>"
                        f"<td style=\"text-align:right;padding:6px 8px\">&#8377;{running:,.2f}</td>"
                        "</tr></tfoot>"
                    )
                    st.markdown(
                        "<table style=\"width:100%;border-collapse:collapse;font-size:.8rem\">"
                        "<thead><tr style=\"background:#1e40af;color:white\">"
                        "<th style=\"padding:6px 8px\">Date</th>"
                        "<th style=\"padding:6px 8px\">Narration</th>"
                        "<th style=\"padding:6px 8px\">Type</th>"
                        "<th style=\"padding:6px 8px\">Mode</th>"
                        "<th style=\"text-align:right;padding:6px 8px\">Credit</th>"
                        "<th style=\"text-align:right;padding:6px 8px\">Debit</th>"
                        "<th style=\"text-align:right;padding:6px 8px\">Balance</th>"
                        f"</tr></thead><tbody>{rows_html}</tbody>{foot}</table>",
                        unsafe_allow_html=True
                    )

                    net = total_cr - total_dr
                    cl_color = "#1e40af" if running >= 0 else "#991b1b"
                    st.markdown(
                        f"<div style=\"display:flex;gap:1rem;flex-wrap:wrap;margin-top:.8rem\">"
                        f"<div style=\"background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;"
                        f"padding:.7rem 1rem;flex:1;min-width:130px\">"
                        f"<div style=\"font-size:.7rem;color:#64748b\">OPENING</div>"
                        f"<div style=\"font-weight:700\">&#8377;{ob_savings:,.2f}</div></div>"
                        f"<div style=\"background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;"
                        f"padding:.7rem 1rem;flex:1;min-width:130px\">"
                        f"<div style=\"font-size:.7rem;color:#64748b\">CREDITS</div>"
                        f"<div style=\"font-weight:700;color:#166534\">&#8377;{total_cr:,.2f}</div></div>"
                        f"<div style=\"background:#fff5f5;border:1px solid #fecaca;border-radius:8px;"
                        f"padding:.7rem 1rem;flex:1;min-width:130px\">"
                        f"<div style=\"font-size:.7rem;color:#64748b\">DEBITS</div>"
                        f"<div style=\"font-weight:700;color:#991b1b\">&#8377;{total_dr:,.2f}</div></div>"
                        f"<div style=\"background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;"
                        f"padding:.7rem 1rem;flex:1;min-width:130px\">"
                        f"<div style=\"font-size:.7rem;color:#64748b\">CLOSING</div>"
                        f"<div style=\"font-weight:700;color:{cl_color}\">&#8377;{running:,.2f}</div></div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    csv_data = _bank_csv(movements, ob_savings, bk_from, bk_to)
                    st.download_button(
                        "\u2b07\ufe0f Download CSV",
                        data=csv_data,
                        file_name=f"Bank_Statement_{bk_fy}_{bk_from.strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )

    # ═══════════════════════════════════════════════════════════
    # TAB 7 — Edit / Void
    # ═══════════════════════════════════════════════════════════
    with tabs[6]:
        st.markdown("#### \U0001f527 Edit or Void an Expense")

        cur_fy = _fy(date.today())
        yr = int(cur_fy[:4])
        fy_opts = [cur_fy, f"{yr-1}-{str(yr)[2:]}"]

        ec1, ec2 = st.columns([1, 3])
        with ec1: ev_fy = st.selectbox("FY", fy_opts, key="ev_fy")
        with ec2: ev_q  = st.text_input("Search description or ID",
                                         key="ev_q", placeholder="e.g. flowers  or  42")

        if st.button("\U0001f50d Search", key="ev_search"):
            st.session_state.ev_results = _search_expenses(ev_fy, ev_q.strip())
            st.session_state.ev_sel = None

        results_ev = st.session_state.get("ev_results")
        if results_ev is not None:
            if not results_ev:
                st.info("No entries found.")
            else:
                rows_html = ""
                for r in results_ev:
                    rows_html += (
                        f"<tr style=\"border-bottom:1px solid #e2e8f0\">"
                        f"<td style=\"padding:5px 8px\">#{r['id']}</td>"
                        f"<td style=\"padding:5px 8px\">{r['txn_date'].strftime('%d %b %Y')}</td>"
                        f"<td style=\"padding:5px 8px\">{r['fund_code']}</td>"
                        f"<td style=\"padding:5px 8px\">{r['mh_code']}</td>"
                        f"<td style=\"text-align:right;padding:5px 8px\">&#8377;{float(r['amount']):,.2f}</td>"
                        f"<td style=\"padding:5px 8px\">{(r.get('description') or '')[:40]}</td>"
                        f"</tr>"
                    )
                st.markdown(
                    "<table style=\"width:100%;border-collapse:collapse;font-size:.8rem\">"
                    "<thead><tr style=\"background:#1e40af;color:white\">"
                    "<th style=\"padding:6px 8px\">ID</th><th style=\"padding:6px 8px\">Date</th>"
                    "<th style=\"padding:6px 8px\">Fund</th><th style=\"padding:6px 8px\">Head</th>"
                    "<th style=\"text-align:right;padding:6px 8px\">Amount</th>"
                    f"<th style=\"padding:6px 8px\">Description</th>"
                    f"</tr></thead><tbody>{rows_html}</tbody></table>",
                    unsafe_allow_html=True
                )
                st.caption(f"{len(results_ev)} entries found")

                id_label = {
                    r["id"]: f"#{r['id']} \u00b7 {r['txn_date'].strftime('%d %b %Y')} \u00b7 "
                             f"{r['fund_code']} \u00b7 &#8377;{float(r['amount']):,.0f}"
                    for r in results_ev
                }
                sel_id = st.selectbox(
                    "Select entry to edit / void",
                    options=[None] + list(id_label.keys()),
                    format_func=lambda x: "\u2014 pick a row \u2014" if x is None else id_label[x],
                    key="ev_sel"
                )

                if sel_id:
                    sel = next(r for r in results_ev if r["id"] == sel_id)
                    st.markdown("---")
                    st.markdown(f"**Editing #{sel['id']}** \u00b7 entered by `{sel['entered_by']}`")
                    with st.form("edit_form"):
                        fe1, fe2, fe3 = st.columns([1.1, 0.9, 1.4])
                        with fe1: e_date = st.date_input("Date", value=sel["txn_date"])
                        with fe2:
                            modes = ["CASH","CHEQUE","BANK_TRANSFER"]
                            e_mode = st.selectbox("Mode", modes,
                                index=modes.index(sel["payment_mode"] or "CASH"),
                                format_func=lambda x: {"CASH":"Cash","CHEQUE":"Cheque",
                                                       "BANK_TRANSFER":"Bank Tfr"}[x])
                        with fe3:
                            fs_opts_e = {f["id"]: f"{f['code']} \u2014 {f['name']}" for f in fs_list}
                            fs_keys_e = list(fs_opts_e.keys())
                            e_fs = st.selectbox("Fund", fs_keys_e,
                                index=fs_keys_e.index(sel["fund_source_id"])
                                      if sel["fund_source_id"] in fs_keys_e else 0,
                                format_func=lambda x: fs_opts_e[x])

                        fe4, fe5 = st.columns([2, 1])
                        with fe4:
                            mh_opts_e = {m["id"]: f"{m['code']} \u2014 {m['name']}" for m in mh_list}
                            mh_keys_e = list(mh_opts_e.keys())
                            e_mh = st.selectbox("Head", mh_keys_e,
                                index=mh_keys_e.index(sel["major_head_id"])
                                      if sel["major_head_id"] in mh_keys_e else 0,
                                format_func=lambda x: mh_opts_e[x])
                        with fe5:
                            e_amt = st.number_input("Amount", min_value=1.0,
                                value=float(sel["amount"]), step=50.0, format="%.2f")

                        ff_e = [f for f in fest_list if f["fund_source_id"] == e_fs]
                        fo_e = {None: "\u2014 General \u2014"} | {f["id"]: f["name"] for f in ff_e}
                        fk_e = list(fo_e.keys())
                        e_fest = st.selectbox("Festival", fk_e,
                            index=fk_e.index(sel["festival_id"])
                                  if sel["festival_id"] in fk_e else 0,
                            format_func=lambda x: fo_e[x])

                        e_chq = None
                        if e_mode == "CHEQUE":
                            e_chq = st.text_input("Cheque No.",
                                value=sel.get("cheque_no") or "", max_chars=30) or None
                        e_desc = st.text_input("Description",
                            value=sel.get("description") or "", max_chars=60) or None
                        e_paid = st.text_input("Paid To",
                            value=sel.get("paid_to") or "", max_chars=50) or None

                        b1, b2 = st.columns([3, 1])
                        with b1: do_save = st.form_submit_button("\U0001f4be Save Changes", type="primary")
                        with b2: do_void = st.form_submit_button("\U0001f5d1\ufe0f Delete", type="secondary")

                    if do_save:
                        try:
                            _update_expense(sel_id, {
                                "txn_date": e_date, "fund_source_id": e_fs,
                                "festival_id": e_fest, "major_head_id": e_mh,
                                "amount": float(e_amt), "payment_mode": e_mode,
                                "cheque_no": e_chq, "description": e_desc, "paid_to": e_paid
                            })
                            st.success(f"\u2705 Entry #{sel_id} updated.")
                            st.session_state.ev_results = None
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Save failed: {ex}")

                    if do_void:
                        try:
                            _void_expense(sel_id)
                            st.success(f"\u2705 Entry #{sel_id} deleted.")
                            st.session_state.ev_results = None
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Delete failed: {ex}")
