"""Render operating statements (xlsx / pdf; monthly, annual, YTD-annualised) and return the correct
categorised extraction (truth)."""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .refdata import FOOTER
from .xlsxutil import finalize_workbook

CATS = ["service_charge", "district_cooling", "utilities_common", "property_management", "maintenance_repairs", "insurance",
        "security_cleaning", "marketing_leasing", "admin_other", "sinking_fund"]


def _truth_block(doc, spec, cites):
    lines = []
    for ln in doc["income"] + doc["expenses"]:
        lines.append({"label": ln["label"], "category": ln["category"], "amount_aed": ln["stated"],
                      "source": cites[ln["label"]], **({"ytd_aed": ln["ytd"]} if "ytd" in ln else {})})
    cats = {}
    for ln in doc["expenses"]:
        cats[ln["category"]] = cats.get(ln["category"], 0) + ln["stated"]
    absent = [c for c in CATS if c not in cats]
    out = {
        "document": spec["stmt"]["file"], "format": spec["stmt"]["fmt"], "title": spec["stmt"]["title"],
        "period": doc["period"], "lines": lines,
        "rental_income_aed": sum(ln["stated"] for ln in doc["income"] if ln["category"] == "rental_income"),
        "other_income_aed": sum(ln["stated"] for ln in doc["income"] if ln["category"] == "other_income"),
        "opex_by_category_aed": cats, "total_opex_aed": sum(cats.values()), "categories_absent": absent,
        "amounts_basis": "as stated in the document's annual/total column" + (" (annualised)" if doc["period"]["annualised"] else ""),
        "opex_includes_vat": True,
    }
    if doc["period"]["annualised"]:
        out["ytd_actual"] = {
            "rental_income_aed": sum(ln["ytd"] for ln in doc["income"] if ln["category"] == "rental_income"),
            "other_income_aed": sum(ln["ytd"] for ln in doc["income"] if ln["category"] == "other_income"),
            "total_opex_aed": sum(ln["ytd"] for ln in doc["expenses"]),
        }
    out["noi_stated_aed"] = out["rental_income_aed"] + out["other_income_aed"] - out["total_opex_aed"]
    return out


def _mlabel(m):
    return m.strftime("%b-%y")


