# expense_entry.py — Piranjeri Temples Trust Accounting v4
# render functions: render_expense_entry | render_bank_statement | render_edit_void
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


def _full_tb(date_from, date_to, ob):
    """
    Full double-entry trial balance.
    ob = row from bank_opening_balances.
    Returns (dr_rows, cr_rows, dr_total, cr_total).
    Each row: {'account': str, 'amount': float}.
    """
    dr_rows, cr_rows = [], []
    fy_str = _fy(date_from)

    # ── CR SIDE: Opening Fund + Income ────────────────────────────
    ob_total = float(ob['savings_balance']) + float(ob['fixed_deposit_balance']) + float(ob['cash_balance'])
    cr_rows.append({'account': 'General Fund — Opening Balance', 'amount': ob_total})

    # Income from income_transactions (historical)
    with _cursor() as c:
        c.execute("""
            SELECT fs.code, fs.name, COALESCE(SUM(it.total_amount),0) total
            FROM fund_sources fs
            LEFT JOIN income_transactions it ON it.fund_source_id=fs.id
              AND it.txn_date >= %s AND it.txn_date <= %s
            WHERE fs.is_active
            GROUP BY fs.id, fs.code, fs.name
            HAVING COALESCE(SUM(it.total_amount),0) > 0
            ORDER BY fs.code
        """, (date_from, date_to))
        for r in _rows(c):
            cr_rows.append({'account': f"{r['code']} {r['name']}", 'amount': float(r['total'])})

    # Income from receipts table (Apr 2026+)
    try:
        rec_sum = _receipts_summary(date_from, date_to)
        for r in rec_sum:
            if float(r.get('total', 0)) > 0:
                cr_rows.append({'account': r['purpose'], 'amount': float(r['total'])})
    except Exception:
        pass

    # ── DR SIDE: Expenses (by major head, from expense_transactions only) ───
    # priest_float EXPENSE entries serve only the Manikandan A/C ledger.
    # Including them here would double-count expenses already in expense_transactions.
    with _cursor() as c:
        c.execute("""
            SELECT mh.code, mh.name,
                   COALESCE(SUM(et.amount),0) AS et_total
            FROM major_heads mh
            LEFT JOIN expense_transactions et ON et.major_head_id=mh.id
              AND et.txn_date >= %s AND et.txn_date <= %s
            WHERE mh.is_active
            GROUP BY mh.id, mh.code, mh.name
            ORDER BY mh.code
        """, (date_from, date_to))
        for r in _rows(c):
            amt = float(r['et_total'])
            if amt > 0:
                dr_rows.append({'account': f"{r['code']} {r['name']}", 'amount': amt})

    # ── DR SIDE: Closing Asset Balances ───────────────────────────
    # Savings Bank A/C
    bank_mvts = _bank_movements(date_from, date_to)
    bank_bal = float(ob['savings_balance'])
    for m in bank_mvts:
        bank_bal += float(m.get('credit', 0)) - float(m.get('debit', 0))
    if bank_bal >= 0:
        dr_rows.append({'account': 'Savings Bank A/C', 'amount': bank_bal})
    else:
        cr_rows.append({'account': 'Savings Bank A/C (Cr)', 'amount': abs(bank_bal)})

    # Fixed Deposit A/C
    fd_bal = float(ob['fixed_deposit_balance'])
    dr_rows.append({'account': 'Fixed Deposit A/C', 'amount': fd_bal})

    # Cash in Hand
    cash_mvts = _cash_movements(date_from, date_to)
    cash_bal = float(ob['cash_balance'])
    for m in cash_mvts:
        cash_bal += float(m.get('credit', 0)) - float(m.get('debit', 0))
    if cash_bal >= 0:
        dr_rows.append({'account': 'Cash in Hand', 'amount': cash_bal})
    else:
        cr_rows.append({'account': 'Cash in Hand (Cr)', 'amount': abs(cash_bal)})

    # Manikandan A/C (net advance balance)
    try:
        with _cursor() as c:
            c.execute("""
                SELECT
                  COALESCE(SUM(CASE WHEN txn_type='ADVANCE' THEN amount ELSE 0 END),0) adv,
                  COALESCE(SUM(CASE WHEN txn_type='EXPENSE'  THEN amount ELSE 0 END),0) exp
                FROM priest_float WHERE fy=%s
            """, (fy_str,))
            r = _row(c)
            mani_bal = float(r['adv']) - float(r['exp']) if r else 0.0
        if mani_bal > 0:
            dr_rows.append({'account': 'Manikandan A/C (Outstanding Advance)', 'amount': mani_bal})
        elif mani_bal < 0:
            cr_rows.append({'account': 'Manikandan A/C (Cr)', 'amount': abs(mani_bal)})
    except Exception:
        pass

    dr_total = sum(r['amount'] for r in dr_rows)
    cr_total = sum(r['amount'] for r in cr_rows)
    return dr_rows, cr_rows, dr_total, cr_total

