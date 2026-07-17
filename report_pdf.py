"""
report_pdf.py — PDF report generators for Piranjeri Temples Family Trust
Uses ReportLab. Each function accepts pre-fetched data (no DB calls) and returns PDF bytes.

Functions:
    trial_balance_pdf(fy, df)
    ie_statement_pdf(fy, year_end_str, data)
    balance_sheet_pdf(fy, data)
    festival_pnl_pdf(fy, rows)
"""

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Palette ───────────────────────────────────────────────────────────────────
TRUST_BLUE   = colors.HexColor("#1A3C6E")
TRUST_INDIGO = colors.HexColor("#4A5299")
LIGHT_GREY   = colors.HexColor("#F5F5F5")
MID_GREY     = colors.HexColor("#CCCCCC")
RED_C        = colors.HexColor("#CC0000")
GREEN_C      = colors.HexColor("#006600")

W, H   = A4
MARGIN = 15 * mm
IW     = W - 2 * MARGIN          # inner width


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(v):
    """Rs. 1,23,456.78  (Helvetica doesn't carry the ₹ glyph)"""
    if v is None:
        return "—"
    return f"Rs.{abs(float(v)):,.2f}"


def _p(text, size=9, bold=False, color=colors.black, align=TA_LEFT):
    style = ParagraphStyle(
        "x",
        fontSize=size,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        textColor=color,
        alignment=align,
        leading=size * 1.3,
    )
    return Paragraph(text, style)


def _header_elements(title, subtitle, fy_label):
    """Return list of flowables for the trust + report header."""
    elems = [
        _p("Piranjeri Temples Family Trust", 13, bold=True,
           color=TRUST_BLUE, align=TA_CENTER),
        Spacer(1, 2 * mm),
        _p(title, 10, bold=True, color=TRUST_INDIGO, align=TA_CENTER),
        _p(subtitle, 8.5, color=colors.grey, align=TA_CENTER),
        _p(fy_label,  8,  color=colors.grey, align=TA_CENTER),
        Spacer(1, 3 * mm),
        HRFlowable(width="100%", thickness=1.2, color=TRUST_BLUE, spaceAfter=5),
    ]
    return elems


def _build(elements):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )
    doc.build(elements)
    return buf.getvalue()


def _hdr_ts():
    return [
        ("BACKGROUND",    (0, 0), (-1, 0), TRUST_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,-1), 8.5),
        ("TOPPADDING",    (0, 0), (-1,-1), 3),
        ("BOTTOMPADDING", (0, 0), (-1,-1), 3),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 1. TRIAL BALANCE
# ══════════════════════════════════════════════════════════════════════════════