# --------------------------------------------------------------------------- xlsx
def write_stmt_xlsx(path, b, spec, doc):
    wb = Workbook()
    ws = wb.active
    lay = doc["layout"]
    ws.title = {"monthly": "T12", "annual_comparative": "P&L", "ytd_annualised": "I&E FY2026", "annual_simple": "Statement"}[lay]
    neg = spec["stmt"]["vocab"] == "landlord"
    nf = "#,##0;(#,##0)" if neg else "#,##0"
    months = doc["months"]
    if lay == "monthly":
        heads = [_mlabel(m) for m in months] + ["Total"]
    elif lay == "annual_comparative":
        heads = [f"FY {months[0].strftime('%b%y')}-{months[-1].strftime('%b%y')}", "Prior year", "Var %"]
    elif lay == "ytd_annualised":
        y = months[-1].year
        heads = [f"Q1 {y}", f"Q2 {y}", f"Q3 {y}", f"FY{y}"]
    else:
        heads = ["Amount (AED)"]
    ncol = 1 + len(heads)
    lc = get_column_letter(ncol)
    title_lines = [b["name"], spec["stmt"]["title"]]
    if lay == "monthly":
        title_lines.append(f"Period: {months[0].strftime('%B %Y')} to {months[-1].strftime('%B %Y')}  |  AED, cash basis")
    elif lay == "annual_comparative":
        title_lines.append(f"Financial year {months[0].strftime('%d %b %Y').replace(months[0].strftime('%d'), '01')} - {doc['period']['end']}  |  Amounts in AED")
    elif lay == "ytd_annualised":
        title_lines.append("Amounts in AED")
    else:
        title_lines.append(f"From {months[0].strftime('%d/%m/%Y')} to {doc['period']['end'][8:]}/{doc['period']['end'][5:7]}/{doc['period']['end'][:4]}")
    r = 1
    for i, t in enumerate(title_lines):
        ws.cell(row=r, column=1, value=t).font = Font(bold=i < 2, size=13 if i == 0 else 10)
        r += 1
    r += 1
    hr = r
    ws.cell(row=r, column=1, value="Account" if lay == "annual_comparative" else "Description")
    for j, h in enumerate(heads, 2):
        ws.cell(row=r, column=j, value=h)
    for j in range(1, ncol + 1):
        c = ws.cell(row=r, column=j)
        c.font = Font(bold=True, color="FFFFFF" if lay != "annual_simple" else "000000")
        c.fill = PatternFill("solid", fgColor={"monthly": "1F3A5F", "annual_comparative": "7B1E2B", "ytd_annualised": "1F3A5F",
                                               "annual_simple": "D9D9D9"}[lay])
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    r += 1
    cites = {}
    total_col = get_column_letter(ncol if lay in ("monthly", "ytd_annualised", "annual_simple") else 2)

    def put_line(label, ln, sign=1):
        nonlocal r
        ws.cell(row=r, column=1, value=label)
        if lay == "monthly":
            vals = ln["monthly"] + [ln["total"]]
        elif lay == "annual_comparative":
            vals = [ln["stated"], ln["prior"], (ln["stated"] - ln["prior"]) / ln["prior"] if ln["prior"] else None]
        elif lay == "ytd_annualised":
            vals = ln["quarters"] + [ln["annualised"]]
        else:
            vals = [ln["stated"]]
        for j, v in enumerate(vals, 2):
            c = ws.cell(row=r, column=j, value=(v * sign if (v is not None and not (lay == "annual_comparative" and j == 4)) else v))
            c.number_format = "0.0%" if (lay == "annual_comparative" and j == 4) else nf
        cites[label] = f"{ws.title}!{total_col}{r}"
        r += 1

    def section(name):
        nonlocal r
        ws.cell(row=r, column=1, value=name).font = Font(bold=True)
        r += 1

    def total_row(name, values):
        nonlocal r
        ws.cell(row=r, column=1, value=name).font = Font(bold=True)
        for j, v in enumerate(values, 2):
            c = ws.cell(row=r, column=j, value=v)
            c.number_format = nf
            c.font = Font(bold=True)
            c.border = Border(top=Side(style="thin"))
        r += 1

    def col_values(lines, sign=1):
        if lay == "monthly":
            return [sign * sum(ln["monthly"][i] for ln in lines) for i in range(12)] + [sign * sum(ln["total"] for ln in lines)]
        if lay == "annual_comparative":
            return [sign * sum(ln["stated"] for ln in lines), sign * sum(ln["prior"] for ln in lines)]
        if lay == "ytd_annualised":
            return [sign * sum(ln["quarters"][i] for ln in lines) for i in range(3)] + [sign * sum(ln["annualised"] for ln in lines)]
        return [sign * sum(ln["stated"] for ln in lines)]

    section("INCOME" if lay != "annual_simple" else "Income")
    for ln in doc["income"]:
        put_line(ln["label"], ln)
    inc = col_values(doc["income"])
    total_row("Total income", inc)
    r += 1
    section("OPERATING EXPENSES" if lay != "annual_simple" else "Expenses")
    for ln in doc["expenses"]:
        put_line(ln["label"], ln, -1 if neg else 1)
    exp = col_values(doc["expenses"], -1 if neg else 1)
    total_row("Total operating expenses", exp)
    r += 1
    noi = [a + e if neg else a - e for a, e in zip(inc, exp)]
    total_row("NET OPERATING INCOME" if lay != "annual_simple" else "Net income", noi)
    r += 1
    notes = []
    if lay == "ytd_annualised":
        notes.append(f"FY{months[-1].year} column: January-September actuals annualised (x 12/9). Q4 to be updated on close.")
    if lay == "monthly":
        notes.append("Unaudited management accounts. Rental income recognised on a cash basis (cheques cleared).")
    if lay == "annual_comparative":
        notes.append("Unaudited. Expenses shown in brackets.")
    if lay == "annual_simple":
        notes.append("Prepared by owner's accountant from bank statements. Not audited.")
    notes.append("Expenses are shown inclusive of VAT, which is not recoverable on residential rent.")
    for n in notes:
        ws.cell(row=r, column=1, value=n).font = Font(italic=True, size=8)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value=FOOTER).font = Font(italic=True, size=8, color="808080")
    ws.oddFooter.center.text = FOOTER
    ws.column_dimensions["A"].width = 48
    for j in range(2, ncol + 1):
        ws.column_dimensions[get_column_letter(j)].width = 11 if lay == "monthly" else 17
    ws.freeze_panes = f"B{hr + 1}"
    finalize_workbook(wb, path, creator="Accounts")
    truth = _truth_block(doc, spec, cites)
    truth["layout"] = {"sheet": ws.title, "header_row": hr, "amount_column": total_col, "columns": heads, "notes": notes}
    return truth