# ── Bank statement functions ───────────────────────────────────────────────────
def _cash_movements(date_from, date_to):
    """Cash account movements — Dr = cash in, Cr = cash out."""
    rows = []
    with _cursor() as c:
        c.execute("""
            SELECT txn_date AS dt,
                   COALESCE(donor_name, income_type, 'Cash Receipt') AS narration,
                   cash_amount AS credit, 0.00 AS debit,
                   'INCOME' AS src
            FROM income_transactions
            WHERE cash_amount > 0 AND txn_date >= %s AND txn_date <= %s
        """, (date_from, date_to))
        rows += _rows(c)
    try:
        with _cursor() as c:
            c.execute("""
                SELECT issue_date::date AS dt,
                       name || ' — ' || purpose AS narration,
                       amount AS credit, 0.00 AS debit,
                       'RECEIPT' AS src
                FROM receipts
                WHERE payment = 'cash'
                  AND (status IS NULL OR status != 'CANCELLED')
                  AND issue_date >= %s AND issue_date <= %s
            """, (str(date_from), str(date_to)))
            rows += _rows(c)
    except Exception:
        pass
    with _cursor() as c:
        c.execute("""
            SELECT txn_date AS dt,
                   COALESCE(description, paid_to, 'Cash Expense') AS narration,
                   0.00 AS credit, amount AS debit,
                   'EXPENSE' AS src
            FROM expense_transactions
            WHERE payment_mode = 'CASH' AND txn_date >= %s AND txn_date <= %s
        """, (date_from, date_to))
        rows += _rows(c)
    # Cash advances to Manikandan
    try:
        with _cursor() as c:
            c.execute("""
                SELECT txn_date AS dt,
                       'Advance to Manikandan'::text AS narration,
                       0.00 AS credit, amount AS debit,
                       'ADVANCE' AS src
                FROM priest_float
                WHERE txn_type = 'ADVANCE' AND payment_mode = 'CASH'
                  AND txn_date >= %s AND txn_date <= %s
            """, (date_from, date_to))
            rows += _rows(c)
    except Exception:
        pass
    rows.sort(key=lambda r: r["dt"])
    return rows


