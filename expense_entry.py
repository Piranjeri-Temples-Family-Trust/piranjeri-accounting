# expense_entry.py — Piranjeri Temples Trust Accounting v2
# Tabs: New Expense | Manikandan A/C | Import Excel | Standing Amounts | Recent Entries

import streamlit as st
import pg8000.dbapi as _pg
from urllib.parse import urlparse, unquote
from datetime import date
from contextlib import contextmanager


# ── DB ─────────────────────────────────────────────────────────────────────────

def _connect():
    dsn = st.secrets["neon"]["dsn"]
    u = urlparse(dsn)
    return _pg.connect(
        host=u.hostname,
        database=u.path.lstrip("/"),
        user=unquote(u.username or ""),
        password=unquote(u.password or ""),
        port=u.port or 5432,
        ssl_context=True,
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
    """Return all rows as list of dicts."""
    if not cur.description:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def _row(cur):
    """Return one row as dict (or None)."""
    if not cur.description:
        return None
    row = cur.fetchone()
    return None if row is None else dict(zip([d[0] for d in cur.description], row))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fy(d: date) -> str:
    return f"{d.year}-{str(d.year+1)[2:]}" if d.month >= 4 else f"{d.year-1}-{str(d.year)[2:]}"

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

@st.cache_data(ttl=300)
def _standing():
    with _cursor() as c:
        c.execute("""
            SELECT sa.major_head_id,sa.festival_id,sa.description,sa.default_amount,sa.notes,
                   mh.code mh_code,mh.name mh_name,f.name festival_name
            FROM standing_amounts sa
            JOIN major_heads mh ON mh.id=sa.major_head_id
            LEFT JOIN festivals f ON f.id=sa.festival_id
            WHERE sa.is_active ORDER BY mh.code,sa.description
        """)
        return _rows(c)

def _recent(limit=20):
    with _cursor() as c:
        c.execute("""
            SELECT et.id,et.txn_date,et.amount,et.payment_mode,et.description,et.paid_to,
                   mh.code mh_code,mh.name mh_name,fs.code fund_code,fv.name festival_name,et.entered_by
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id=et.major_head_id
            JOIN fund_sources fs ON fs.id=et.fund_source_id
            LEFT JOIN festivals fv ON fv.id=et.festival_id
            ORDER BY et.created_at DESC LIMIT %s
        """, (limit,))
        return _rows(c)

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

# ── Priest float helpers ───────────────────────────────────────────────────────

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

def _priest_ledger(fy_str, limit=30):
    with _cursor() as c:
        c.execute("""
            SELECT pf.id,pf.txn_date,pf.txn_type,pf.amount,pf.description,
                   pf.payment_mode,pf.cheque_no,
                   mh.code mh_code,mh.name mh_name,
                   fs.code fund_code
            FROM priest_float pf
            LEFT JOIN major_heads mh ON mh.id=pf.major_head_id
            LEFT JOIN fund_sources fs ON fs.id=pf.fund_source_id
            WHERE pf.fy=%s ORDER BY pf.txn_date DESC,pf.id DESC LIMIT %s
        """, (fy_str, limit))
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

# ── Excel import helpers ───────────────────────────────────────────────────────

# Fund column → (fund_source_code, major_head_code or None, festival_code or None)
FUND_COL_MAP = {
    "NPK":        ("NPK",    None,   "NPK_DAILY"),
    "PRO":        ("PRO",    None,   "PRO"),
    "PANGUNI":    ("PANGUNI",None,   "PANGUNI"),
    "AADI_POORAM":("NPK",   None,   "AADI_POORAM"),
    "GSS":        ("GSS",   None,   "GSS"),
    "VARU":       ("VARU",  None,   "VARU"),
    "RENOVAT":    ("RENOV", "E-18", "RENOV"),
    "BK_CHGS":    ("NPK",  "E-15",  None),
    "AUDIT":      ("NPK",  "E-16",  None),
}

KEYWORD_HEAD = [
    (["flower","garland","malli","kayathar","nadarajan"],               "E-01"),
    (["abhishekam material","subramaniapill","coconut","lemon","betel",
      "panchamirtham","vessel","pooja item"],                           "E-02"),
    (["milk"],                                                          "E-03"),
    (["kolam"],                                                         "E-04"),
    (["devi pooja","karuppan","monthly pooja","pooja expense"],         "E-05"),
    (["sambavanai","vadhyar","dakshina","manikandan","govindan",
      "sankararaman","hari team","sriram","srinivasan","raghu"],        "E-06"),
    (["watchman","security salary"],                                    "E-07"),
    (["prasadam","catering","food","plate","cup","annadhanam",
      "lunch","tiffin","banana thaar","tender coconut"],                "E-08"),
    (["vasthram","vasthra","silk","padmavilas"],                        "E-09"),
    (["nadaswaram","music","sangu","melam"],                            "E-10"),
    (["cleaning","palavesam"],                                          "E-11"),
    (["electricity","eb charge","cctv","jio","electrical"],             "E-12"),
    (["repair","damaram","asari","maintenance","transport","lorry",
      "sastha temple"],                                                 "E-13"),
    (["envelope","postage","speed post","stationery","zerox",
      "printing","scanning","paper"],                                   "E-14"),
    (["bank charge","sms charge","cheque book","bank fee"],             "E-15"),
    (["audit fee"],                                                     "E-16"),
    (["furniture","chair","equipment"],                                 "E-17"),
    (["renovation","cctv repair","cc tv"],                              "E-13"),
]

def _guess_head(text: str) -> str | None:
    t = text.lower()
    for keywords, code in KEYWORD_HEAD:
        if any(k in t for k in keywords):
            return code
    return None

def _parse_excel(file, fs_lookup: dict, mh_lookup: dict, fest_lookup: dict) -> tuple:
    """
    Returns (rows: list[dict], skipped: list[str], advances: list[dict])
    rows     = expense rows ready for import
    skipped  = description of rows we couldn't classify
    advances = Manikandan advance rows
    """
    import pandas as pd

    df = pd.read_excel(file, sheet_name="EXP", header=8, engine="openpyxl")
    # Trim to expected columns
    col_names = ["day","month","year","particulars","chq_no","dr","cr","balance",
                 "bank","cash","NPK","PRO","PANGUNI","AADI_POORAM","GSS","VARU",
                 "RENOVAT","BK_CHGS","AUDIT","ADVANCES"]
    df = df.iloc[:, :len(col_names)]
    df.columns = col_names[:df.shape[1]]

    rows, skipped, advances = [], [], []
    last_day = last_month = last_year = None

    for _, row in df.iterrows():
        import math

        def val(col):
            v = row.get(col)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
            return v

        day = val("day"); month = val("month"); year = val("year")
        if day is not None: last_day = int(day)
        if month is not None: last_month = int(month)
        if year is not None: last_year = int(year)

        if last_day is None or last_month is None or last_year is None:
            continue

        particulars = str(val("particulars") or "").strip()
        if not particulars or particulars.upper() in ["DATE","CASH BALANCE B/FD",""]:
            continue

        try:
            txn_date = date(last_year, last_month, last_day)
        except ValueError:
            skipped.append(f"{particulars} — invalid date {last_day}/{last_month}/{last_year}")
            continue

        fy_str = _fy(txn_date)
        dr = val("dr")
        cr = val("cr")
        chq_no = val("chq_no")
        is_bank = val("bank") not in (None,)

        # ── CR rows = money received (Manikandan advance or donor receipt) ──
        if cr and not dr:
            if any(k in particulars.lower() for k in ["manikandan","priest","advance"]):
                mode = "CHEQUE" if chq_no else ("BANK_TRANSFER" if is_bank else "CASH")
                advances.append({
                    "txn_date": txn_date, "fy": fy_str,
                    "txn_type": "ADVANCE", "amount": float(cr),
                    "major_head_id": None, "fund_source_id": None, "festival_id": None,
                    "description": particulars,
                    "payment_mode": mode,
                    "cheque_no": str(int(chq_no)) if chq_no else None,
                    "utr_ref_no": None,
                })
            # else: donor receipts / bank interest — skip
            continue

        if not dr:
            continue  # no expense amount

        dr_amt = float(dr)

        # Skip ADVANCES FROM TRUSTEE column entries (liability, not expense)
        if val("ADVANCES") and not any([val(c) for c in
            ["NPK","PRO","PANGUNI","AADI_POORAM","GSS","VARU","RENOVAT","BK_CHGS","AUDIT"]]):
            skipped.append(f"{txn_date} · {particulars} · ₹{dr_amt:,.0f} — Trustee advance (skip)")
            continue

        # ── Determine fund source from column ──
        fund_col = None
        for col in ["NPK","PRO","PANGUNI","AADI_POORAM","GSS","VARU","RENOVAT","BK_CHGS","AUDIT"]:
            if val(col):
                fund_col = col
                break

        if not fund_col:
            skipped.append(f"{txn_date} · {particulars} · ₹{dr_amt:,.0f} — no fund column")
            continue

        fs_code, mh_code_hint, fest_code = FUND_COL_MAP.get(fund_col, (None, None, None))
        fs_id = fs_lookup.get(fs_code)
        fest_id = fest_lookup.get(fest_code)

        # ── Determine major head ──
        if mh_code_hint:
            mh_code = mh_code_hint
        else:
            mh_code = _guess_head(particulars)

        mh_id = mh_lookup.get(mh_code) if mh_code else None

        # ── Payment mode ──
        if chq_no:
            mode = "CHEQUE"
        elif val("bank"):
            mode = "BANK_TRANSFER"
        else:
            mode = "CASH"

        rows.append({
            "txn_date": txn_date, "fy": fy_str,
            "fund_source_id": fs_id, "festival_id": fest_id,
            "major_head_id": mh_id,
            "amount": dr_amt,
            "payment_mode": mode,
            "cheque_no": str(int(chq_no)) if chq_no else None,
            "utr_ref_no": None,
            "description": particulars[:50],
            "paid_to": None,
            "_fund_code": fs_code,
            "_mh_code": mh_code,
            "_fest_code": fest_code,
            "_needs_review": (mh_id is None or fs_id is None),
        })

    return rows, skipped, advances

def _bulk_insert_expenses(rows: list, user: str) -> int:
    count = 0
    with _cursor() as c:
        for r in rows:
            if r.get("_needs_review"):
                continue
            c.execute("""
                INSERT INTO expense_transactions
                  (txn_date,fy,fund_source_id,festival_id,major_head_id,amount,
                   payment_mode,cheque_no,utr_ref_no,description,paid_to,entered_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (r["txn_date"],r["fy"],r["fund_source_id"],r["festival_id"],
                  r["major_head_id"],r["amount"],r["payment_mode"],
                  r["cheque_no"],r["utr_ref_no"],r["description"],r["paid_to"],user))
            count += 1
    return count

# ── Receipts (income) import helpers ──────────────────────────────────────────

# RECEIPTS sheet fund column → (fund_source_code, festival_code, income_type)
RECEIPT_FUND_COLS = [
    ("NPK",    "NPK_DAILY",    "DONATION"),   # col index 9
    ("PRO",    "PRO",          "DONATION"),   # 10
    ("NPK",    "AADI_POORAM",  "DONATION"),   # 11  (AADI PURAM column)
    ("GSS",    "GSS",          "DONATION"),   # 12
    ("VARU",   "VARU",         "DONATION"),   # 13
    ("PANGUNI","PANGUNI",      "DONATION"),   # 14  (PANGU column)
    ("RENOV",  "RENOV",        "DONATION"),   # 15  (RENO column)
    ("NPK",    None,           "INTEREST"),   # 16  (BANK INT)
    (None,     None,           "OTHER"),      # 17  (OTHERS)
]

def _parse_receipts_excel(file, fs_by_code: dict, fest_by_code: dict) -> tuple:
    """Returns (rows, skipped) for the RECEIPTS sheet."""
    import pandas as pd, math

    df = pd.read_excel(file, sheet_name="RECEIPTS", header=10, engine="openpyxl")
    col_names = ["book_no","rec_no","day","month","year","name",
                 "amount","bank","cash",
                 "NPK","PRADO","AADI_PURAM","GSS","VARU","PANGU","RENO",
                 "BANK_INT","OTHERS"]
    df = df.iloc[:, :len(col_names)]
    df.columns = col_names[:df.shape[1]]

    FUND_COLS = ["NPK","PRADO","AADI_PURAM","GSS","VARU","PANGU","RENO","BANK_INT","OTHERS"]

    rows, skipped = [], []
    last_book = None

    for _, row in df.iterrows():
        def val(col):
            v = row.get(col)
            return None if (v is None or (isinstance(v, float) and math.isnan(v))) else v

        if val("book_no"): last_book = int(val("book_no"))

        name = str(val("name") or "").strip()
        if not name or name.upper() in ("NAME","CANCELLED",""):
            continue

        rec_no = val("rec_no")
        day = val("day"); month = val("month"); year = val("year")
        if not all([day, month, year]):
            skipped.append(f"Rec#{rec_no} · {name} — missing date")
            continue

        try:
            txn_date = date(int(year), int(month), int(day))
        except ValueError:
            skipped.append(f"Rec#{rec_no} · {name} — bad date {day}/{month}/{year}")
            continue

        fy_str  = _fy(txn_date)
        total   = float(val("amount") or 0)
        bank_a  = float(val("bank")   or 0)
        cash_a  = float(val("cash")   or 0)

        if total <= 0:
            continue

        mode = "BOTH" if bank_a > 0 and cash_a > 0 else ("BANK" if bank_a > 0 else "CASH")

        any_fund = False
        for i, col in enumerate(FUND_COLS):
            col_amt = float(val(col) or 0)
            if col_amt <= 0:
                continue
            any_fund = True
            fs_code, fest_code, inc_type = RECEIPT_FUND_COLS[i]
            # pro-rate bank/cash split when amounts split across funds
            ratio = col_amt / total if total else 1
            rows.append({
                "txn_date":       txn_date,
                "fy":             fy_str,
                "book_no":        last_book,
                "receipt_no":     int(rec_no) if rec_no else None,
                "donor_name":     name[:80],
                "total_amount":   col_amt,
                "bank_amount":    round(bank_a * ratio, 2),
                "cash_amount":    round(cash_a * ratio, 2),
                "payment_mode":   mode,
                "fund_source_id": fs_by_code.get(fs_code),
                "festival_id":    fest_by_code.get(fest_code) if fest_code else None,
                "income_type":    inc_type,
                "_fund_code":     fs_code or "—",
                "_fest_code":     fest_code or "—",
            })

        if not any_fund:
            skipped.append(f"Rec#{rec_no} · {name} · ₹{total:,.0f} — no fund column")

    return rows, skipped


def _bulk_insert_income(rows: list, user: str) -> int:
    count = 0
    with _cursor() as c:
        for r in rows:
            c.execute("""
                INSERT INTO income_transactions
                  (txn_date,fy,book_no,receipt_no,donor_name,
                   total_amount,bank_amount,cash_amount,payment_mode,
                   fund_source_id,festival_id,income_type,entered_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (r["txn_date"],r["fy"],r["book_no"],r["receipt_no"],r["donor_name"],
                  r["total_amount"],r["bank_amount"],r["cash_amount"],r["payment_mode"],
                  r["fund_source_id"],r["festival_id"],r["income_type"],user))
            count += 1
    return count


def _bulk_insert_advances(advances: list, user: str) -> int:
    count = 0
    with _cursor() as c:
        for a in advances:
            c.execute("""
                INSERT INTO priest_float
                  (txn_date,fy,txn_type,amount,major_head_id,fund_source_id,festival_id,
                   description,payment_mode,cheque_no,utr_ref_no,entered_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (a["txn_date"],a["fy"],a["txn_type"],a["amount"],
                  a["major_head_id"],a["fund_source_id"],a["festival_id"],
                  a["description"],a["payment_mode"],a["cheque_no"],a["utr_ref_no"],user))
            count += 1
    return count


# ── Ledger helpers ────────────────────────────────────────────────────────────

def _ledger_fund_summary(fy_str: str) -> list:
    """Income vs Expenses vs Balance per fund source."""
    with _cursor() as c:
        c.execute("""
            SELECT fs.code fund, fs.name fund_name,
                   COALESCE(SUM(i.total_amount),0) income,
                   0::numeric expenses
            FROM fund_sources fs
            LEFT JOIN income_transactions i ON i.fund_source_id=fs.id AND i.fy=%s
            GROUP BY fs.id, fs.code, fs.name
            UNION ALL
            SELECT fs.code, fs.name,
                   0, COALESCE(SUM(e.amount),0)
            FROM fund_sources fs
            LEFT JOIN expense_transactions e ON e.fund_source_id=fs.id AND e.fy=%s
            GROUP BY fs.id, fs.code, fs.name
            ORDER BY 1
        """, (fy_str, fy_str))
        raw = _rows(c)
    # Aggregate
    agg = {}
    for r in raw:
        k = r["fund"]
        if k not in agg:
            agg[k] = {"fund": k, "fund_name": r["fund_name"], "income": 0.0, "expenses": 0.0}
        agg[k]["income"]   += float(r["income"])
        agg[k]["expenses"] += float(r["expenses"])
    result = sorted(agg.values(), key=lambda x: x["fund"])
    for r in result:
        r["balance"] = r["income"] - r["expenses"]
    return result

def _ledger_festival_summary(fy_str: str) -> list:
    """Income vs Expenses vs Balance per festival."""
    with _cursor() as c:
        c.execute("""
            SELECT COALESCE(fv.name,'General / No Festival') festival,
                   COALESCE(SUM(i.total_amount),0) income,
                   0::numeric expenses
            FROM festivals fv
            LEFT JOIN income_transactions i ON i.festival_id=fv.id AND i.fy=%s
            GROUP BY fv.id, fv.name
            UNION ALL
            SELECT COALESCE(fv.name,'General / No Festival'),
                   0, COALESCE(SUM(e.amount),0)
            FROM festivals fv
            LEFT JOIN expense_transactions e ON e.festival_id=fv.id AND e.fy=%s
            GROUP BY fv.id, fv.name
            UNION ALL
            SELECT 'General / No Festival',
                   COALESCE(SUM(i.total_amount),0), 0
            FROM income_transactions i WHERE i.festival_id IS NULL AND i.fy=%s
            UNION ALL
            SELECT 'General / No Festival',
                   0, COALESCE(SUM(e.amount),0)
            FROM expense_transactions e WHERE e.festival_id IS NULL AND e.fy=%s
            ORDER BY 1
        """, (fy_str, fy_str, fy_str, fy_str))
        raw = _rows(c)
    agg = {}
    for r in raw:
        k = r["festival"]
        if k not in agg:
            agg[k] = {"festival": k, "income": 0.0, "expenses": 0.0}
        agg[k]["income"]   += float(r["income"])
        agg[k]["expenses"] += float(r["expenses"])
    result = sorted(agg.values(), key=lambda x: x["festival"])
    for r in result:
        r["balance"] = r["income"] - r["expenses"]
    return [r for r in result if r["income"] > 0 or r["expenses"] > 0]

def _ledger_cashbook(fy_str: str, date_from=None, date_to=None, fund_id=None) -> list:
    """All transactions (income + expenses) in date order."""
    params_i = [fy_str]
    params_e = [fy_str]
    where_i = where_e = ""
    if date_from:
        where_i += " AND i.txn_date >= %s"; params_i.append(date_from)
        where_e += " AND e.txn_date >= %s"; params_e.append(date_from)
    if date_to:
        where_i += " AND i.txn_date <= %s"; params_i.append(date_to)
        where_e += " AND e.txn_date <= %s"; params_e.append(date_to)
    if fund_id:
        where_i += " AND i.fund_source_id = %s"; params_i.append(fund_id)
        where_e += " AND e.fund_source_id = %s"; params_e.append(fund_id)

    sql = f"""
        SELECT i.txn_date, 'INCOME' txn_type,
               i.donor_name description, NULL paid_to,
               i.total_amount amount, 0::numeric expense,
               fs.code fund_code, COALESCE(fv.name,'') festival,
               i.income_type sub_type, i.payment_mode
        FROM income_transactions i
        JOIN fund_sources fs ON fs.id=i.fund_source_id
        LEFT JOIN festivals fv ON fv.id=i.festival_id
        WHERE i.fy=%s {where_i}
        UNION ALL
        SELECT e.txn_date, 'EXPENSE',
               COALESCE(e.description,''), e.paid_to,
               0, e.amount,
               fs.code, COALESCE(fv.name,''),
               mh.code, e.payment_mode
        FROM expense_transactions e
        JOIN fund_sources fs ON fs.id=e.fund_source_id
        JOIN major_heads mh ON mh.id=e.major_head_id
        LEFT JOIN festivals fv ON fv.id=e.festival_id
        WHERE e.fy=%s {where_e}
        ORDER BY txn_date, txn_type
    """
    with _cursor() as c:
        c.execute(sql, params_i + params_e)
        return _rows(c)


def _ledger_fund_transactions(fy_str: str, fund_code: str) -> list:
    """All transactions (income + expense) for one fund, with unique IDs."""
    with _cursor() as c:
        c.execute("""
            SELECT 'EXP-'||e.id::text txn_id, e.txn_date, 'EXPENSE' txn_type,
                   mh.code||' — '||mh.name head,
                   COALESCE(fv.name,'General') festival,
                   COALESCE(e.description,'') description,
                   COALESCE(e.paid_to,'') paid_to,
                   e.payment_mode,
                   0::numeric income, e.amount expense
            FROM expense_transactions e
            JOIN fund_sources fs ON fs.id=e.fund_source_id
            JOIN major_heads mh ON mh.id=e.major_head_id
            LEFT JOIN festivals fv ON fv.id=e.festival_id
            WHERE e.fy=%s AND fs.code=%s
            UNION ALL
            SELECT 'INC-'||i.id::text, i.txn_date, 'INCOME',
                   i.income_type, COALESCE(fv.name,'General'),
                   COALESCE(i.donor_name,''), '', i.payment_mode,
                   i.total_amount, 0
            FROM income_transactions i
            JOIN fund_sources fs ON fs.id=i.fund_source_id
            LEFT JOIN festivals fv ON fv.id=i.festival_id
            WHERE i.fy=%s AND fs.code=%s
            ORDER BY txn_date, txn_type DESC
        """, (fy_str, fund_code, fy_str, fund_code))
        return _rows(c)

def _ledger_festival_transactions(fy_str: str, festival_name: str) -> list:
    """All transactions for one festival, with unique IDs."""
    if festival_name == "General / No Festival":
        where_e = "e.festival_id IS NULL"
        where_i = "i.festival_id IS NULL"
        p_e = [fy_str]
        p_i = [fy_str]
    else:
        where_e = "fv.name=%s"
        where_i = "fv.name=%s"
        p_e = [fy_str, festival_name]
        p_i = [fy_str, festival_name]
    sql = f"""
        SELECT 'EXP-'||e.id::text txn_id, e.txn_date, 'EXPENSE' txn_type,
               fs.code fund,
               mh.code||' — '||mh.name head,
               COALESCE(e.description,'') description,
               COALESCE(e.paid_to,'') paid_to,
               e.payment_mode,
               0::numeric income, e.amount expense
        FROM expense_transactions e
        JOIN fund_sources fs ON fs.id=e.fund_source_id
        JOIN major_heads mh ON mh.id=e.major_head_id
        LEFT JOIN festivals fv ON fv.id=e.festival_id
        WHERE e.fy=%s AND {where_e}
        UNION ALL
        SELECT 'INC-'||i.id::text, i.txn_date, 'INCOME',
               fs.code, i.income_type,
               COALESCE(i.donor_name,''), '', i.payment_mode,
               i.total_amount, 0
        FROM income_transactions i
        JOIN fund_sources fs ON fs.id=i.fund_source_id
        LEFT JOIN festivals fv ON fv.id=i.festival_id
        WHERE i.fy=%s AND {where_i}
        ORDER BY txn_date, txn_type DESC
    """
    with _cursor() as c:
        c.execute(sql, p_e + p_i)
        return _rows(c)

# ── Edit / Void helpers ────────────────────────────────────────────────────────

def _search_expenses(fy_str: str, q: str = "", limit: int = 100) -> list:
    with _cursor() as c:
        c.execute("""
            SELECT et.id, et.txn_date, et.amount, et.payment_mode,
                   et.description, et.paid_to, et.cheque_no, et.utr_ref_no,
                   et.fund_source_id, et.festival_id, et.major_head_id,
                   mh.code mh_code, mh.name mh_name,
                   fs.code fund_code, fv.name festival_name,
                   et.entered_by, et.fy
            FROM expense_transactions et
            JOIN major_heads mh ON mh.id=et.major_head_id
            JOIN fund_sources fs ON fs.id=et.fund_source_id
            LEFT JOIN festivals fv ON fv.id=et.festival_id
            WHERE et.fy=%s
              AND (%s='' OR et.description ILIKE %s OR et.paid_to ILIKE %s
                         OR CAST(et.id AS TEXT)=%s OR et.cheque_no=%s)
            ORDER BY et.txn_date DESC, et.id DESC LIMIT %s
        """, (fy_str, q, f"%{q}%", f"%{q}%", q, q, limit))
        return _rows(c)

def _update_expense(txn_id: int, upd: dict):
    with _cursor() as c:
        c.execute("""
            UPDATE expense_transactions SET
              txn_date=%s, fund_source_id=%s, festival_id=%s, major_head_id=%s,
              amount=%s, payment_mode=%s, cheque_no=%s, utr_ref_no=%s,
              description=%s, paid_to=%s
            WHERE id=%s
        """, (upd["txn_date"], upd["fund_source_id"], upd["festival_id"],
              upd["major_head_id"], upd["amount"], upd["payment_mode"],
              upd["cheque_no"], upd["utr_ref_no"],
              upd["description"], upd["paid_to"], txn_id))

def _void_expense(txn_id: int):
    with _cursor() as c:
        c.execute("DELETE FROM expense_transactions WHERE id=%s", (txn_id,))


# ── CSS ────────────────────────────────────────────────────────────────────────

def _css():
    st.markdown("""<style>
    div[data-testid="stForm"] label{font-size:.78rem!important;font-weight:600!important;color:#475569!important}
    .hint-box{background:#f0fdf4;border-left:3px solid #22c55e;border-radius:4px;
              padding:.4rem .7rem;font-size:.78rem;color:#166534;margin-top:1.5rem}
    .balance-card{background:#1e40af;color:white;border-radius:10px;padding:1rem 1.4rem;
                  margin-bottom:1rem;display:flex;justify-content:space-between;align-items:center}
    .bal-num{font-size:1.6rem;font-weight:700}
    .bal-label{font-size:.75rem;opacity:.8}
    .entry-row{padding:.5rem .9rem;border-radius:7px;background:#f8fafc;
               border:1px solid #e2e8f0;margin-bottom:.4rem;font-size:.82rem;
               display:flex;justify-content:space-between;align-items:center}
    .adv-row{background:#eff6ff;border-color:#bfdbfe}
    .exp-row{background:#f8fafc;border-color:#e2e8f0}
    .badge{display:inline-block;border-radius:4px;padding:1px 6px;
           font-size:.68rem;font-weight:600;margin-left:4px}
    .badge-adv{background:#dbeafe;color:#1d4ed8}
    .badge-exp{background:#dcfce7;color:#15803d}
    .badge-warn{background:#fef3c7;color:#92400e}
    div[data-testid="stForm"] .stFormSubmitButton button{
        background:#1e40af!important;color:white!important;border:none!important;
        border-radius:6px!important;font-weight:600!important;font-size:.85rem!important}
    </style>""", unsafe_allow_html=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def render_expense_entry(user: str):
    _css()

    fs_list   = _fund_sources()
    fest_list = _festivals()
    mh_list   = _major_heads()
    sa_list   = _standing()

    # Lookup dicts
    fs_by_id   = {f["id"]: f for f in fs_list}
    fs_by_code = {f["code"]: f["id"] for f in fs_list}
    mh_by_id   = {m["id"]: m for m in mh_list}
    mh_by_code = {m["code"]: m["id"] for m in mh_list}
    fest_by_id   = {f["id"]: f for f in fest_list}
    fest_by_code = {f["code"]: f["id"] for f in fest_list}

    tabs = st.tabs(["✏️ New Expense","👤 Manikandan A/C","📥 Import Excel","📌 Standing Amts","🕐 Recent","📒 Ledger","🔧 Edit/Void"])

    # ═══════════════════════════════════════════════════════════
    # TAB 1 — New Expense
    # ═══════════════════════════════════════════════════════════
    with tabs[0]:
        # ── Prefill amount from hint-button click ────────────────
        if "_pf_amount" in st.session_state:
            st.session_state["ne_amount"] = float(st.session_state.pop("_pf_amount"))

        st.markdown("#### 🧾 Record Expense")

        # Row 1 — Date / Mode / Fund / Festival
        c1,c2,c3,c4 = st.columns([1.1,0.9,1.4,1.4])
        with c1:
            txn_date = st.date_input("Date", value=date.today(), max_value=date.today(), key="ne_date")
            st.caption(f"FY {_fy(txn_date)}")
        with c2:
            mode = st.selectbox("Mode", ["CASH","CHEQUE","BANK_TRANSFER"],
                format_func=lambda x:{"CASH":"Cash","CHEQUE":"Cheque","BANK_TRANSFER":"Bank Tfr"}[x],
                key="ne_mode")
        with c3:
            fs_opts = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
            fs_id = st.selectbox("Fund", list(fs_opts), format_func=lambda x: fs_opts[x], key="ne_fs")
        with c4:
            ff = [f for f in fest_list if f["fund_source_id"]==fs_id]
            fo = {None:"— General —"} | {f["id"]: f["name"] for f in ff}
            fest_id = st.selectbox("Festival", list(fo), format_func=lambda x: fo[x], key="ne_fest")

        # Row 2 — Head / Amount
        c5,c6 = st.columns([2,1])
        with c5:
            mh_opts = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
            mh_id = st.selectbox("Head", list(mh_opts), format_func=lambda x: mh_opts[x], key="ne_mh")
        with c6:
            amount = st.number_input("Amount (₹)", min_value=1.0, max_value=500000.0,
                step=50.0, format="%.2f", key="ne_amount")

        # Row 3 — Clickable standing-amount hints (live, updates on every Head change)
        hint_matches = [s for s in sa_list
                        if s["major_head_id"] == mh_id
                        and (fest_id is None or s["festival_id"] is None
                             or s["festival_id"] == fest_id)]
        if hint_matches:
            st.markdown('<p style="font-size:.78rem;color:#475569;margin:4px 0 2px">📌 Usual amounts — click to apply</p>',
                        unsafe_allow_html=True)
            hcols = st.columns(min(len(hint_matches), 4))
            for i, s in enumerate(hint_matches[:4]):
                with hcols[i]:
                    if st.button(f"₹{s['default_amount']:,.0f}  {s['description']}",
                                 key=f"sa_h_{s['major_head_id']}_{s.get('festival_id','g')}_{i}",
                                 ):
                        st.session_state["_pf_amount"] = float(s["default_amount"])
                        st.rerun()

        # Row 4 — Cheque / Description / Paid To
        c8,c9,c10 = st.columns([1,1.5,1.5])
        cheque_no = utr = None
        with c8:
            if mode=="CHEQUE":
                cheque_no = st.text_input("Cheque No.", max_chars=30, key="ne_chq") or None
            elif mode=="BANK_TRANSFER":
                utr = st.text_input("UTR Ref.", max_chars=40, key="ne_utr") or None
            else:
                st.empty()
        with c9:
            desc    = st.text_input("Description", max_chars=50, placeholder="e.g. April flowers NPK",  key="ne_desc") or None
        with c10:
            paid_to = st.text_input("Paid To",     max_chars=50, placeholder="e.g. Subramania Pillai", key="ne_paid") or None

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Expense", type="primary", key="ne_save"):
            errs = []
            if mode=="CHEQUE" and not cheque_no: errs.append("Cheque number required.")
            if mode=="BANK_TRANSFER" and not utr: errs.append("UTR required.")
            if errs:
                for e in errs: st.error(e)
            else:
                try:
                    nid = _save_expense({"txn_date":txn_date,"fy":_fy(txn_date),"fund_source_id":fs_id,
                        "festival_id":fest_id,"major_head_id":mh_id,"amount":float(amount),
                        "payment_mode":mode,"cheque_no":cheque_no,"utr_ref_no":utr,
                        "description":desc,"paid_to":paid_to,"entered_by":user})
                    st.success(f"✅ Saved #{nid} · ₹{amount:,.2f} · {mh_opts[mh_id]}")
                    for k in ["ne_date","ne_mode","ne_fs","ne_fest","ne_mh",
                              "ne_amount","ne_chq","ne_utr","ne_desc","ne_paid"]:
                        st.session_state.pop(k, None)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Save failed: {ex}")

    # ═══════════════════════════════════════════════════════════
    # TAB 2 — Manikandan A/C
    # ═══════════════════════════════════════════════════════════
    with tabs[1]:
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
        except Exception:
            st.info("Run schema_patch.sql in Neon first to enable this tab.")
            st.stop()

        action = st.radio("Action", ["Issue Advance","Record Settlement"], horizontal=True)

        if action == "Issue Advance":
            with st.form("adv_form", clear_on_submit=True):
                ca,cb,cc = st.columns([1.2,1,1.2])
                with ca: adate = st.date_input("Date", value=today, max_value=today)
                with cb: amode = st.selectbox("Mode",["CHEQUE","BANK_TRANSFER"],
                    format_func=lambda x:{"CHEQUE":"Cheque","BANK_TRANSFER":"Bank Tfr"}[x])
                with cc: aamt  = st.number_input("Amount (₹)", min_value=1.0, max_value=200000.0,
                    step=500.0, format="%.2f")
                cd,ce = st.columns(2)
                with cd: achq = st.text_input("Cheque / UTR No.", max_chars=40) or None
                with ce: adesc= st.text_input("Narration", max_chars=50,
                    placeholder="e.g. Monthly advance Apr 2026") or None
                st.markdown("<br>", unsafe_allow_html=True)
                aok = st.form_submit_button("💾 Record Advance", type="primary")
            if aok:
                try:
                    nid = _save_priest({"txn_date":adate,"fy":_fy(adate),"txn_type":"ADVANCE",
                        "amount":float(aamt),"major_head_id":None,"fund_source_id":None,
                        "festival_id":None,"description":adesc,"payment_mode":amode,
                        "cheque_no":achq if amode=="CHEQUE" else None,
                        "utr_ref_no":achq if amode=="BANK_TRANSFER" else None,
                        "entered_by":user})
                    st.success(f"✅ Advance recorded #{nid} · ₹{aamt:,.2f}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed: {ex}")

        else:  # Record Settlement
            with st.form("settle_form", clear_on_submit=True):
                s1,s2,s3,s4 = st.columns([1.2,1.4,1.4,1])
                with s1: sdate = st.date_input("Date", value=today, max_value=today)
                with s2:
                    mh_opts2 = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
                    smh = st.selectbox("Head", list(mh_opts2), format_func=lambda x: mh_opts2[x])
                with s3:
                    fs_opts2 = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
                    sfs = st.selectbox("Fund", list(fs_opts2), format_func=lambda x: fs_opts2[x])
                with s4: samt = st.number_input("₹", min_value=1.0, max_value=200000.0, step=50.0, format="%.2f")
                sdesc = st.text_input("Description", max_chars=50, placeholder="e.g. Flowers Apr 2026") or None
                st.markdown("<br>", unsafe_allow_html=True)
                sok = st.form_submit_button("💾 Record Settlement", type="primary")
            if sok:
                try:
                    nid = _save_priest({"txn_date":sdate,"fy":_fy(sdate),"txn_type":"EXPENSE",
                        "amount":float(samt),"major_head_id":smh,"fund_source_id":sfs,
                        "festival_id":None,"description":sdesc,"payment_mode":None,
                        "cheque_no":None,"utr_ref_no":None,"entered_by":user})
                    st.success(f"✅ Settlement recorded #{nid} · ₹{samt:,.2f}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed: {ex}")

        # Ledger
        st.markdown("---")
        st.markdown("**Recent transactions**")
        try:
            ledger = _priest_ledger(fy_str)
            for r in ledger:
                is_adv = r["txn_type"]=="ADVANCE"
                badge  = '<span class="badge badge-adv">ADVANCE</span>' if is_adv else \
                         f'<span class="badge badge-exp">{r["mh_code"] or ""}</span>'
                desc   = r.get("description") or ""
                chq    = f" · Chq {r['cheque_no']}" if r.get("cheque_no") else ""
                sign   = "+" if is_adv else "−"
                color  = "#1d4ed8" if is_adv else "#166534"
                st.markdown(f"""
                <div class="entry-row {'adv-row' if is_adv else 'exp-row'}">
                  <div>
                    <span style="color:#64748b;font-size:.73rem">{r['txn_date'].strftime('%d %b %Y')}</span>
                    {badge}
                    <br><span style="font-weight:600;color:#1e293b">{desc}{chq}</span>
                  </div>
                  <div style="font-weight:700;color:{color};font-size:.95rem">{sign}₹{float(r['amount']):,.2f}</div>
                </div>""", unsafe_allow_html=True)
        except Exception as ex:
            st.error(f"Ledger error: {ex}")

    # ═══════════════════════════════════════════════════════════
    # TAB 3 — Import Excel
    # ═══════════════════════════════════════════════════════════
    with tabs[2]:
        st.markdown("#### 📥 Import from Excel")

        import_mode = st.radio("What to import", ["Expenses (EXP sheet)", "Receipts / Collections (RECEIPTS sheet)"],
                               horizontal=True, key="import_mode")

        uploaded = st.file_uploader("Choose .xlsx file", type=["xlsx"],
                                    key="import_xlsx")

        if uploaded:
            import pandas as pd

            # ════════════════════════════════════════════════════
            # MODE A — EXPENSES
            # ════════════════════════════════════════════════════
            if import_mode.startswith("Expenses"):
                with st.spinner("Parsing EXP sheet..."):
                    rows, skipped, advances = _parse_excel(
                        uploaded, fs_by_code, mh_by_code, fest_by_code)

                ok_rows   = [r for r in rows if not r.get("_needs_review")]
                warn_rows = [r for r in rows if r.get("_needs_review")]

                col1, col2, col3 = st.columns(3)
                col1.metric("✅ Ready to import", len(ok_rows))
                col2.metric("⚠️ Needs review",    len(warn_rows))
                col3.metric("🔵 Mani advances",   len(advances))

                if ok_rows:
                    st.markdown("**Ready rows (sample — first 20)**")
                    preview = pd.DataFrame([{
                        "Date": r["txn_date"], "Fund": r["_fund_code"],
                        "Head": r["_mh_code"] or "—", "Festival": r["_fest_code"] or "—",
                        "₹": r["amount"], "Mode": r["payment_mode"],
                        "Description": (r["description"] or "")[:40],
                    } for r in ok_rows[:20]])
                    st.dataframe(preview, hide_index=True)

                if warn_rows:
                    st.markdown("**⚠️ Rows needing manual head assignment**")
                    for i, r in enumerate(warn_rows):
                        wc1, wc2 = st.columns([3,2])
                        with wc1:
                            st.markdown(f"`{r['txn_date']}` · {r['_fund_code']} · "
                                        f"₹{r['amount']:,.0f} · {r['description']}")
                        with wc2:
                            chosen = st.selectbox(f"Head##{i}",
                                options=[None]+[m["id"] for m in mh_list],
                                format_func=lambda x: "— select —" if x is None else
                                    f"{mh_by_id[x]['code']} {mh_by_id[x]['name']}",
                                key=f"warn_mh_{i}")
                            if chosen:
                                warn_rows[i]["major_head_id"] = chosen
                                warn_rows[i]["_needs_review"] = False

                if skipped:
                    with st.expander(f"Skipped rows ({len(skipped)})"):
                        for s in skipped: st.caption(s)

                if advances:
                    st.markdown("**🔵 Manikandan advances found**")
                    adv_df = [{"Date":a["txn_date"],"₹":a["amount"],
                               "Mode":a["payment_mode"],"Ref":a["cheque_no"] or "",
                               "Description":a["description"]} for a in advances]
                    st.dataframe(adv_df, hide_index=True)

                st.markdown("---")
                bcol1, bcol2 = st.columns(2)
                with bcol1:
                    if st.button("🚀 Import Expenses", type="primary",
                                 disabled=not any(not r.get("_needs_review") for r in rows)):
                        try:
                            n = _bulk_insert_expenses(rows, user)
                            st.success(f"✅ {n} expense rows imported.")
                            st.cache_data.clear()
                        except Exception as ex:
                            st.error(f"Import failed: {ex}")
                with bcol2:
                    if advances:
                        if st.button("🔵 Import Manikandan Advances"):
                            try:
                                n = _bulk_insert_advances(advances, user)
                                st.success(f"✅ {n} advance rows imported.")
                                st.cache_data.clear()
                            except Exception as ex:
                                st.error(f"Import failed: {ex}")

            # ════════════════════════════════════════════════════
            # MODE B — RECEIPTS / COLLECTIONS
            # ════════════════════════════════════════════════════
            else:
                with st.spinner("Parsing RECEIPTS sheet..."):
                    rec_rows, rec_skipped = _parse_receipts_excel(
                        uploaded, fs_by_code, fest_by_code)

                # Summary by fund
                fund_totals = {}
                for r in rec_rows:
                    k = r["_fund_code"]
                    fund_totals[k] = fund_totals.get(k, 0) + r["total_amount"]

                grand = sum(fund_totals.values())
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("📄 Rows to import", len(rec_rows))
                mc2.metric("⏭️ Skipped",         len(rec_skipped))
                mc3.metric("💰 Total ₹",          f"{grand:,.0f}")

                # Fund-wise breakdown
                if fund_totals:
                    st.markdown("**Fund-wise breakdown**")
                    st.dataframe(pd.DataFrame([
                        {"Fund": k, "₹ Total": f"{v:,.0f}"}
                        for k, v in sorted(fund_totals.items())
                    ]), hide_index=True)

                # Preview first 30 rows
                if rec_rows:
                    st.markdown("**Preview (first 30 rows)**")
                    prev = pd.DataFrame([{
                        "Rec#":    r["receipt_no"],
                        "Date":    r["txn_date"].strftime("%d/%m/%Y"),
                        "Donor":   r["donor_name"][:35],
                        "Fund":    r["_fund_code"],
                        "Festival":r["_fest_code"],
                        "₹":       f"{r['total_amount']:,.0f}",
                        "Mode":    r["payment_mode"],
                        "Type":    r["income_type"],
                    } for r in rec_rows[:30]])
                    st.dataframe(prev, hide_index=True)

                if rec_skipped:
                    with st.expander(f"Skipped rows ({len(rec_skipped)})"):
                        for s in rec_skipped: st.caption(s)

                st.markdown("---")
                if st.button("🚀 Import Receipts", type="primary",
                             disabled=not rec_rows):
                    try:
                        n = _bulk_insert_income(rec_rows, user)
                        st.success(f"✅ {n} receipt rows imported into income_transactions.")
                        st.cache_data.clear()
                    except Exception as ex:
                        st.error(f"Import failed: {ex}")

    # ═══════════════════════════════════════════════════════════
    # TAB 4 — Standing Amounts
    # ═══════════════════════════════════════════════════════════
    with tabs[3]:
        st.caption("Default amounts for recurring expenses.")
        if not sa_list:
            st.info("No standing amounts configured.")
        else:
            by_fest: dict = {}
            for s in sa_list:
                k = s.get("festival_name") or "General"
                by_fest.setdefault(k,[]).append(s)
            for fn, items in sorted(by_fest.items()):
                with st.expander(f"**{fn}**", expanded=True):
                    import pandas as pd
                    st.dataframe(pd.DataFrame([{
                        "Head": f"{i['mh_code']} {i['mh_name']}",
                        "Item": i["description"],
                        "₹ Default": f"{i['default_amount']:,.2f}",
                        "Notes": i["notes"] or "",
                    } for i in items]), hide_index=True)

    # ═══════════════════════════════════════════════════════════
    # TAB 5 — Recent Entries
    # ═══════════════════════════════════════════════════════════
    with tabs[4]:
        try:
            entries = _recent(20)
        except Exception as ex:
            st.error(f"Could not load: {ex}"); entries = []
        if not entries:
            st.info("No entries yet.")
        for e in entries:
            icon = {"CASH":"💵","CHEQUE":"🏦","BANK_TRANSFER":"🔁"}.get(e["payment_mode"],"")
            desc = f" · {e['description']}" if e.get("description") else ""
            paid = f" → {e['paid_to']}" if e.get("paid_to") else ""
            fest = (f'<span class="badge" style="background:#e0f2fe;color:#0369a1">'
                    f'{e["festival_name"]}</span>') if e.get("festival_name") else ""
            st.markdown(f"""
            <div class="entry-row">
              <div>
                <span style="color:#64748b;font-size:.73rem">{e['txn_date'].strftime('%d %b %Y')}</span>
                &nbsp;<span style="color:#0369a1;font-size:.72rem">{e['fund_code']}</span>{fest}
                <br><span style="font-weight:600;color:#1e293b">{e['mh_code']} {e['mh_name']}</span>
                <span style="color:#64748b;font-size:.78rem">{desc}{paid}</span>
              </div>
              <div style="text-align:right">
                <span style="font-weight:700;font-size:.95rem">₹{float(e['amount']):,.2f}</span>
                <br><span style="color:#94a3b8;font-size:.72rem">{icon} {e['entered_by']}</span>
              </div>
            </div>""", unsafe_allow_html=True)

    # ═══════════════════════════════════════════════════════════
    # TAB 6 — Ledger
    # ═══════════════════════════════════════════════════════════
    with tabs[5]:
        st.markdown("#### 📒 Ledger — FY Summary & Cash Book")

        import pandas as pd

        def _show_txn_drilldown(txns: list, title: str):
            """Render a transaction drilldown table with unique IDs and major-head breakdown."""
            if not txns:
                st.info("No transactions found.")
                return
            st.markdown(f"**{title}** — {len(txns)} transactions")
            rows = []
            for r in txns:
                inc = float(r["income"])
                exp = float(r["expense"])
                rows.append({
                    "Txn ID":      r["txn_id"],
                    "Date":        r["txn_date"].strftime("%d %b %Y"),
                    "Type":        r["txn_type"],
                    "Head / Type": r["head"],
                    "Festival":    r["festival"],
                    "Description": (r.get("description") or "")[:40],
                    "Paid To":     (r.get("paid_to") or "")[:30],
                    "Mode":        r.get("payment_mode") or "",
                    "Income ₹":    f"{inc:,.2f}" if inc else "",
                    "Expense ₹":   f"{exp:,.2f}" if exp else "",
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            # Major-head expense breakdown
            exp_only = [r for r in txns if float(r["expense"]) > 0]
            if exp_only:
                st.markdown("**Expense breakdown by head:**")
                bk: dict = {}
                for r in exp_only:
                    h = r["head"]
                    bk[h] = bk.get(h, 0.0) + float(r["expense"])
                bk_rows = sorted(bk.items(), key=lambda x: -x[1])
                bk_df = pd.DataFrame([{"Head": h, "Total ₹": f"{v:,.2f}"} for h, v in bk_rows])
                st.dataframe(bk_df, hide_index=True)
                st.caption(f"Total expenses: ₹{sum(bk.values()):,.2f}")

        # FY selector
        cur_fy = _fy(date.today())
        yr = int(cur_fy[:4])
        fy_opts = [cur_fy, f"{yr-1}-{str(yr)[2:]}", f"{yr+1}-{str(yr+2)[2:]}"]
        led_fy = st.selectbox("Financial Year", fy_opts, key="led_fy")

        sub = st.radio("View", ["Fund-wise Summary","Festival-wise Summary","Cash Book"],
                       horizontal=True, key="led_view")

        # ── Fund-wise summary ───────────────────────────────────
        if sub == "Fund-wise Summary":
            try:
                rows_f = _ledger_fund_summary(led_fy)
            except Exception as ex:
                st.error(f"Error: {ex}"); rows_f = []
            if not rows_f:
                st.info("No data for this FY.")
            else:
                df_f = pd.DataFrame([{
                    "Fund":       r["fund"],
                    "Name":       r["fund_name"],
                    "Income ₹":   f"{r['income']:,.2f}",
                    "Expenses ₹": f"{r['expenses']:,.2f}",
                    "Balance ₹":  f"{r['balance']:,.2f}",
                } for r in rows_f])
                st.dataframe(df_f, hide_index=True)
                tot_inc = sum(r["income"]   for r in rows_f)
                tot_exp = sum(r["expenses"] for r in rows_f)
                bal     = tot_inc - tot_exp
                bal_color = "#166534" if bal >= 0 else "#991b1b"
                st.markdown(f"""
                <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                            padding:.8rem 1.2rem;margin-top:.5rem;display:flex;gap:2rem">
                  <div><div style="font-size:.72rem;color:#64748b">TOTAL INCOME</div>
                       <div style="font-weight:700;font-size:1.1rem">₹{tot_inc:,.2f}</div></div>
                  <div><div style="font-size:.72rem;color:#64748b">TOTAL EXPENSES</div>
                       <div style="font-weight:700;font-size:1.1rem">₹{tot_exp:,.2f}</div></div>
                  <div><div style="font-size:.72rem;color:#64748b">NET BALANCE</div>
                       <div style="font-weight:700;font-size:1.1rem;color:{bal_color}">₹{bal:,.2f}</div></div>
                </div>""", unsafe_allow_html=True)
                st.divider()
                # Drilldown
                fund_choices = ["— Select a fund to view its transactions —"] + \
                               [f"{r['fund']} — {r['fund_name']}" for r in rows_f]
                sel_f = st.selectbox("🔍 Drill into fund:", fund_choices, key="led_fund_drill")
                if sel_f != fund_choices[0]:
                    sel_code = sel_f.split(" — ")[0]
                    try:
                        drill = _ledger_fund_transactions(led_fy, sel_code)
                        _show_txn_drilldown(drill, sel_f)
                    except Exception as ex:
                        st.error(f"Error: {ex}")

        # ── Festival-wise summary ───────────────────────────────
        elif sub == "Festival-wise Summary":
            try:
                rows_fv = _ledger_festival_summary(led_fy)
            except Exception as ex:
                st.error(f"Error: {ex}"); rows_fv = []
            if not rows_fv:
                st.info("No data for this FY.")
            else:
                df_fv = pd.DataFrame([{
                    "Festival":   r["festival"],
                    "Income ₹":   f"{r['income']:,.2f}",
                    "Expenses ₹": f"{r['expenses']:,.2f}",
                    "Balance ₹":  f"{r['balance']:,.2f}",
                } for r in rows_fv])
                st.dataframe(df_fv, hide_index=True)
                st.divider()
                # Drilldown
                fest_choices = ["— Select a festival to view its transactions —"] + \
                               [r["festival"] for r in rows_fv]
                sel_fv = st.selectbox("🔍 Drill into festival:", fest_choices, key="led_fest_drill")
                if sel_fv != fest_choices[0]:
                    try:
                        drill_fv = _ledger_festival_transactions(led_fy, sel_fv)
                        _show_txn_drilldown(drill_fv, sel_fv)
                    except Exception as ex:
                        st.error(f"Error: {ex}")

        # ── Cash Book ───────────────────────────────────────────
        else:
            fc1, fc2, fc3 = st.columns([1.2, 1.2, 1.6])
            with fc1:
                cb_from = st.date_input("From", value=None, key="cb_from")
            with fc2:
                cb_to   = st.date_input("To",   value=None, key="cb_to")
            with fc3:
                fund_opts_l = {None: "All Funds"} | {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
                cb_fund = st.selectbox("Fund", list(fund_opts_l),
                                       format_func=lambda x: fund_opts_l[x], key="cb_fund")

            if st.button("\U0001f50d Load Cash Book", key="cb_load"):
                try:
                    cb_rows = _ledger_cashbook(led_fy, cb_from, cb_to, cb_fund)
                    st.session_state["cb_rows"] = cb_rows
                except Exception as ex:
                    st.error(f"Error: {ex}")

            cb_rows = st.session_state.get("cb_rows")
            if cb_rows is not None:
                if not cb_rows:
                    st.info("No transactions found.")
                else:
                    running = 0.0
                    table_rows = []
                    for r in cb_rows:
                        inc = float(r["amount"])
                        exp = float(r["expense"])
                        running += inc - exp
                        table_rows.append({
                            "Date":        r["txn_date"].strftime("%d %b %Y"),
                            "Type":        r["txn_type"],
                            "Fund":        r["fund_code"],
                            "Festival":    r["festival"],
                            "Description": r["description"][:40],
                            "Income ₹":    f"{inc:,.2f}" if inc else "",
                            "Expense ₹":   f"{exp:,.2f}" if exp else "",
                            "Balance ₹":   f"{running:,.2f}",
                        })
                    st.dataframe(pd.DataFrame(table_rows), hide_index=True)
                    st.caption(f"{len(cb_rows)} transactions | Running balance: ₹{running:,.2f}")

    # ===========================================================
    # TAB 7 -- Edit / Void
    # ===========================================================
    with tabs[6]:
        st.markdown("#### \U0001f527 Edit or Void an Expense")

        cur_fy2 = _fy(date.today())
        yr2 = int(cur_fy2[:4])
        fy_options2 = [
            cur_fy2,
            f"{yr2-1}-{str(yr2)[2:]}",
            f"{yr2+1}-{str(yr2+2)[2:]}",
        ]

        sc1, sc2 = st.columns([1, 3])
        with sc1:
            ev_fy = st.selectbox("Financial Year", fy_options2, key="ev_fy")
        with sc2:
            ev_q = st.text_input("Search description, paid-to, cheque no, or row ID",
                                 key="ev_q", placeholder="e.g. flowers  or  42")

        if st.button("\U0001f50d Search", key="ev_search"):
            st.session_state.ev_results = _search_expenses(ev_fy, ev_q.strip())
            st.session_state.ev_sel = None

        results_ev = st.session_state.get("ev_results")

        if results_ev is not None:
            if not results_ev:
                st.info("No entries found. Try a different keyword or FY.")
            else:
                import pandas as _pd2
                preview_ev = pd.DataFrame([{
                    "ID":     r["id"],
                    "Date":   r["txn_date"].strftime("%d %b %Y"),
                    "Fund":   r["fund_code"],
                    "Head":   f"{r['mh_code']} {r['mh_name']}",
                    "Rs":     f"{float(r['amount']):,.2f}",
                    "Mode":   r["payment_mode"],
                    "Desc":   (r.get("description") or "")[:40],
                    "Cheque": r.get("cheque_no") or "",
                } for r in results_ev])
                st.dataframe(preview_ev, hide_index=True)
                st.caption(f"{len(results_ev)} entries found")

                id_label = {
                    r["id"]: f"#{r['id']} · {r['txn_date'].strftime('%d %b %Y')} · "
                             f"{r['fund_code']} · ₹{float(r['amount']):,.0f}"
                             f"{' · ' + r['description'][:25] if r.get('description') else ''}"
                    for r in results_ev
                }
                sel_id = st.selectbox(
                    "Select entry to edit / void",
                    options=[None] + list(id_label.keys()),
                    format_func=lambda x: "— pick a row —" if x is None else id_label[x],
                    key="ev_sel",
                )

                if sel_id:
                    sel = next(r for r in results_ev if r["id"] == sel_id)
                    st.markdown("---")
                    st.markdown(f"**Editing #{sel['id']}** &nbsp;·&nbsp; entered by `{sel['entered_by']}`")

                    with st.form("edit_expense_form"):
                        fe1,fe2,fe3,fe4 = st.columns([1.1,0.9,1.4,1.4])
                        with fe1:
                            e_date = st.date_input("Date", value=sel["txn_date"])
                        with fe2:
                            modes = ["CASH","CHEQUE","BANK_TRANSFER"]
                            e_mode = st.selectbox(
                                "Mode", modes,
                                index=modes.index(sel["payment_mode"] or "CASH"),
                                format_func=lambda x: {"CASH":"Cash","CHEQUE":"Cheque",
                                                       "BANK_TRANSFER":"Bank Tfr"}[x])
                        with fe3:
                            fs_opts_e = {f["id"]: f"{f['code']} — {f['name']}" for f in fs_list}
                            fs_keys_e = list(fs_opts_e.keys())
                            e_fs = st.selectbox(
                                "Fund", fs_keys_e,
                                index=fs_keys_e.index(sel["fund_source_id"])
                                      if sel["fund_source_id"] in fs_keys_e else 0,
                                format_func=lambda x: fs_opts_e[x])
                        with fe4:
                            ff_e = [f for f in fest_list if f["fund_source_id"]==e_fs]
                            fo_e = {None:"— General —"} | {f["id"]: f["name"] for f in ff_e}
                            fk_e = list(fo_e.keys())
                            e_fest = st.selectbox(
                                "Festival", fk_e,
                                index=fk_e.index(sel["festival_id"])
                                      if sel["festival_id"] in fk_e else 0,
                                format_func=lambda x: fo_e[x])

                        fe5,fe6 = st.columns([2,1])
                        with fe5:
                            mh_opts_e = {m["id"]: f"{m['code']} — {m['name']}" for m in mh_list}
                            mh_keys_e = list(mh_opts_e.keys())
                            e_mh = st.selectbox(
                                "Head", mh_keys_e,
                                index=mh_keys_e.index(sel["major_head_id"])
                                      if sel["major_head_id"] in mh_keys_e else 0,
                                format_func=lambda x: mh_opts_e[x])
                        with fe6:
                            e_amt = st.number_input("Amount", min_value=1.0,
                                                    value=float(sel["amount"]),
                                                    step=50.0, format="%.2f")

                        fe7,fe8,fe9 = st.columns([1,1.5,1.5])
                        e_chq = e_utr = None
                        with fe7:
                            if e_mode == "CHEQUE":
                                e_chq = st.text_input("Cheque No.",
                                                      value=sel.get("cheque_no") or "",
                                                      max_chars=30) or None
                            elif e_mode == "BANK_TRANSFER":
                                e_utr = st.text_input("UTR Ref.",
                                                      value=sel.get("utr_ref_no") or "",
                                                      max_chars=30) or None
                        with fe8:
                            e_desc = st.text_input("Description",
                                                   value=sel.get("description") or "",
                                                   max_chars=50) or None
                        with fe9:
                            e_paid = st.text_input("Paid To",
                                                   value=sel.get("paid_to") or "",
                                                   max_chars=50) or None

                        st.markdown("<br>", unsafe_allow_html=True)
                        btn_save, btn_void = st.columns([3,1])
                        with btn_save:
                            do_save = st.form_submit_button("\U0001f4be Save Changes", type="primary")
                        with btn_void:
                            do_void = st.form_submit_button("\U0001f5d1 Void/Delete", type="secondary")

                    if do_save:
                        try:
                            _update_expense(sel_id, {
                                "txn_date": e_date, "fund_source_id": e_fs,
                                "festival_id": e_fest, "major_head_id": e_mh,
                                "amount": float(e_amt), "payment_mode": e_mode,
                                "cheque_no": e_chq, "utr_ref_no": e_utr,
                                "description": e_desc, "paid_to": e_paid,
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