# --------------------------------------------------------------------------- pdf
def write_stmt_pdf(path, b, spec, doc):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    lay = doc["layout"]
    months = doc["months"]
    vocab = spec["stmt"]["vocab"]
    land = lay == "monthly"
    ps = landscape(A4) if land else A4
    font = {"accountant": ("Times-Roman", "Times-Bold"), "owner": ("Helvetica", "Helvetica-Bold")}.get(vocab, ("Helvetica", "Helvetica-Bold"))
    sty_h = ParagraphStyle("h", fontName=font[1], fontSize=13, leading=16)
    sty_s = ParagraphStyle("s", fontName=font[0], fontSize=9, leading=11.5)
    sty_n = ParagraphStyle("n", fontName=font[0], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#444444"))

    def fmt(v):
        if v is None:
            return ""
        return f"({abs(v):,})" if v < 0 else f"{v:,}"

    if lay == "monthly":
        head = ["AED"] + [_mlabel(m) for m in months] + ["Total"]
    elif lay == "annual_comparative":
        head = ["", f"12 months to\n{months[-1].strftime('%b %Y')}", f"12 months to\n{months[-1].replace(year=months[-1].year - 1).strftime('%b %Y')}"]
    else:
        head = ["", "AED"]
    data = [head]
    style = []

    def row_vals(ln):
        if lay == "monthly":
            return [fmt(x) for x in ln["monthly"]] + [fmt(ln["total"])]
        if lay == "annual_comparative":
            return [fmt(ln["stated"]), fmt(ln["prior"])]
        return [fmt(ln["stated"])]

    def add_section(name):
        data.append([name] + [""] * (len(head) - 1))
        style.append(("FONT", (0, len(data) - 1), (0, len(data) - 1), font[1], 8 if land else 9.5))

    def add_total(name, vals):
        data.append([name] + vals)
        i = len(data) - 1
        style.append(("FONT", (0, i), (-1, i), font[1], 7 if land else 9.5))
        style.append(("LINEABOVE", (1, i), (-1, i), 0.6, colors.black))

    def sums(lines):
        if lay == "monthly":
            return [fmt(sum(ln["monthly"][i] for ln in lines)) for i in range(12)] + [fmt(sum(ln["total"] for ln in lines))]
        if lay == "annual_comparative":
            return [fmt(sum(ln["stated"] for ln in lines)), fmt(sum(ln["prior"] for ln in lines))]
        return [fmt(sum(ln["stated"] for ln in lines))]

    add_section("Income" if not land else "INCOME")
    for ln in doc["income"]:
        data.append(["  " + ln["label"]] + row_vals(ln))
    add_total("Total income", sums(doc["income"]))
    data.append([""] * len(head))
    add_section("Operating expenses" if not land else "EXPENSES")
    for ln in doc["expenses"]:
        data.append(["  " + ln["label"]] + row_vals(ln))
    add_total("Total operating expenses", sums(doc["expenses"]))
    data.append([""] * len(head))

    def noi_vals():
        if lay == "monthly":
            inc = [sum(ln["monthly"][i] for ln in doc["income"]) for i in range(12)]
            exp = [sum(ln["monthly"][i] for ln in doc["expenses"]) for i in range(12)]
            v = [a - e for a, e in zip(inc, exp)]
            return [fmt(x) for x in v] + [fmt(sum(v))]
        if lay == "annual_comparative":
            return [fmt(sum(l["stated"] for l in doc["income"]) - sum(l["stated"] for l in doc["expenses"])),
                    fmt(sum(l["prior"] for l in doc["income"]) - sum(l["prior"] for l in doc["expenses"]))]
        return [fmt(sum(l["stated"] for l in doc["income"]) - sum(l["stated"] for l in doc["expenses"]))]

    add_total("Net operating income" if vocab != "owner" else "Net income", noi_vals())
    style.append(("LINEBELOW", (1, len(data) - 1), (-1, len(data) - 1), 1.0, colors.black))

    if land:
        cw = [52 * mm] + [16.2 * mm] * 12 + [20 * mm]
        base_font = 6.6
    elif lay == "annual_comparative":
        cw = [100 * mm, 35 * mm, 35 * mm]
        base_font = 9.5
    else:
        cw = [120 * mm, 40 * mm]
        base_font = 9.5
    t = Table(data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font[0], base_font), ("FONT", (0, 0), (-1, 0), font[1], base_font),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 1.4 if land else 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4 if land else 2.2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ] + style))

    end = doc["period"]["end"]
    if vocab == "owner":
        sub = f"{b['name']} - {b['sub_community'].split(',')[0]}"
    elif vocab == "strata":
        sub = f"{b['name']}, {b['sub_community']} - owner of {b['unit_count']} units"
    else:
        sub = f"{b['name']}, {b['sub_community']}"
    story = [Paragraph(spec["stmt"]["title"], sty_h), Paragraph(sub, sty_s), Spacer(1, 2 * mm),
             Paragraph(f"Period: {months[0].strftime('%d %B %Y').lstrip('0')} to {int(end[8:])} {months[-1].strftime('%B %Y')}. Amounts in UAE Dirhams (AED).", sty_s),
             Spacer(1, 5 * mm), t, Spacer(1, 5 * mm)]
    notes = []
    if vocab == "strata":
        notes.append("Service charges are levied by the Owners Association on each unit under Law No. 6 of 2019 and paid through Mollak. "
                     "Chiller (Empower) is paid by tenants directly.")
    if vocab == "master_owner":
        notes.append("Building is let in its entirety under a master lease. The master tenant bears leasing, FM, cleaning, security and "
                     "common-area utilities; those costs are not shown in this landlord statement.")
    if vocab == "owner":
        notes.append("Prepared by the owner from bank records. Rent shown as received (cheques cleared in the month).")
    if vocab == "accountant":
        notes.append("Unaudited management information prepared on a cash basis.")
    if vocab == "pm_company":
        notes.append("Prepared by the property manager. Unaudited.")
    notes.append("Expenses include VAT at 5% (not recoverable).")
    for n in notes:
        story.append(Paragraph(n, sty_n))

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.grey)
        c.drawCentredString(ps[0] / 2, 8 * mm, FOOTER)
        c.drawRightString(ps[0] - 14 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    pdf = SimpleDocTemplate(str(path), pagesize=ps, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=spec["stmt"]["title"], author="Accounts", invariant=1)
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    cites = {ln["label"]: "page 1" for ln in doc["income"] + doc["expenses"]}
    truth = _truth_block(doc, spec, cites)
    truth["layout"] = {"columns": head, "notes": notes, "pages": 1}
    return truth