def _bank_opening(fy_str):
    """Return (row_or_None, err_str) for the given FY opening balance."""
    try:
        with _cursor() as c:
            c.execute("""
                SELECT savings_balance, fixed_deposit_balance, cash_balance, as_at, notes
                FROM bank_opening_balances WHERE fy=%s
            """, (fy_str,))
            return _row(c), None
    except Exception as ex:
        return None, str(ex)

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

    st.markdown("#### 📝 Journal Entry")
    acct_keys, acct_labels = _acct_opts()

    # ── Row 1: Date | Account | Dr/Cr | Amount ────────────────────────────
    r1, r2, r3, r4 = st.columns([1.2, 2.6, 0.7, 1.2])
    with r1:
        je_date = st.date_input("Date", value=date.today(),
            max_value=date.today(), key="je_date")
        st.caption(f"FY {_fy(je_date)}")
    with r2:
        je_acct = st.selectbox("Account", acct_keys,
            format_func=lambda x: acct_labels[x], key="je_acct")
    with r3:
        je_dc = st.selectbox("Dr/Cr", ["Dr", "Cr"], key="je_dc")
    with r4:
        je_amt = st.number_input("Amount (₹)", min_value=0.01,
            step=50.0, format="%.2f", key="je_amt")

    is_mh   = je_acct.startswith("mh_")
    is_fs   = je_acct.startswith("fs_")
    is_mani = je_acct == MANI
    is_cash = je_acct == CASH
    is_bank = je_acct == BANK

    route_expense  = (is_mh and je_dc == "Dr") or ((is_cash or is_bank) and je_dc == "Cr")
    route_income   = (is_fs and je_dc == "Cr") or ((is_cash or is_bank) and je_dc == "Dr")
    route_mani_adv = is_mani and je_dc == "Dr"
    route_mani_exp = is_mani and je_dc == "Cr"

    # Manikandan balance card — visible whenever Manikandan A/C is selected
    if is_mani:
        try:
            _adv, _exp = _priest_balance(_fy(je_date))
            _bal = _adv - _exp
            _bc  = "#1e40af" if _bal >= 0 else "#991b1b"
            st.markdown(f"""
            <div class="balance-card" style="background:{_bc};margin:.4rem 0">
              <div>
                <div class="bal-label">MANIKANDAN A/C · FY {_fy(je_date)}</div>
                <div class="bal-num">₹{_bal:,.2f} {'Dr' if _bal >= 0 else 'Cr'}</div>
              </div>
              <div style="text-align:right;font-size:.8rem;opacity:.85">
                Advances ₹{_adv:,.2f} &nbsp;·&nbsp; Settled ₹{_exp:,.2f}
              </div>
            </div>""", unsafe_allow_html=True)
        except Exception:
            pass

    st.markdown("---")

    # ── EXPENSE path ───────────────────────────────────────────────────────
    if route_expense:
        xe1, xe2, xe3 = st.columns([1.2, 2, 1])
        with xe1:
            xe_mode = st.selectbox("Mode",
                ["CASH","CHEQUE","BANK_TRANSFER"],
                format_func=lambda x: {"CASH":"Cash","CHEQUE":"Cheque",
                                       "BANK_TRANSFER":"Bank Tfr"}[x],
                key="je_xmode")
        with xe2:
            xe_fs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            xe_fs = st.selectbox("Fund", list(xe_fs_opts),
                format_func=lambda x: xe_fs_opts[x], key="je_xfs")
        with xe3:
            xe_ff = [f for f in fest_list if f["fund_source_id"] == xe_fs]
            xe_fo = {None: "— General —"} | {f["id"]: f["name"] for f in xe_ff}
            xe_fest = st.selectbox("Festival", list(xe_fo),
                format_func=lambda x: xe_fo[x], key="je_xfest")

        # If Cash/Bank was the account, need to pick the expense head
        if is_cash or is_bank:
            xe_mh_opts = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
            xe_mh_id = st.selectbox("Expense Head", list(xe_mh_opts),
                format_func=lambda x: xe_mh_opts[x], key="je_xmh")
        else:
            xe_mh_id = mh_by_key[je_acct]

        xb1, xb2, xb3 = st.columns([1.2, 1.8, 1.3])
        xe_chq = xe_utr = None
        with xb1:
            if xe_mode == "CHEQUE":
                xe_chq = st.text_input("Cheque No.", max_chars=30, key="je_xchq") or None
            elif xe_mode == "BANK_TRANSFER":
                xe_utr = st.text_input("UTR Ref.", max_chars=40, key="je_xutr") or None
        with xb2:
            xe_desc = st.text_input("Description", max_chars=60,
                placeholder="e.g. Flowers for Garuda Seva", key="je_xdesc") or None
        with xb3:
            xe_paid = st.text_input("Paid To", max_chars=50, key="je_xpaid") or None

        if st.button("💾 Save Expense", type="primary", key="je_save_exp"):
            errs = []
            if xe_mode == "CHEQUE" and not xe_chq: errs.append("Cheque number required.")
            if xe_mode == "BANK_TRANSFER" and not xe_utr: errs.append("UTR required.")
            if errs:
                for e in errs: st.error(e)
            else:
                try:
                    nid = _save_expense({
                        "txn_date": je_date, "fy": _fy(je_date),
                        "fund_source_id": xe_fs, "festival_id": xe_fest,
                        "major_head_id": xe_mh_id, "amount": float(je_amt),
                        "payment_mode": xe_mode, "cheque_no": xe_chq,
                        "utr_ref_no": xe_utr, "description": xe_desc,
                        "paid_to": xe_paid, "entered_by": user
                    })
                    st.success(f"✅ Expense #{nid} · ₹{je_amt:,.2f} · {acct_labels[je_acct]}")
                    st.cache_data.clear(); st.rerun()
                except Exception as ex:
                    st.error(f"Save failed: {ex}")

    # ── INCOME path ────────────────────────────────────────────────────────
    elif route_income:
        xi1, xi2 = st.columns([1.2, 1])
        with xi1:
            xi_mode = st.selectbox("Mode",
                ["CASH","CHEQUE","BANK_TRANSFER","BOTH"],
                format_func=lambda x: {"CASH":"Cash","CHEQUE":"Cheque",
                                       "BANK_TRANSFER":"Bank Tfr","BOTH":"Bank+Cash"}[x],
                key="je_imode")
        with xi2:
            xi_type = st.selectbox("Type",
                ["DONATION","INTEREST","OTHER"], key="je_itype")

        # If Cash/Bank selected, need to pick the fund source
        if is_cash or is_bank:
            xi_fs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            xi_fs = st.selectbox("Fund", list(xi_fs_opts),
                format_func=lambda x: xi_fs_opts[x], key="je_ifs")
        else:
            xi_fs = fs_by_key[je_acct]

        xi_ff = [f for f in fest_list if f["fund_source_id"] == xi_fs]
        xi_fo = {None: "— General —"} | {f["id"]: f["name"] for f in xi_ff}
        xi_fest = st.selectbox("Festival", list(xi_fo),
            format_func=lambda x: xi_fo[x], key="je_ifest")

        xi3, xi4 = st.columns([2, 1])
        with xi3:
            xi_donor = st.text_input("Donor / Narration", max_chars=80, key="je_idonor") or None
        with xi4:
            xi_rec = st.text_input("Receipt No.", max_chars=20, key="je_irec") or None

        if st.button("💾 Save Income", type="primary", key="je_save_inc"):
            try:
                amt_f = float(je_amt)
                if xi_mode == "CASH":
                    bank_a, cash_a = 0.0, amt_f
                elif xi_mode in ("CHEQUE","BANK_TRANSFER"):
                    bank_a, cash_a = amt_f, 0.0
                else:
                    bank_a = cash_a = round(amt_f / 2, 2)
                nid = _save_income({
                    "txn_date": je_date, "fy": _fy(je_date), "book_no": None,
                    "receipt_no": int(xi_rec) if xi_rec and xi_rec.isdigit() else None,
                    "donor_name": xi_donor, "total_amount": amt_f,
                    "bank_amount": bank_a, "cash_amount": cash_a,
                    "payment_mode": xi_mode, "fund_source_id": xi_fs,
                    "festival_id": xi_fest, "income_type": xi_type,
                    "entered_by": user
                })
                st.success(f"✅ Income #{nid} · ₹{je_amt:,.2f} saved.")
                st.cache_data.clear(); st.rerun()
            except Exception as ex:
                st.error(f"Save failed: {ex}")

    # ── MANIKANDAN — ADVANCE (Dr) ──────────────────────────────────────────
    elif route_mani_adv:
        xa1, xa2 = st.columns([1, 2])
        with xa1:
            xa_mode = st.selectbox("Mode",
                ["CHEQUE","BANK_TRANSFER"],
                format_func=lambda x: {"CHEQUE":"Cheque","BANK_TRANSFER":"Bank Tfr"}[x],
                key="je_amode")
        with xa2:
            xa_ref = st.text_input("Cheque / UTR No.", max_chars=40, key="je_aref") or None
        xa_desc = st.text_input("Narration", max_chars=50,
            placeholder="e.g. Monthly advance April 2026", key="je_adesc") or None

        if st.button("💾 Save Advance", type="primary", key="je_save_adv"):
            try:
                nid = _save_priest({
                    "txn_date": je_date, "fy": _fy(je_date), "txn_type": "ADVANCE",
                    "amount": float(je_amt), "major_head_id": None,
                    "fund_source_id": None, "festival_id": None,
                    "description": xa_desc, "payment_mode": xa_mode,
                    "cheque_no": xa_ref if xa_mode == "CHEQUE" else None,
                    "utr_ref_no": xa_ref if xa_mode == "BANK_TRANSFER" else None,
                    "entered_by": user
                })
                st.success(f"✅ Advance #{nid} · ₹{je_amt:,.2f}")
                st.cache_data.clear(); st.rerun()
            except Exception as ex:
                st.error(f"Failed: {ex}")

    # ── MANIKANDAN — SETTLEMENT (Cr) ───────────────────────────────────────
    elif route_mani_exp:
        xs1, xs2 = st.columns([2, 1])
        with xs1:
            xs_mh_opts = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
            xs_mh = st.selectbox("Contra Expense Head", list(xs_mh_opts),
                format_func=lambda x: xs_mh_opts[x], key="je_smh")
        with xs2:
            xs_fs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            xs_fs = st.selectbox("Fund", list(xs_fs_opts),
                format_func=lambda x: xs_fs_opts[x], key="je_sfs")
        xs_desc = st.text_input("Description", max_chars=50, key="je_sdesc") or None

        if st.button("💾 Save Settlement", type="primary", key="je_save_set"):
            try:
                nid = _save_priest({
                    "txn_date": je_date, "fy": _fy(je_date), "txn_type": "EXPENSE",
                    "amount": float(je_amt), "major_head_id": xs_mh,
                    "fund_source_id": xs_fs, "festival_id": None,
                    "description": xs_desc, "payment_mode": None,
                    "cheque_no": None, "utr_ref_no": None, "entered_by": user
                })
                st.success(f"✅ Settlement #{nid} · ₹{je_amt:,.2f}")
                st.cache_data.clear(); st.rerun()
            except Exception as ex:
                st.error(f"Failed: {ex}")

    # ── Unusual direction ──────────────────────────────────────────────────
    else:
        if is_mh and je_dc == "Cr":
            st.info("ℹ️ Expense account Cr = reversal entry. Switch to **Dr** to record a normal payment.")
        elif is_fs and je_dc == "Dr":
            st.info("ℹ️ Income/Fund account Dr = reversal entry. Switch to **Cr** to record income received.")