def trial_balance_pdf(fy, df):
    """
    fy  : str  e.g. '2025-26'
    df  : pandas DataFrame — columns must include:
              code, name, account_type, dr_balance, cr_balance
    Returns PDF bytes.
    """
    year_end = fy.split("-")[1]
    elems = _header_elements(
        "Trial Balance",
        f"As at 31 March 20{year_end}",
        f"Financial Year {fy}",
    )

    GROUP_LABELS = {
        "ASSET":       "Assets",
        "INCOME":      "Income",
        "EXPENDITURE": "Expenditure",
        "FUND":        "Funds",
        "LIABILITY":   "Liabilities",
    }
    GROUP_ORDER = ["ASSET", "INCOME", "EXPENDITURE", "FUND", "LIABILITY"]

    cw = [IW * 0.13, IW * 0.50, IW * 0.185, IW * 0.185]
    data = [["Code", "Account", "Debit (Rs.)", "Credit (Rs.)"]]

    total_dr = 0.0
    total_cr = 0.0
    last_g   = None

    for gtype in GROUP_ORDER:
        gdf = df[df["account_type"] == gtype]
        if gdf.empty:
            continue
        label = GROUP_LABELS.get(gtype, gtype)
        data.append([label, "", "", ""])      # group header row — tagged by empty cols 2-4
        last_g = gtype

        for _, row in gdf.iterrows():
            dr = float(row.get("dr_balance", 0) or 0)
            cr = float(row.get("cr_balance", 0) or 0)
            total_dr += dr
            total_cr += cr
            data.append([
                row["code"],
                row["name"],
                _fmt(dr) if dr > 0.005 else "",
                _fmt(cr) if cr > 0.005 else "",
            ])

    data.append(["", "TOTAL", _fmt(total_dr), _fmt(total_cr)])

    ts = TableStyle(_hdr_ts() + [
        ("ALIGN",  (0, 0), (-1,  0), "CENTER"),
        ("ALIGN",  (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN",  (0, 1), ( 1, -1), "LEFT"),
        ("GRID",   (0, 0), (-1, -1), 0.25, MID_GREY),
        ("FONTNAME",  (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, TRUST_BLUE),
        ("LINEBELOW", (0, -1), (-1, -1), 1, TRUST_BLUE),
    ])

    # Style group-header rows (identified by col-2 and col-3 being empty, col-0 non-empty)
    for i, row in enumerate(data[1:], start=1):
        if row[2] == "" and row[3] == "" and row[0] != "":
            ts.add("BACKGROUND", (0, i), (-1, i), TRUST_INDIGO)
            ts.add("TEXTCOLOR",  (0, i), (-1, i), colors.white)
            ts.add("FONTNAME",   (0, i), (-1, i), "Helvetica-Bold")
            ts.add("SPAN",       (0, i), (-1, i))
        elif i % 2 == 0:
            ts.add("BACKGROUND", (0, i), (-1, i), LIGHT_GREY)

    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(ts)
    elems.append(t)
    return _build(elems)


# ══════════════════════════════════════════════════════════════════════════════
# 2. I&E STATEMENT
# ══════════════════════════════════════════════════════════════════════════════

def ie_statement_pdf(fy, year_end_str, data):
    """
    fy          : str   e.g. '2025-26'
    year_end_str: str   e.g. '31 March 2026'
    data        : dict  keys: i01,i02,i03,i04,i05,i_aadi,i_sb,i_fd,
                              e01,e02,e03,e04,e05,e06,e08,e09,
                              total_income,total_exp,ie_result,grand_total,
                              surplus_label,balancing_amt
    Returns PDF bytes.
    """
    d = data
    elems = _header_elements(
        "Income & Expenditure Account",
        f"For the year ended {year_end_str}",
        f"Financial Year {fy}",
    )

    ie_result    = d["ie_result"]
    grand_total  = d["grand_total"]
    slabel       = d["surplus_label"]
    bal_amt      = d["balancing_amt"]

    festival_exp   = d["e01"] + d["e04"] + d["e02"] + d["e05"] + d["e06"] + d["e03"]
    other_exp      = d["e08"] + d["e09"]
    total_donations = d["i01"] + d["i_aadi"] + d["i02"] + d["i03"] + d["i04"] + d["i05"]
    total_interest  = d["i_sb"] + d["i_fd"]

    # ── Build a unified 6-column table ────────────────────────────────────────
    # cols: [ExpDesc | ExpInner | ExpOuter || IncDesc | IncInner | IncOuter]
    half = IW / 2 - 2 * mm
    cw = [half*0.56, half*0.20, half*0.24,
          half*0.56, half*0.20, half*0.24]

    BOLD  = "Helvetica-Bold"
    NORM  = "Helvetica"
    ITAL  = "Helvetica-Oblique"
    GRP   = colors.HexColor("#EEEEEE")

    def row6(e_desc="", e_in=None, e_out=None,
             i_desc="", i_in=None, i_out=None,
             bold=False, group=False):
        fn = BOLD if (bold or group) else NORM
        fc = colors.white if group else colors.black
        def cell(v, align="RIGHT", fn2=fn, fc2=fc):
            return _p(v if v is not None else "", 8, bold=(fn2==BOLD),
                      color=fc2, align=(TA_RIGHT if align=="RIGHT" else TA_LEFT))
        e_in_str  = _fmt(e_in)  if e_in  is not None and e_in  > 0.005 else ""
        e_out_str = _fmt(e_out) if e_out is not None and e_out > 0.005 else ""
        i_in_str  = _fmt(i_in)  if i_in  is not None and i_in  > 0.005 else ""
        i_out_str = _fmt(i_out) if i_out is not None and i_out > 0.005 else ""
        return [
            cell(e_desc, "LEFT"),
            cell(e_in_str),
            cell(e_out_str),
            cell(i_desc, "LEFT"),
            cell(i_in_str),
            cell(i_out_str),
        ]

    tdata = [["Expenditure", "", "", "Income", "", ""]]

    # ── Pair up rows so both sides grow together ───────────────────────────────
    exp_section_rows = []
    inc_section_rows = []

    # Exp: section header
    exp_section_rows.append(("EXP_SECTION", "Expenditure towards"))
    # Exp: festival items
    for label, amt in [
        ("  Nithya Pooja",     d["e01"]),
        ("  Aadi Pooram",      d["e04"]),
        ("  Pradosham",        d["e02"]),
        ("  Garuda Seva",      d["e05"]),
        ("  Varushabhishekam", d["e06"]),
        ("  Panguni Uthram",   d["e03"]),
    ]:
        if amt > 0.005:
            exp_section_rows.append(("ITEM", label, amt))
    exp_section_rows.append(("SUBTOTAL", "Sub-total", festival_exp))
    exp_section_rows.append(("SPACER",))
    exp_section_rows.append(("EXP_SECTION", "Other Expenses"))
    for label, amt in [("  Bank Charges", d["e08"]), ("  Audit Fees", d["e09"])]:
        if amt > 0.005:
            exp_section_rows.append(("ITEM", label, amt))
    exp_section_rows.append(("SUBTOTAL", "Sub-total", other_exp))
    exp_section_rows.append(("SPACER",))
    if ie_result >= 0:
        exp_section_rows.append(("BALANCING", slabel, bal_amt))
        exp_section_rows.append(("SPACER",))
    exp_section_rows.append(("TOTAL", "TOTAL", grand_total))

    # Inc: section header
    inc_section_rows.append(("INC_SECTION", "Donations received for"))
    for label, amt in [
        ("  Nithya Pooja",     d["i01"]),
        ("  Aadi Pooram",      d["i_aadi"]),
        ("  Pradosham",        d["i02"]),
        ("  Garuda Seva",      d["i03"]),
        ("  Varushabhishekam", d["i04"]),
        ("  Panguni Uthram",   d["i05"]),
    ]:
        if amt > 0.005:
            inc_section_rows.append(("ITEM", label, amt))
    inc_section_rows.append(("SUBTOTAL", "Sub-total", total_donations))
    inc_section_rows.append(("SPACER",))
    inc_section_rows.append(("INC_SECTION", "Interest Income"))
    for label, amt in [
        ("  Interest on Savings Bank",   d["i_sb"]),
        ("  Interest on Fixed Deposits", d["i_fd"]),
    ]:
        if amt > 0.005:
            inc_section_rows.append(("ITEM", label, amt))
    inc_section_rows.append(("SUBTOTAL", "Sub-total", total_interest))
    inc_section_rows.append(("SPACER",))
    if ie_result < 0:
        inc_section_rows.append(("BALANCING", slabel, bal_amt))
        inc_section_rows.append(("SPACER",))
    inc_section_rows.append(("TOTAL", "TOTAL", grand_total))

    # Pad shorter side with spacers
    while len(exp_section_rows) < len(inc_section_rows):
        exp_section_rows.insert(-1, ("SPACER",))
    while len(inc_section_rows) < len(exp_section_rows):
        inc_section_rows.insert(-1, ("SPACER",))

    ts_cmds = _hdr_ts() + [
        ("ALIGN",  (0, 0), (-1, 0), "CENTER"),
        ("ALIGN",  (1, 1), (2, -1), "RIGHT"),
        ("ALIGN",  (4, 1), (5, -1), "RIGHT"),
        ("ALIGN",  (0, 1), (0, -1), "LEFT"),
        ("ALIGN",  (3, 1), (3, -1), "LEFT"),
        ("GRID",   (0, 0), (-1, -1), 0.2, MID_GREY),
        ("LINEAFTER", (2, 0), (2, -1), 1.2, TRUST_BLUE),  # vertical divider
    ]

    section_rows = []  # track row indices needing section-header style
    subtotal_rows = []
    total_rows = []

    for e_row, i_row in zip(exp_section_rows, inc_section_rows):
        row_idx = len(tdata)

        # Extract e/i values
        e_type = e_row[0]
        i_type = i_row[0]

        e_desc = e_row[1] if len(e_row) > 1 else ""
        i_desc = i_row[1] if len(i_row) > 1 else ""
        e_in = e_row[2] if e_type == "ITEM" else None
        e_out = e_row[2] if e_type in ("SUBTOTAL", "BALANCING", "TOTAL") else None
        i_in = i_row[2] if i_type == "ITEM" else None
        i_out = i_row[2] if i_type in ("SUBTOTAL", "BALANCING", "TOTAL") else None
        is_bold = e_type in ("SUBTOTAL", "TOTAL", "BALANCING") or \
                  i_type in ("SUBTOTAL", "TOTAL", "BALANCING")
        is_section = e_type.endswith("_SECTION") or i_type.endswith("_SECTION")

        if e_type == "SPACER" and i_type == "SPACER":
            tdata.append(["", "", "", "", "", ""])
            continue

        tdata.append(row6(
            e_desc=e_desc, e_in=e_in, e_out=e_out,
            i_desc=i_desc, i_in=i_in, i_out=i_out,
            bold=is_bold, group=is_section,
        ))

        if is_section:
            section_rows.append(row_idx)
        elif e_type == "SUBTOTAL" or i_type == "SUBTOTAL":
            subtotal_rows.append(row_idx)
        elif e_type == "TOTAL" or i_type == "TOTAL":
            total_rows.append(row_idx)

    for ri in section_rows:
        ts_cmds += [
            ("BACKGROUND", (0, ri), (2, ri), colors.HexColor("#E8ECF5")),
            ("BACKGROUND", (3, ri), (5, ri), colors.HexColor("#E8ECF5")),
            ("FONTNAME",   (0, ri), (-1, ri), "Helvetica-Bold"),
        ]
    for ri in subtotal_rows:
        ts_cmds += [
            ("LINEABOVE",  (0, ri), (2, ri), 0.5, MID_GREY),
            ("LINEABOVE",  (3, ri), (5, ri), 0.5, MID_GREY),
            ("FONTNAME",   (0, ri), (-1, ri), "Helvetica-Bold"),
        ]
    for ri in total_rows:
        ts_cmds += [
            ("LINEABOVE",  (0, ri), (2, ri), 1.2, TRUST_BLUE),
            ("LINEABOVE",  (3, ri), (5, ri), 1.2, TRUST_BLUE),
            ("LINEBELOW",  (0, ri), (2, ri), 1.2, TRUST_BLUE),
            ("LINEBELOW",  (3, ri), (5, ri), 1.2, TRUST_BLUE),
            ("FONTNAME",   (0, ri), (-1, ri), "Helvetica-Bold"),
        ]

    t = Table(tdata, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle(ts_cmds))
    elems.append(t)
    elems.append(Spacer(1, 4 * mm))
    note_style = ParagraphStyle("note", fontSize=7, fontName="Helvetica-Oblique",
                                 textColor=colors.grey)
    elems.append(Paragraph(
        "Note: Renovation Fund income & expenditure are excluded — shown in the "
        "Renovation Fund on the Balance Sheet. Bank interest shown separately.",
        note_style,
    ))
    return _build(elems)


# ══════════════════════════════════════════════════════════════════════════════
# 3. BALANCE SHEET
# ══════════════════════════════════════════════════════════════════════════════

def balance_sheet_pdf(fy, data):
    """
    fy   : str   e.g. '2025-26'
    data : dict  keys: a01,a02,a03,a04,a05,
                        l01,l02,l03,l04,l05,
                        ob_l01,ob_l02,ob_l03,
                        i06_cr,e07_dr,total_assets,total_fl
    Returns PDF bytes.
    """
    d = data
    year_end = fy.split("-")[1]
    elems = _header_elements(
        "Balance Sheet",
        f"As at 31 March 20{year_end}",
        f"Financial Year {fy}",
    )

    a01 = d["a01"]; a02 = d["a02"]; a03 = d["a03"]
    a04 = d["a04"]; a05 = d["a05"]
    l01 = d["l01"]; l02 = d["l02"]; l03 = d["l03"]
    l04 = d["l04"]; l05 = d["l05"]
    ob_l01 = d["ob_l01"]; ob_l02 = d["ob_l02"]; ob_l03 = d["ob_l03"]
    i06_cr = d["i06_cr"]; e07_dr = d["e07_dr"]
    total_assets = d["total_assets"]; total_fl = d["total_fl"]
    l03_label    = "Non-Corpus Fund (Deficit)" if l03 < 0 else "Non-Corpus Fund"
    l03_movement = l03 - ob_l03

    half = IW / 2 - 2 * mm
    lcw  = [half * 0.68, half * 0.32]
    rcw  = [half * 0.68, half * 0.32]

    def make_side(rows_data):
        data = []
        bold_rows = []
        section_rows = []
        for i, (tag, label, val) in enumerate(rows_data):
            if tag == "HDR":
                data.append([label, ""])
                section_rows.append(i)
            elif tag == "BOLD":
                data.append([label, _fmt(val) if val is not None else ""])
                bold_rows.append(i)
            elif tag == "ITEM":
                data.append([label, _fmt(val) if val is not None else ""])
            elif tag == "TOTAL":
                data.append([label, _fmt(val) if val is not None else ""])
                bold_rows.append(i)
            else:  # BLANK
                data.append(["", ""])

        ts = TableStyle([
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (1, 0), (1, -1),  "RIGHT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("GRID",          (0, 0), (-1, -1), 0.2, MID_GREY),
        ])
        for ri in section_rows:
            ts.add("BACKGROUND", (0, ri), (-1, ri), TRUST_BLUE)
            ts.add("TEXTCOLOR",  (0, ri), (-1, ri), colors.white)
            ts.add("FONTNAME",   (0, ri), (-1, ri), "Helvetica-Bold")
            ts.add("SPAN",       (0, ri), (-1, ri))
        for ri in bold_rows:
            ts.add("FONTNAME",   (0, ri), (-1, ri), "Helvetica-Bold")
        # Total row: last item in bold_rows that is TOTAL tag
        last = len(data) - 1
        ts.add("FONTNAME",   (0, last), (-1, last), "Helvetica-Bold")
        ts.add("LINEABOVE",  (0, last), (-1, last), 1, TRUST_BLUE)
        ts.add("LINEBELOW",  (0, last), (-1, last), 1, TRUST_BLUE)
        t = Table(data, colWidths=lcw if lcw == rcw else lcw)
        t.setStyle(ts)
        return t

    # LEFT — Funds & Liabilities
    left = [("HDR", "Funds & Liabilities", None)]
    left += [
        ("ITEM", "Corpus Fund", None),
        ("ITEM", f"  Opening balance: {_fmt(ob_l01)}", None),
        ("ITEM", "  Additions: Nil", None),
        ("BOLD", "Corpus Fund Total", l01),
        ("BLANK", "", None),
        ("ITEM", "Renovation Fund", None),
        ("ITEM", f"  Opening balance: {_fmt(ob_l02)}", None),
        ("ITEM", f"  Add: Renovation income: {_fmt(i06_cr)}", None),
        ("ITEM", f"  Less: Renovation exp: ({_fmt(e07_dr)})", None),
        ("BOLD", "Renovation Fund Total", l02),
        ("BLANK", "", None),
        ("ITEM", l03_label, None),
        ("ITEM", f"  Opening balance: {_fmt(abs(ob_l03))} {'Dr' if ob_l03 < 0 else 'Cr'}", None),
    ]
    if l03_movement < 0:
        left.append(("ITEM", f"  Add: Deficit for year: {_fmt(abs(l03_movement))}", None))
    else:
        left.append(("ITEM", f"  Add: Surplus for year: {_fmt(l03_movement)}", None))
    left.append(("BOLD", f"{l03_label} Total", l03))
    if l04 != 0:
        left += [("BLANK","",None), ("ITEM","Loan from Trustees", None), ("ITEM","", l04)]
    if l05 != 0:
        left += [("BLANK","",None), ("ITEM","Audit Fees Payable", None), ("ITEM","", l05)]
    left += [("BLANK","",None), ("TOTAL","TOTAL", total_fl)]

    # RIGHT — Assets
    right = [("HDR", "Assets", None)]
    right += [
        ("ITEM", "Cash in Hand",                   a01),
        ("ITEM", "Cash at Bank — IOB Savings",      a02),
        ("ITEM", "Fixed Deposits",                  a03),
        ("ITEM", "Accrued Interest on FD",          a04),
    ]
    if a05 != 0:
        right.append(("ITEM", "Advance to Priest — Manikandan", a05))

    # Pad right to match left height
    while len(right) < len(left) - 1:
        right.append(("BLANK", "", None))
    right.append(("TOTAL", "TOTAL", total_assets))

    lt = make_side(left)
    lt.colWidths = lcw
    rt = make_side(right)
    rt.colWidths = rcw

    outer = Table([[lt, rt]], colWidths=[half + 3*mm, half + 3*mm])
    outer.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ("RIGHTPADDING",  (0,0), (-1,-1), 2),
        ("TOPPADDING",    (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    elems.append(outer)
    elems.append(Spacer(1, 4 * mm))

    bal_ok = abs(total_fl - total_assets) < 1.0
    bal_style = ParagraphStyle("bal", fontSize=8, fontName="Helvetica-Bold",
                                textColor=GREEN_C if bal_ok else RED_C)
    if bal_ok:
        elems.append(Paragraph(
            f"Balance Sheet balances — Total {_fmt(total_assets)}", bal_style))
    else:
        elems.append(Paragraph(
            f"WARNING: Balance Sheet does NOT balance — "
            f"Funds+Liabilities {_fmt(total_fl)} vs Assets {_fmt(total_assets)}", bal_style))
    return _build(elems)


# ══════════════════════════════════════════════════════════════════════════════
# 4. FESTIVAL P&L
# ══════════════════════════════════════════════════════════════════════════════

def festival_pnl_pdf(fy, rows):
    """
    fy  : str   e.g. '2025-26'
    rows: list of dicts — keys: Fund, 'Income (Rs.)', 'Expenditure (Rs.)', 'Surplus / (Deficit) (Rs.)'
          (the column names from festival_pnl.py summary_rows)
    Returns PDF bytes.
    """
    year_end = fy.split("-")[1]
    elems = _header_elements(
        "Festival P&L Summary",
        f"For the year ended 31 March 20{year_end}",
        f"Financial Year {fy}",
    )

    cw = [IW*0.36, IW*0.20, IW*0.21, IW*0.23]
    tdata = [["Fund", "Income (Rs.)", "Expenditure (Rs.)", "Surplus / (Deficit)"]]

    total_inc = 0.0
    total_exp = 0.0
    total_sur = 0.0

    for row in rows:
        inc = float(row.get("Income (₹)", 0) or row.get("Income (Rs.)", 0) or 0)
        exp = float(row.get("Expenditure (₹)", 0) or row.get("Expenditure (Rs.)", 0) or 0)
        sur = float(row.get("Surplus / (Deficit) (₹)", 0) or
                    row.get("Surplus / (Deficit) (Rs.)", 0) or 0)
        total_inc += inc
        total_exp += exp
        total_sur += sur
        tdata.append([row["Fund"], _fmt(inc), _fmt(exp), _fmt(sur)])

    tdata.append(["TOTAL", _fmt(total_inc), _fmt(total_exp), _fmt(total_sur)])

    ts = TableStyle(_hdr_ts() + [
        ("ALIGN",  (0,0), (-1, 0), "CENTER"),
        ("ALIGN",  (1,1), (-1,-1), "RIGHT"),
        ("ALIGN",  (0,1), ( 0,-1), "LEFT"),
        ("GRID",   (0,0), (-1,-1), 0.3, MID_GREY),
        ("FONTNAME",  (0,-1), (-1,-1), "Helvetica-Bold"),
        ("LINEABOVE", (0,-1), (-1,-1), 1.2, TRUST_BLUE),
        ("LINEBELOW", (0,-1), (-1,-1), 1.2, TRUST_BLUE),
    ])

    # Colour surplus/deficit column
    for i, row in enumerate(rows, start=1):
        sur = float(row.get("Surplus / (Deficit) (₹)", 0) or
                    row.get("Surplus / (Deficit) (Rs.)", 0) or 0)
        ts.add("TEXTCOLOR", (3, i), (3, i), GREEN_C if sur >= 0 else RED_C)
        if i % 2 == 0:
            ts.add("BACKGROUND", (0, i), (-1, i), LIGHT_GREY)

    t = Table(tdata, colWidths=cw, repeatRows=1)
    t.setStyle(ts)
    elems.append(t)
    return _build(elems)