# ═══════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────
def render_bank_statement(user: str):
    """Bank Statement view — called from app_accounting.py sidebar nav."""
    _css()
    st.markdown("#### 🏦 Bank Statement — Savings Account")

    _today2 = date.today()
    _fy_yr2 = _today2.year if _today2.month >= 4 else _today2.year - 1
    cur_fy2 = f"{_fy_yr2}-{str(_fy_yr2+1)[2:]}"

    # FY selector — show previous FY first (has audited opening balance)
    prev_fy2 = f"{_fy_yr2-1}-{str(_fy_yr2)[2:]}"
    bk_fy_opts = [prev_fy2, cur_fy2]
    bk_fy = st.selectbox("Financial Year", bk_fy_opts, key="bk_fy")

    # Derive date range for selected FY
    bk_yr = int(bk_fy[:4])
    bk_d_from = date(bk_yr, 4, 1)
    bk_d_to   = date(bk_yr+1, 3, 31) if _today2 > date(bk_yr+1, 3, 31) else _today2

    bk1, bk2 = st.columns(2)
    with bk1: bk_from = st.date_input("From", value=bk_d_from, key="bk_from")
    with bk2: bk_to   = st.date_input("To",   value=bk_d_to,   key="bk_to")

    if st.button("📊 Generate Bank Statement", type="primary", key="bk_load"):
        ob, ob_err = _bank_opening(bk_fy)
        if ob_err:
            st.error(f"Database error: {ob_err}")
        elif ob is None:
            st.warning(
                f"⚠️ No opening balance found for FY {bk_fy}. "
                f"Run `bank_setup.sql` in Neon SQL Editor to add the {bk_fy} opening balance."
            )
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
                    src_badge = {
                        "INCOME":  "<span style='background:#dcfce7;color:#166534;padding:1px 5px;border-radius:3px;font-size:.72rem'>Fund</span>",
                        "RECEIPT": "<span style='background:#ccfbf1;color:#0d9488;padding:1px 5px;border-radius:3px;font-size:.72rem'>Receipt</span>",
                        "EXPENSE": "<span style='background:#fee2e2;color:#991b1b;padding:1px 5px;border-radius:3px;font-size:.72rem'>Expense</span>",
                    }.get(r.get("src",""), "")
                    cr_cell = f"<td style='text-align:right;padding:5px 8px;color:#166534'>₹{cr:,.2f}</td>" if cr else "<td style='padding:5px 8px'></td>"
                    dr_cell = f"<td style='text-align:right;padding:5px 8px;color:#991b1b'>₹{dr:,.2f}</td>" if dr else "<td style='padding:5px 8px'></td>"
                    rows_html += (
                        f"<tr style='border-bottom:1px solid #e2e8f0'>"
                        f"<td style='padding:5px 8px'>{dt}</td>"
                        f"<td style='padding:5px 8px'>{r.get('narration','')[:55]}</td>"
                        f"<td style='padding:5px 8px'>{src_badge}</td>"
                        f"<td style='padding:5px 8px;color:#64748b;font-size:.78rem'>{(r.get('mode') or '').replace('_',' ')}</td>"
                        f"{cr_cell}{dr_cell}"
                        f"<td style='text-align:right;font-weight:600;padding:5px 8px'>₹{running:,.2f}</td>"
                        f"</tr>"
                    )

                foot = (f"<tfoot><tr style='font-weight:700;background:#f0fdf4'>"
                        f"<td colspan='4' style='padding:6px 8px'>CLOSING BALANCE</td>"
                        f"<td style='text-align:right;padding:6px 8px;color:#166534'>₹{total_cr:,.2f}</td>"
                        f"<td style='text-align:right;padding:6px 8px;color:#991b1b'>₹{total_dr:,.2f}</td>"
                        f"<td style='text-align:right;padding:6px 8px'>₹{running:,.2f}</td>"
                        f"</tr></tfoot>")
                st.markdown(f"""
                <table style="width:100%;border-collapse:collapse;font-size:.8rem">
                <thead><tr style="background:#1e40af;color:white">
                  <th style="padding:6px 8px">Date</th>
                  <th style="padding:6px 8px">Narration</th>
                  <th style="padding:6px 8px">Type</th>
                  <th style="padding:6px 8px">Mode</th>
                  <th style="text-align:right;padding:6px 8px">Credit ₹</th>
                  <th style="text-align:right;padding:6px 8px">Debit ₹</th>
                  <th style="text-align:right;padding:6px 8px">Balance ₹</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
                {foot}
                </table>
                """, unsafe_allow_html=True)

                # Summary cards
                net = total_cr - total_dr
                st.markdown(f"""
                <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-top:.8rem">
                  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                              padding:.7rem 1rem;flex:1;min-width:140px">
                    <div style="font-size:.7rem;color:#64748b">OPENING</div>
                    <div style="font-weight:700">₹{ob_savings:,.2f}</div>
                  </div>
                  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                              padding:.7rem 1rem;flex:1;min-width:140px">
                    <div style="font-size:.7rem;color:#64748b">TOTAL CREDITS</div>
                    <div style="font-weight:700;color:#166534">₹{total_cr:,.2f}</div>
                  </div>
                  <div style="background:#fff5f5;border:1px solid #fecaca;border-radius:8px;
                              padding:.7rem 1rem;flex:1;min-width:140px">
                    <div style="font-size:.7rem;color:#64748b">TOTAL DEBITS</div>
                    <div style="font-weight:700;color:#991b1b">₹{total_dr:,.2f}</div>
                  </div>
                  <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;
                              padding:.7rem 1rem;flex:1;min-width:140px">
                    <div style="font-size:.7rem;color:#64748b">CLOSING BALANCE</div>
                    <div style="font-weight:700;color:#1e40af">₹{running:,.2f}</div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                csv_data = _bank_csv(movements, ob_savings, bk_from, bk_to)
                st.download_button("⬇️ Download CSV",
                                   data=csv_data,
                                   file_name=f"Bank_Statement_{bk_fy}_{bk_from.strftime('%Y%m%d')}.csv",
                                   mime="text/csv")

# ═══════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────
def render_edit_void(user: str):
    """Edit/Void expense entries — called from app_accounting.py sidebar nav."""
    _css()
    fs_list   = _fund_sources()
    fest_list = _festivals()
    mh_list   = _major_heads()
    st.markdown('#### 🔧 Edit or Void an Expense')

    cur_fy = _fy(date.today())
    yr = int(cur_fy[:4])
    fy_opts = [cur_fy, f"{yr-1}-{str(yr)[2:]}"]

    ec1, ec2 = st.columns([1, 3])
    with ec1: ev_fy = st.selectbox("FY", fy_opts, key="ev_fy")
    with ec2: ev_q  = st.text_input("Search description or ID",
                                     key="ev_q", placeholder="e.g. flowers  or  42")

    if st.button("🔍 Search", key="ev_search"):
        st.session_state.ev_results = _search_expenses(ev_fy, ev_q.strip())
        st.session_state.ev_sel = None

    results_ev = st.session_state.get("ev_results")
    if results_ev is not None:
        if not results_ev:
            st.info("No entries found.")
        else:
            rows_html = ""
            for r in results_ev:
                rows_html += (f"<tr style='border-bottom:1px solid #e2e8f0'>"
                              f"<td style='padding:5px 8px'>#{r['id']}</td>"
                              f"<td style='padding:5px 8px'>{r['txn_date'].strftime('%d %b %Y')}</td>"
                              f"<td style='padding:5px 8px'>{r['fund_code']}</td>"
                              f"<td style='padding:5px 8px'>{r['mh_code']}</td>"
                              f"<td style='text-align:right;padding:5px 8px'>₹{float(r['amount']):,.2f}</td>"
                              f"<td style='padding:5px 8px'>{(r.get('description') or '')[:40]}</td>"
                              f"</tr>")
            st.markdown(f"""
            <table style="width:100%;border-collapse:collapse;font-size:.8rem">
            <thead><tr style="background:#1e40af;color:white">
              <th style="padding:6px 8px">ID</th><th style="padding:6px 8px">Date</th>
              <th style="padding:6px 8px">Fund</th><th style="padding:6px 8px">Head</th>
              <th style="text-align:right;padding:6px 8px">Amount</th>
              <th style="padding:6px 8px">Description</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
            </table>
            """, unsafe_allow_html=True)
            st.caption(f"{len(results_ev)} entries found")

            id_label = {
                r["id"]: f"#{r['id']} · {r['txn_date'].strftime('%d %b %Y')} · "
                         f"{r['fund_code']} · ₹{float(r['amount']):,.0f}"
                for r in results_ev
            }
            sel_id = st.selectbox("Select entry to edit / void",
                options=[None] + list(id_label.keys()),
                format_func=lambda x: "— pick a row —" if x is None else id_label[x],
                key="ev_sel")

            if sel_id:
                sel = next(r for r in results_ev if r["id"] == sel_id)
                st.markdown("---")
                st.markdown(f"**Editing #{sel['id']}** &nbsp;·&nbsp; entered by `{sel['entered_by']}`")
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
                        fs_opts_e = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
                        fs_keys_e = list(fs_opts_e.keys())
                        e_fs = st.selectbox("Fund", fs_keys_e,
                            index=fs_keys_e.index(sel["fund_source_id"])
                                  if sel["fund_source_id"] in fs_keys_e else 0,
                            format_func=lambda x: fs_opts_e[x])

                    fe4, fe5 = st.columns([2, 1])
                    with fe4:
                        mh_opts_e = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
                        mh_keys_e = list(mh_opts_e.keys())
                        e_mh = st.selectbox("Head", mh_keys_e,
                            index=mh_keys_e.index(sel["major_head_id"])
                                  if sel["major_head_id"] in mh_keys_e else 0,
                            format_func=lambda x: mh_opts_e[x])
                    with fe5:
                        e_amt = st.number_input("Amount", min_value=1.0,
                            value=float(sel["amount"]), step=50.0, format="%.2f")

                    ff_e = [f for f in fest_list if f["fund_source_id"] == e_fs]
                    fo_e = {None: "— General —"} | {f["id"]: f["name"] for f in ff_e}
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
                    with b1: do_save = st.form_submit_button("💾 Save Changes", type="primary")
                    with b2: do_void = st.form_submit_button("🗑️ Delete", type="secondary")

                if do_save:
                    try:
                        _update_expense(sel_id, {
                            "txn_date": e_date, "fund_source_id": e_fs,
                            "festival_id": e_fest, "major_head_id": e_mh,
                            "amount": float(e_amt), "payment_mode": e_mode,
                            "cheque_no": e_chq, "description": e_desc, "paid_to": e_paid
                        })
                        st.success(f"✅ Entry #{sel_id} updated.")
                        st.session_state.ev_results = None
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Save failed: {ex}")

                if do_void:
                    try:
                        _void_expense(sel_id)
                        st.success(f"✅ Entry #{sel_id} deleted.")
                        st.session_state.ev_results = None
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Delete failed: {ex}")
