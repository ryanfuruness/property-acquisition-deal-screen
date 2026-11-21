"""Render rent rolls in varied layouts (xlsx / pdf / csv) and return the correct parse (truth)."""
from __future__ import annotations

import csv
import random
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .analysis import OCC_LIKE
from .refdata import FOOTER
from .xlsxutil import finalize_workbook

SQM = 10.7639

STATUS_VOCAB = {
    "standard": {"occupied": ["Occupied"], "vacant": ["Vacant"], "notice_served": ["Notice Served"],
                 "under_renewal": ["Under Renewal"], "legal_case": ["Legal Case"]},
    "leased": {"occupied": ["Leased"], "vacant": ["Available"], "notice_served": ["Notice given"],
               "under_renewal": ["Renewal pending"], "legal_case": ["RDC case"]},
    "messy": {"occupied": ["Occupied", "occupied", "OCCUPIED", "Rented", "Occupied "], "vacant": ["VACANT", "Vacant", "vacant - ready"],
              "notice_served": ["Notice to vacate", "notice served"], "under_renewal": ["Renewal in progress", "under renewal"],
              "legal_case": ["RDC case", "Legal - cheque bounced"]},
    "lower": {"occupied": ["occupied", "occupied", "rented"], "vacant": ["vacant", "empty"], "notice_served": ["leaving"],
              "under_renewal": ["renewing"], "legal_case": ["case filed", "legal"]},
    "export": {"occupied": ["ACTIVE"], "vacant": ["VACANT"], "notice_served": ["NOTICE"], "under_renewal": ["HOLDOVER-RENEWAL"],
               "legal_case": ["LEGAL"]},
    "bilingual": {"occupied": ["مؤجر Occupied"], "vacant": ["شاغر Vacant"], "notice_served": ["إخطار بالإخلاء Notice"],
                  "under_renewal": ["قيد التجديد Renewal"], "legal_case": ["قضية إيجارية Case"]},
    "caps": {"occupied": ["OCCUPIED"], "vacant": ["VACANT"], "notice_served": ["NOTICE SERVED"], "under_renewal": ["UNDER RENEWAL"],
             "legal_case": ["LEGAL CASE"]},
}
TYPE_VOCAB = {
    "standard": {"studio": "Studio", "1br": "1 BR", "2br": "2 BR", "3br": "3 BR", "retail": "Shop"},
    "bhk": {"studio": "Studio", "1br": "1BHK", "2br": "2BHK", "3br": "3BHK", "retail": "Shop"},
    "bed": {"studio": "Studio", "1br": "1 Bed", "2br": "2 Bed", "3br": "3 Bed", "retail": "Retail"},
    "code": {"studio": "STU", "1br": "1BR", "2br": "2BR", "3br": "3BR", "retail": "RET"},
    "long": {"studio": "Studio", "1br": "One Bedroom", "2br": "Two Bedroom", "3br": "Three Bedroom", "retail": "Retail Shop"},
    "bilingual": {"studio": "استوديو Studio", "1br": "غرفة وصالة 1BR", "2br": "غرفتين وصالة 2BR", "3br": "ثلاث غرف 3BR",
                  "retail": "محل Shop"},
    "caps": {"studio": "STUDIO", "1br": "1 B/R", "2br": "2 B/R", "3br": "3 B/R", "retail": "SHOP"},
}
CHILLER_TXT = {"landlord_district": "Chiller free", "landlord_plant": "Chiller free",
               "tenant_district": "Tenant (Empower)", "tenant_dewa": "DEWA (tenant)"}

THIN = Side(style="thin", color="A0A0A0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _ordinal_floor(f):
    if f == 0:
        return "GROUND FLOOR"
    suf = {1: "ST", 2: "ND", 3: "RD"}.get(f if f < 20 else f % 10, "TH")
    if 10 < f < 14:
        suf = "TH"
    return f"{f}{suf} FLOOR"


class RR:
    """Collects the correct parse while rendering."""

    def __init__(self, building, spec, doc_name):
        self.b = building
        self.spec = spec
        self.doc = doc_name
        self.rows = []
        self.summary_rows = []
        self.rng = random.Random(spec["seed"] + 5)

    def canonical(self, u, *, area_stated, area_unit, cite, tenant_text, rent_cell=None):
        row = {
            "unit": u["unit"], "unit_type": u["type"],
            "area_sqft": round(area_stated * SQM, 2) if area_unit == "sqm" else float(area_stated),
            "tenant": tenant_text, "tenant_type": u["tenant_type"], "ejari_no": u["ejari_no"],
            "lease_start": u["lease_start"].isoformat() if u["lease_start"] else None,
            "lease_end": u["lease_end"].isoformat() if u["lease_end"] else None,
            "annual_rent_aed": u["annual_rent_aed"], "asking_rent_aed": u.get("asking_rent_aed"),
            "cheques": u["cheques"], "deposit_aed": u["deposit_aed"], "status": u["status"],
            "chiller": u["chiller"], "source": cite,
        }
        if area_unit == "sqm":
            row["area_original"] = {"value": area_stated, "unit": "sq m"}
        self.rows.append(row)
        return row


def _units_sorted(b, key="floor"):
    us = list(b["units"])
    return sorted(us, key=lambda u: (u["floor"], u["unit"]))


def _status_text(rr, vocab, s):
    return rr.rng.choice(STATUS_VOCAB[vocab][s])


def _name(u, case):
    if not u["tenant"]:
        return None
    return u["tenant"].upper() if case == "upper" else u["tenant"]


# --------------------------------------------------------------------------- xlsx generic
LAYOUTS = {
    "pm_standard": dict(
        title=lambda b, s: [b["name"], f"Tenancy Schedule as at {s['roll_date'].strftime('%d %B %Y')}",
                            "Prepared by the Property Manager on behalf of the Owner"],
        cols=[("unit", "Unit No."), ("floor", "Floor"), ("type", "Type"), ("area", "Size (sq ft)"), ("tenant", "Tenant Name"),
              ("ttype", "Tenant Type"), ("ejari", "Ejari No."), ("start", "Lease Start"), ("end", "Lease End"),
              ("rent", "Annual Rent (AED)"), ("cheques", "No. of Cheques"), ("deposit", "Security Deposit (AED)"),
              ("chiller", "A/C"), ("status", "Status"), ("remarks", "Remarks")],
        date="excel:dd/mm/yyyy", status="standard", types="standard", case="as_is", area_dp=2,
        group=None, totals="TOTAL", header_fill="1F3A5F", header_font="FFFFFF", vacant_rent="remarks_asking"),
    "grouped_by_type": dict(
        title=lambda b, s: [f"{b['name'].upper()} - RENT ROLL", f"Position as at {s['roll_date'].strftime('%d.%m.%Y')}"],
        cols=[("unit", "Flat No"), ("type", "Category"), ("area", "Area SqFt"), ("tenant", "Tenant"), ("start", "Contract Start"),
              ("end", "Contract End"), ("rent", "Rent p.a. (AED)"), ("cheques", "Cheques"), ("deposit", "Deposit"),
              ("ejari", "Ejari Contract No."), ("status", "Status")],
        date="excel:dd-mmm-yy", status="leased", types="long", case="as_is", area_dp=1,
        group="type", totals="GRAND TOTAL", header_fill="2F4F3A", header_font="FFFFFF", vacant_rent="blank"),
    "floorwise": dict(
        title=lambda b, s: [f"{b['name'].upper()} - RENT ROLL", f"AS ON {s['roll_date'].strftime('%d/%m/%Y')}"],
        cols=[("sno", "S.No"), ("unit", "Unit"), ("type", "Unit Type"), ("area", "Area (Sq.Ft)"), ("tenant", "Tenant Name"),
              ("start", "Contract Start"), ("end", "Contract End"), ("rent", "Annual Rent"), ("cheques", "Payment (Chq)"),
              ("deposit", "Deposit"), ("ejari", "Ejari"), ("status", "Status")],
        date="text:%d-%b-%y", status="messy", types="bhk", case="upper", area_dp=2,
        group="floor", totals="TOTAL", header_fill="000000", header_font="D4AF37", vacant_rent="blank", vacant_tenant="VACANT"),
    "pm_export": dict(
        title=lambda b, s: [f"Report: Rent Roll | Property: {b['name'].upper()} | Run date: {s['roll_date'].isoformat()} 06:12"],
        cols=[("property", "Property"), ("unit", "Unit"), ("type", "Unit Type"), ("area", "Sq.Ft"), ("start", "Lease From"),
              ("end", "Lease To"), ("tenant", "Tenant"), ("ttype", "Tenant Category"), ("ejari", "Ejari"),
              ("rent", "Rent (AED p.a.)"), ("freq", "Pmt Freq"), ("deposit", "Deposit Held"), ("status", "Lease Status"),
              ("chiller", "A/C")],
        date="text:%Y-%m-%d", status="export", types="code", case="upper", area_dp=2, merge_title=False,
        group=None, totals="Grand Total", header_fill="D9D9D9", header_font="000000", vacant_rent="blank"),
    "institutional": dict(
        title=lambda b, s: [f"{b['name']} - Rent Roll", f"Rent roll date: {s['roll_date'].strftime('%d %b %Y')}  |  All rents exclusive of VAT"],
        cols=[("unit", "Unit"), ("floor", "Level"), ("type", "Unit type"), ("area", "NLA (sq ft)"), ("tenant", "Tenant"),
              ("ejari", "Ejari reg. no."), ("start", "Commencement"), ("end", "Expiry"), ("rent", "Passing rent (AED p.a.)"),
              ("psf", "AED psf"), ("cheques", "Cheques"), ("deposit", "Deposit (AED)"), ("status", "Status")],
        group_header=[("Lease details", "start", "end"), ("Financials", "rent", "deposit")],
        date="excel:d mmm yyyy", status="standard", types="bed", case="as_is", area_dp=2,
        group=None, totals="Total / average", header_fill="1F3A5F", header_font="FFFFFF", vacant_rent="blank"),
    "owner_simple": dict(
        title=lambda b, s: [f"{b['name']} - rent roll", f"updated {s['roll_date'].strftime('%d.%m.%y')}"],
        cols=[("unit", "Flat"), ("type", "Type"), ("area", "Sq ft"), ("tenant", "Name"), ("start", "Start"), ("end", "End"),
              ("rent", "Rent"), ("cheques", "Chq"), ("deposit", "Deposit"), ("ejari", "Ejari no"), ("status", "Status"),
              ("note", "Note")],
        date="mixed", status="lower", types="standard", case="as_is", area_dp=0,
        group=None, totals="Total", header_fill="FFF2CC", header_font="000000", vacant_rent="blank"),
    "sqm": dict(
        title=lambda b, s: [f"{b['name']}", f"Tenancy Schedule - {s['roll_date'].strftime('%d/%m/%Y')}", "Areas as per title deeds (square metres)"],
        cols=[("unit", "Unit No."), ("type", "Type"), ("area_sqm", "Area (sq.m)"), ("tenant", "Lessee"), ("ttype", "Lessee Type"),
              ("start", "Tenancy Start"), ("end", "Tenancy Expiry"), ("rent", "Contract Value (AED)"), ("terms", "Payment Terms"),
              ("deposit", "Security Deposit"), ("ejari", "Ejari Contract No."), ("status", "Occupancy Status")],
        date="text:%d/%m/%Y", status="standard", types="standard", case="as_is", area_dp=2,
        group=None, totals="TOTAL", header_fill="7B1E2B", header_font="FFFFFF", vacant_rent="blank"),
    "owner_simple2": dict(
        title=lambda b, s: [f"{b['name'].upper()} - {b['sub_community'].split(',')[-1].strip().upper()} - INTERNATIONAL CITY"],
        cols=[("sno", "No"), ("unit", "Flat/Shop"), ("type", "Type"), ("area", "Size"), ("tenant", "Tenant Name"), ("start", "From"),
              ("end", "To"), ("rent", "Rent / Asking (AED)"), ("cheques", "Cheques"), ("deposit", "Deposit"), ("ejari", "Ejari"),
              ("remarks", "Remarks")],
        date="excel:dd/mm/yyyy", status="caps", types="caps", case="upper", area_dp=0,
        group=None, totals="TOTAL ANNUAL RENT", header_fill="F4B183", header_font="000000", vacant_rent="asking_in_rent"),
    "oa_style": dict(
        title=lambda b, s: [f"{b['name']} - Rent Roll", f"As at {s['roll_date'].strftime('%d/%m/%Y')}"],
        cols=[("unit", "Unit"), ("deed", "Title Deed No."), ("type", "Type"), ("area", "Area (sq ft)"), ("tenant", "Tenant"),
              ("ejari", "Ejari"), ("start", "Start"), ("end", "End"), ("rent", "Rent (AED)"), ("cheques", "Cheques"),
              ("deposit", "Deposit"), ("status", "Status"), ("sc", "Service Charge (AED/yr)")],
        date="excel:dd/mm/yyyy", status="standard", types="standard", case="as_is", area_dp=2,
        group=None, totals="TOTAL", header_fill="000000", header_font="D4AF37", vacant_rent="blank"),
    "bilingual": dict(
        title=lambda b, s: [f"كشف الإيجارات - {b['name']} - Rent Schedule", f"كما في / As at {s['roll_date'].strftime('%d/%m/%Y')}"],
        cols=[("unit", "رقم الوحدة / Unit No."), ("type", "النوع / Type"), ("area", "المساحة (قدم مربع) / Area (sq ft)"),
              ("tenant", "اسم المستأجر / Tenant Name"), ("ejari", "رقم إيجاري / Ejari No."), ("start", "تاريخ البداية / Start"),
              ("end", "تاريخ الانتهاء / End"), ("rent", "الإيجار السنوي (درهم) / Annual Rent (AED)"), ("cheques", "عدد الشيكات / Cheques"),
              ("deposit", "التأمين / Deposit"), ("status", "الحالة / Status")],
        date="excel:dd/mm/yyyy", status="bilingual", types="bilingual", case="as_is", area_dp=2,
        group=None, totals="الإجمالي / TOTAL", header_fill="2E5E4E", header_font="FFFFFF", vacant_rent="blank"),
    "export_split": dict(
        title=lambda b, s: [f"{b['name']} | Unit listing export | {s['roll_date'].strftime('%d-%b-%Y')}"],
        cols=[("unit", "UnitRef"), ("floor", "Lvl"), ("type", "Config"), ("area", "Size_sqft"), ("tenant", "Occupant"),
              ("ttype", "OccupantType"), ("start", "LeaseStart"), ("end", "LeaseEnd"), ("rent", "ContractRent_AED"),
              ("cheques", "PDCs"), ("deposit", "SecDep_AED"), ("ejari", "EjariRef"), ("status", "UnitStatus")],
        date="text:%d-%b-%Y", status="export", types="code", case="as_is", area_dp=2, merge_title=False,
        group=None, totals="Sheet total", header_fill="DDEBF7", header_font="000000", vacant_rent="blank"),
    "master_sub": dict(
        title=lambda b, s: [f"{b['name']} - Operator sub-tenancy schedule", f"Prepared by {b['master_lease']['tenant']} - {s['roll_date'].strftime('%d %b %Y')}"],
        cols=[("unit", "Unit"), ("type", "Type"), ("area", "Size sqft"), ("tenant", "Sub-tenant"), ("ejari", "Ejari"),
              ("start", "Start"), ("end", "End"), ("rent", "Rent AED"), ("cheques", "Cheques"), ("status", "Status")],
        date="excel:dd/mm/yyyy", status="standard", types="standard", case="as_is", area_dp=1,
        group=None, totals="Total", header_fill="000000", header_font="D4AF37", vacant_rent="blank"),
}


def _write_date(ws, cell, d, mode, rr):
    if d is None:
        return None
    if mode.startswith("excel:"):
        c = ws[cell]
        c.value = datetime(d.year, d.month, d.day)
        c.number_format = mode.split(":", 1)[1]
        return d
    if mode == "mixed":
        if rr.rng.random() < 0.55:
            c = ws[cell]
            c.value = datetime(d.year, d.month, d.day)
            c.number_format = "dd/mm/yyyy"
        else:
            ws[cell] = d.strftime("%d.%m.%Y")
        return d
    ws[cell] = d.strftime(mode.split(":", 1)[1])
    return d


def write_rentroll_xlsx(path, b, spec, layout_name, *, wb=None, sheet_title="Rent Roll", stale=None, units_subset=None, rr=None,
                        finalize=True):
    L = LAYOUTS[layout_name]
    own_wb = wb is None
    if own_wb:
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_title
    else:
        ws = wb.create_sheet(sheet_title)
    rr = rr or RR(b, spec, path.name)
    cols = L["cols"]
    ncol = len(cols)
    last_col = get_column_letter(ncol)
    r = 1
    for i, t in enumerate(L["title"](b, spec)):
        ws.cell(row=r, column=1, value=t)
        ws.cell(row=r, column=1).font = Font(bold=(i == 0), size=14 if i == 0 else 10)
        if L.get("merge_title", True):
            ws.merge_cells(f"A{r}:{last_col}{r}")
            ws.cell(row=r, column=1).alignment = Alignment(horizontal="center")
        r += 1
    r += 1
    if L.get("group_header"):
        keys = [k for k, _ in cols]
        for lab, a, z in L["group_header"]:
            ca, cz = keys.index(a) + 1, keys.index(z) + 1
            ws.cell(row=r, column=ca, value=lab)
            ws.merge_cells(start_row=r, start_column=ca, end_row=r, end_column=cz)
            ws.cell(row=r, column=ca).alignment = Alignment(horizontal="center")
            ws.cell(row=r, column=ca).font = Font(bold=True, color=L["header_font"])
            for c in range(ca, cz + 1):
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=L["header_fill"])
        r += 1
    header_row = r
    for j, (_, h) in enumerate(cols, 1):
        c = ws.cell(row=r, column=j, value=h)
        c.font = Font(bold=True, color=L["header_font"])
        c.fill = PatternFill("solid", fgColor=L["header_fill"])
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BOX
    ws.row_dimensions[r].height = 30
    r += 1
    first_data = r
    units = _units_sorted(b) if units_subset is None else units_subset
    if L["group"] == "type":
        order = ["studio", "1br", "2br", "3br", "retail"]
        groups = [(TYPE_VOCAB["long"][t].upper() + ("S" if t != "retail" else " UNITS"), [u for u in units if u["type"] == t])
                  for t in order if any(u["type"] == t for u in units)]
    elif L["group"] == "floor":
        floors = sorted({u["floor"] for u in units})
        groups = [(_ordinal_floor(f) + (" - RETAIL" if f == 0 else ""), [u for u in units if u["floor"] == f]) for f in floors]
    else:
        groups = [(None, units)]
    tot_rent = 0
    tot_area = 0.0
    tot_dep = 0
    n_units = 0
    sno = 0
    keys = [k for k, _ in cols]
    for gname, gunits in groups:
        if gname:
            ws.cell(row=r, column=1, value=gname).font = Font(bold=True)
            rr.summary_rows.append({"row": r, "label": gname, "kind": "group_heading"})
            r += 1
        g_rent = 0
        g_area = 0.0
        for u in gunits:
            sno += 1
            vals = {}
            vac = u["status"] == "vacant"
            dp = L["area_dp"]
            area_sqft = round(u["area_sqft"], dp) if dp else int(round(u["area_sqft"]))
            area_sqm = round(u["area_sqft"] / SQM, 2)
            tenant = _name(u, L["case"])
            if vac and L.get("vacant_tenant"):
                tenant_cell = L["vacant_tenant"]
            else:
                tenant_cell = tenant
            rent_val = u["annual_rent_aed"]
            if vac and L["vacant_rent"] == "asking_in_rent":
                rent_val = u["asking_rent_aed"]
            vals.update(
                sno=sno, unit=u["unit"], floor=("G" if u["floor"] == 0 else u["floor"]), type=TYPE_VOCAB[L["types"]][u["type"]],
                area=area_sqft, area_sqm=area_sqm, tenant=tenant_cell,
                ttype=(None if vac else ("Company" if u["tenant_type"] == "company" else "Individual")),
                ejari=u["ejari_no"], rent=rent_val, cheques=u["cheques"], deposit=u["deposit_aed"],
                chiller=CHILLER_TXT[u["chiller"]], status=_status_text(rr, L["status"], u["status"]),
                property=b["name"].upper(), freq=(f"{u['cheques']} Cheque{'s' if u['cheques'] != 1 else ''}" if u["cheques"] else None),
                terms=(f"{u['cheques']} chq{'s' if u['cheques'] != 1 else ''}" if u["cheques"] else None),
                psf=(round(u["annual_rent_aed"] / u["area_sqft"], 2) if u["annual_rent_aed"] else None),
                deed=spec.get("_deed_no", lambda x: None)(u),
                sc=(int(round(u["area_sqft"] * spec.get("_sc_rate", 0))) if spec.get("_sc_rate") else None),
                remarks=None, note=None,
            )
            if vac and L["vacant_rent"] == "remarks_asking":
                vals["remarks"] = f"Asking AED {u['asking_rent_aed']:,}"
            if vac and L["vacant_rent"] == "asking_in_rent":
                vals["remarks"] = "VACANT - asking"
            if u["status"] == "notice_served" and "remarks" in keys and not vals["remarks"]:
                vals["remarks"] = "Vacating on expiry"
            if u["status"] == "legal_case" and "note" in keys:
                vals["note"] = rr.rng.choice(["cheque bounced, case at RDC", "RDC case filed"])
            if u.get("holding_over") and "note" in keys:
                vals["note"] = rr.rng.choice(["", "renewal to follow", None])
            for j, k in enumerate(keys, 1):
                cell = f"{get_column_letter(j)}{r}"
                if k in ("start", "end"):
                    d = u["lease_start"] if k == "start" else u["lease_end"]
                    _write_date(ws, cell, d, L["date"], rr)
                else:
                    v = vals.get(k)
                    if v not in (None, ""):
                        ws[cell] = v
                    if k in ("rent", "deposit", "sc") and isinstance(v, (int, float)):
                        ws[cell].number_format = "#,##0"
                    if k in ("area", "area_sqm", "psf") and isinstance(v, (int, float)):
                        ws[cell].number_format = "#,##0.00" if (k != "area" or dp) else "#,##0"
                ws[cell].border = BOX
            area_unit = "sqm" if "area_sqm" in keys else "sqft"
            stated_area = area_sqm if area_unit == "sqm" else area_sqft
            row = rr.canonical(u, area_stated=stated_area, area_unit=area_unit,
                               cite=f"{ws.title}!A{r}:{last_col}{r}", tenant_text=tenant)
            if L["vacant_rent"] == "asking_in_rent" and vac:
                row["rent_column_shows"] = "asking rent"
            n_units += 1
            tot_area += stated_area
            g_area += stated_area
            if rent_val:
                tot_rent += rent_val
                g_rent += rent_val
            if u["deposit_aed"]:
                tot_dep += u["deposit_aed"]
            r += 1
        if L["group"] == "type":
            ws.cell(row=r, column=1, value=f"Sub-total {gname.title()}").font = Font(bold=True, italic=True)
            ws.cell(row=r, column=keys.index("area") + 1, value=round(g_area, 1)).number_format = "#,##0.0"
            c = ws.cell(row=r, column=keys.index("rent") + 1, value=g_rent)
            c.number_format = "#,##0"
            c.font = Font(bold=True, italic=True)
            rr.summary_rows.append({"row": r, "label": f"Sub-total {gname.title()}", "kind": "subtotal",
                                    "units": len(gunits), "rent_aed": g_rent})
            r += 1
        if L["group"] == "floor":
            r += 1  # blank separator
    last_data = r - 1
    # totals row
    stated_rent = tot_rent if stale is None else stale
    tcol_label = 1
    ws.cell(row=r, column=tcol_label, value=L["totals"]).font = Font(bold=True)
    area_key = "area_sqm" if "area_sqm" in keys else "area"
    ws.cell(row=r, column=keys.index(area_key) + 1, value=round(tot_area, 2)).number_format = "#,##0.00"
    c = ws.cell(row=r, column=keys.index("rent") + 1, value=stated_rent)
    c.number_format = "#,##0"
    c.font = Font(bold=True)
    if "deposit" in keys:
        ws.cell(row=r, column=keys.index("deposit") + 1, value=tot_dep).number_format = "#,##0"
    if "unit" in keys and keys.index("unit") != 0:
        ws.cell(row=r, column=keys.index("unit") + 1, value=f"{n_units} units")
    for j in range(1, ncol + 1):
        ws.cell(row=r, column=j).border = Border(top=Side(style="medium"), bottom=Side(style="double"))
        ws.cell(row=r, column=j).font = Font(bold=True)
    rr.summary_rows.append({"row": r, "label": L["totals"], "kind": "total", "sheet": ws.title, "scope_sum_aed": tot_rent,
                            "cell_rent": f"{ws.title}!{get_column_letter(keys.index('rent') + 1)}{r}",
                            "units": n_units, "rent_aed": stated_rent,
                            "rent_basis": "incl. vacant at asking" if L["vacant_rent"] == "asking_in_rent" else "occupied units",
                            "area": round(tot_area, 2), "area_unit": "sq m" if area_key == "area_sqm" else "sq ft",
                            "deposits_aed": tot_dep if "deposit" in keys else None})
    r += 2
    if layout_name == "pm_standard":
        occ = sum(1 for u in units if u["status"] != "vacant")
        ws.cell(row=r, column=1, value="Occupancy (units)")
        ws.cell(row=r, column=4, value=occ / len(units)).number_format = "0.0%"
        rr.summary_rows.append({"row": r, "label": "Occupancy (units)", "kind": "summary", "value": round(occ / len(units), 4)})
        r += 1
        ws.cell(row=r, column=1, value="Vacant units")
        ws.cell(row=r, column=4, value=len(units) - occ)
        rr.summary_rows.append({"row": r, "label": "Vacant units", "kind": "summary", "value": len(units) - occ})
        r += 2
    ws.cell(row=r, column=1, value=FOOTER).font = Font(italic=True, size=8, color="808080")
    ws.oddFooter.center.text = FOOTER
    ws.oddFooter.center.size = 7
    # widths
    width = {"tenant": 34, "ejari": 19, "property": 16, "remarks": 22, "note": 22, "deed": 16, "chiller": 15}
    for j, k in enumerate(keys, 1):
        ws.column_dimensions[get_column_letter(j)].width = width.get(k, 13)
    ws.freeze_panes = f"A{header_row + 1}"
    if layout_name == "bilingual":
        ws.row_dimensions[header_row].height = 44
    ws.sheet_view.showGridLines = layout_name in ("owner_simple", "owner_simple2", "pm_export")
    meta = {"document": path.name, "format": "xlsx", "sheet": ws.title, "header_row": header_row,
            "first_data_row": first_data, "last_data_row": last_data, "area_unit": "sq m" if area_key == "area_sqm" else "sq ft",
            "date_format": L["date"], "summary_rows": rr.summary_rows}
    if own_wb and finalize:
        finalize_workbook(wb, path)
    return rr, meta


# --------------------------------------------------------------------------- master lease workbook
def write_master_xlsx(path, b, spec):
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Lease"
    ml = b["master_lease"]
    rows = [
        (f"{b['name']} - Tenancy Schedule", None),
        (f"As at {spec['roll_date'].strftime('%d %B %Y')}", None),
        (None, None),
        ("Lease type", "Master (bulk) lease - whole building"),
        ("Tenant", ml["tenant"]),
        ("Units", f"All {b['unit_count']} apartments"),
        ("Lease start", datetime.fromisoformat(ml["start"])),
        ("Lease expiry", datetime.fromisoformat(ml["end"])),
        ("Annual rent (AED)", ml["annual_rent_aed"]),
        ("Payment", "Quarterly in advance (4 cheques)"),
        ("Escalation", "None - fixed rent for the term"),
        ("Ejari", f"01{ml['start'][:4]}07{random.Random(spec['seed']).randint(10**7, 10**8 - 1)}"),
        ("Tenant responsibilities", "Leasing, sub-tenancies, FM, utilities (common), cleaning, security"),
        ("Landlord responsibilities", "Building insurance, structural repairs, reserve fund, master community charges"),
        (None, None),
        ("Note", "Sub-tenancy schedule provided by the operator for information (see next sheet)."),
    ]
    for i, (k, v) in enumerate(rows, 1):
        if k:
            ws.cell(row=i, column=1, value=k).font = Font(bold=(i <= 1 or v is not None) and i != 2, size=14 if i == 1 else 10)
        if v is not None:
            c = ws.cell(row=i, column=2, value=v)
            if isinstance(v, datetime):
                c.number_format = "dd/mm/yyyy"
            if isinstance(v, int):
                c.number_format = "#,##0"
    ws.cell(row=len(rows) + 2, column=1, value=FOOTER).font = Font(italic=True, size=8, color="808080")
    ws.oddFooter.center.text = FOOTER
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 70
    rr, meta = write_rentroll_xlsx(path, b, spec, "master_sub", wb=wb, sheet_title="Operator Sub-tenancies")
    finalize_workbook(wb, path)
    meta["master_lease_sheet"] = {"sheet": "Master Lease", "rent_cell": "Master Lease!B9", "tenant_cell": "Master Lease!B5",
                                  "expiry_cell": "Master Lease!B8"}
    return rr, meta


# --------------------------------------------------------------------------- csv
def write_rentroll_csv(path, b, spec):
    rr = RR(b, spec, path.name)
    lines = [[f"{b['name']} - {b['sub_community']}"],
             [f"Rent roll as of {spec['roll_date'].strftime('%d-%m-%Y')}"], [],
             ["Unit", "Type", "Area_sqft", "Tenant", "Ejari", "Start", "End", "Annual_Rent", "Cheques", "Deposit", "Status"]]
    header_line = 4
    vocab = {"studio": "STUDIO", "1br": "1BR", "2br": "2BR", "3br": "3BR", "retail": "SHOP"}
    stat = {"occupied": "RENTED", "vacant": "VACANT", "under_renewal": "RENEWAL", "notice_served": "NOTICE", "legal_case": "LEGAL"}
    tot = 0
    for u in _units_sorted(b):
        vac = u["status"] == "vacant"
        rent = u["asking_rent_aed"] if vac else u["annual_rent_aed"]
        tot += rent
        lines.append([u["unit"], vocab[u["type"]], f"{u['area_sqft']:.1f}", u["tenant"] or "", u["ejari_no"] or "",
                      u["lease_start"].strftime("%d-%m-%Y") if u["lease_start"] else "",
                      u["lease_end"].strftime("%d-%m-%Y") if u["lease_end"] else "",
                      str(rent), str(u["cheques"] or ""), str(u["deposit_aed"] or ""), stat[u["status"]]])
        row = rr.canonical(u, area_stated=round(u["area_sqft"], 1), area_unit="sqft", cite=f"line {len(lines)}", tenant_text=u["tenant"])
        if vac:
            row["rent_column_shows"] = "asking rent"
    lines.append([])
    lines.append(["Total rent incl. vacant at asking", "", "", "", "", "", "", str(tot)])
    rr.summary_rows.append({"line": len(lines), "label": "Total rent incl. vacant at asking", "kind": "total", "rent_aed": tot,
                            "scope_sum_aed": tot, "rent_basis": "incl. vacant at asking", "units": len(b["units"])})
    lines.append([])
    lines.append([FOOTER])
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\r\n")
        for ln in lines:
            w.writerow(ln)
    meta = {"document": path.name, "format": "csv", "header_line": header_line, "first_data_line": header_line + 1,
            "last_data_line": header_line + len(b["units"]), "area_unit": "sq ft", "date_format": "%d-%m-%Y",
            "summary_rows": rr.summary_rows}
    return rr, meta


# --------------------------------------------------------------------------- pdf
def write_rentroll_pdf(path, b, spec):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle

    rr = RR(b, spec, path.name)
    hdr = ["S/N", "Flat No.", "Type", "Area (Sq.Ft.)", "Tenant Name", "Ejari No.", "From", "To", "Rent (AED)", "Chqs",
           "Deposit", "Status"]
    stat = {"occupied": "Occupied", "vacant": "Vacant", "under_renewal": "Under renewal", "notice_served": "Notice served",
            "legal_case": "Legal case"}
    tv = TYPE_VOCAB["standard"]
    units = _units_sorted(b)
    per_page = 30
    rows = []
    tot = 0
    for i, u in enumerate(units, 1):
        rows.append([str(i), u["unit"], tv[u["type"]], f"{u['area_sqft']:,.2f}",
                     Paragraph(u["tenant"] or "-", ParagraphStyle("tn", fontName="Times-Roman", fontSize=7.6, leading=8.6)),
                     u["ejari_no"] or "-",
                     u["lease_start"].strftime("%d/%m/%Y") if u["lease_start"] else "-",
                     u["lease_end"].strftime("%d/%m/%Y") if u["lease_end"] else "-",
                     f"{u['annual_rent_aed']:,}" if u["annual_rent_aed"] else "-", str(u["cheques"] or "-"),
                     f"{u['deposit_aed']:,}" if u["deposit_aed"] else "-", stat[u["status"]]])
        tot += u["annual_rent_aed"] or 0
        page = 1 + (i - 1) // per_page
        rr.canonical(u, area_stated=round(u["area_sqft"], 2), area_unit="sqft", cite=f"page {page}, row S/N {i}", tenant_text=u["tenant"])
    total_row = ["", "", "", f"{sum(u['area_sqft'] for u in units):,.2f}", "TOTAL", "", "", "", f"{tot:,}", "", "", ""]
    last_page = 1 + (len(units) - 1) // per_page
    rr.summary_rows.append({"page": last_page, "label": "TOTAL", "kind": "total", "rent_aed": tot, "scope_sum_aed": tot, "units": len(units),
                            "rent_basis": "occupied units"})

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.grey)
        c.drawCentredString(landscape(A4)[0] / 2, 8 * mm, FOOTER)
        c.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=16 * mm, title=f"{b['name']} tenancy list",
                            author="Owner's office", invariant=1)
    st = ParagraphStyle("h", fontName="Times-Bold", fontSize=13, leading=16)
    st2 = ParagraphStyle("s", fontName="Times-Roman", fontSize=9.5, leading=12)
    story = [Paragraph(f"{b['name'].upper()} - {b['sub_community'].split(',')[0].upper()}, DUBAI", st),
             Paragraph(f"Plot No. {b['plot_number']} &nbsp;&nbsp; Tenancy list as on {spec['roll_date'].strftime('%d/%m/%Y')}", st2),
             Spacer(1, 4 * mm)]
    cw = [10, 15, 17, 22, 64, 32, 20, 20, 21, 10, 17, 23]
    from reportlab.platypus import PageBreak
    chunks = [rows[i:i + per_page] for i in range(0, len(rows), per_page)]
    for ci, chunk in enumerate(chunks):
        data = [hdr] + chunk + ([total_row] if ci == len(chunks) - 1 else [])
        t = Table(data, colWidths=[w * mm for w in cw])
        style = [
            ("FONT", (0, 0), (-1, 0), "Times-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Times-Roman", 8.0),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7E6E6")),
            ("ALIGN", (3, 1), (3, -1), "RIGHT"), ("ALIGN", (8, 1), (10, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ]
        if ci == len(chunks) - 1:
            style.append(("FONT", (0, -1), (-1, -1), "Times-Bold", 8.5))
        t.setStyle(TableStyle(style))
        story.append(t)
        if ci < len(chunks) - 1:
            story.append(PageBreak())
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    meta = {"document": path.name, "format": "pdf", "rows_per_page": per_page, "area_unit": "sq ft", "date_format": "%d/%m/%Y",
            "summary_rows": rr.summary_rows}
    return rr, meta


def write_split_xlsx(path, b, spec):
    """Unit listing export split across two sheets by floor band, plus a summary sheet."""
    units = _units_sorted(b)
    floors = sorted({u["floor"] for u in units})
    cut = floors[len(floors) // 2]
    a = [u for u in units if u["floor"] < cut]
    c = [u for u in units if u["floor"] >= cut]
    name_a = f"Floors {floors[0] if floors[0] else 'G'}-{cut - 1}"
    name_c = f"Floors {cut}-{floors[-1]}"
    wb = Workbook()
    wb.remove(wb.active)
    rr, meta_a = write_rentroll_xlsx(path, b, spec, "export_split", wb=wb, sheet_title=name_a, units_subset=a, finalize=False)
    rr, meta_c = write_rentroll_xlsx(path, b, spec, "export_split", wb=wb, sheet_title=name_c, units_subset=c, rr=rr, finalize=False)
    ws = wb.create_sheet("Summary", 0)
    occ = [u for u in units if u["status"] != "vacant"]
    rows = [("Property", b["name"]), ("Export date", spec["roll_date"].strftime("%d-%b-%Y")), (None, None),
            ("Units (all sheets)", len(units)), ("Let units", len(occ)), ("Vacant units", len(units) - len(occ)),
            ("Contract rent, let units (AED)", sum(u["annual_rent_aed"] for u in occ)), (None, None),
            ("Sheets", f"{name_a}; {name_c}")]
    for i, (k, v) in enumerate(rows, 1):
        if k:
            ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        if v is not None:
            c_ = ws.cell(row=i, column=2, value=v)
            if isinstance(v, int) and v > 1000:
                c_.number_format = "#,##0"
    ws.cell(row=len(rows) + 2, column=1, value=FOOTER).font = Font(italic=True, size=8, color="808080")
    ws.oddFooter.center.text = FOOTER
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 36
    tot = sum(u["annual_rent_aed"] for u in occ)
    rr.summary_rows.append({"row": 7, "sheet": "Summary", "label": "Contract rent, let units (AED)", "kind": "total",
                            "rent_aed": tot, "scope_sum_aed": tot, "units": len(units)})
    finalize_workbook(wb, path)
    meta = {"document": path.name, "format": "xlsx", "sheets": [meta_a, meta_c], "summary_sheet": "Summary",
            "area_unit": "sq ft", "date_format": "%d-%b-%Y",
            "note": "Units are split across two sheets by floor band; each has its own header and sheet total.",
            "summary_rows": rr.summary_rows}
    return rr, meta


def write_rentroll_pdf_spanning(path, b, spec, *, area_in_sqm_labelled_sqft=False, stale=None):
    """One long table flowing across pages (header repeated), as exported from a PM system to PDF."""
    import pymupdf
    import re as _re
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rr = RR(b, spec, path.name)
    hdr = ["#", "Unit", "Type", "Area (sq ft)", "Tenant", "Ejari", "Start", "Expiry", "Rent AED", "Chq", "Status"]
    stat = {"occupied": "Let", "vacant": "Vacant", "under_renewal": "Renewal", "notice_served": "Notice", "legal_case": "Legal"}
    tv = TYPE_VOCAB["code"]
    units = _units_sorted(b)
    data = [hdr]
    tot = 0
    area_tot = 0.0
    pst = ParagraphStyle("t", fontName="Helvetica", fontSize=6.6, leading=7.6)
    for i, u in enumerate(units, 1):
        area = round(u["area_sqft"] / SQM, 1) if area_in_sqm_labelled_sqft else round(u["area_sqft"], 1)
        area_tot += area
        data.append([str(i), u["unit"], tv[u["type"]], f"{area:,.1f}", Paragraph(u["tenant"] or "", pst), u["ejari_no"] or "",
                     u["lease_start"].strftime("%d.%m.%Y") if u["lease_start"] else "", u["lease_end"].strftime("%d.%m.%Y") if u["lease_end"] else "",
                     f"{u['annual_rent_aed']:,}" if u["annual_rent_aed"] else "", str(u["cheques"] or ""), stat[u["status"]]])
        tot += u["annual_rent_aed"] or 0
        row = rr.canonical(u, area_stated=area, area_unit="sqm" if area_in_sqm_labelled_sqft else "sqft", cite=None, tenant_text=u["tenant"])
        if area_in_sqm_labelled_sqft:
            row["area_original"] = {"value": area, "unit": "sq m", "header_says": "sq ft"}
    stated = tot if stale is None else stale
    data.append(["", "", "TOTAL", f"{area_tot:,.1f}", "", "", "", "", f"{stated:,}", "", ""])

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 6.8)
        c.setFillColor(colors.grey)
        c.drawCentredString(A4[0] / 2, 8 * mm, FOOTER)
        c.drawRightString(A4[0] - 12 * mm, 8 * mm, f"Page {d.page}")
        c.drawString(12 * mm, A4[1] - 9 * mm, f"{b['name']} - rent roll export {spec['roll_date'].strftime('%d.%m.%Y')}")
        c.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"{b['name']} rent roll", author="PM system", invariant=1)
    t = Table(data, colWidths=[w * mm for w in [8, 12, 10, 18, 48, 26, 17, 17, 18, 8, 12]], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 6.6), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 6.8),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E1F2")), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("ALIGN", (3, 1), (3, -1), "RIGHT"), ("ALIGN", (8, 1), (8, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 6.8), ("TOPPADDING", (0, 0), (-1, -1), 1.2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2)]))
    ps = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11, leading=14)
    doc.build([Paragraph(f"{b['name']} - Rent Roll", ps), Spacer(1, 3 * mm), t], onFirstPage=footer, onLaterPages=footer)
    # find each row's page in the rendered text
    pages = [_re.sub(r"\s+", " ", p.get_text()) for p in pymupdf.open(str(path))]
    last = 1
    for i, row in enumerate(rr.rows, 1):
        pat = f" {i} {row['unit']} "
        hit = next((k + 1 for k, t_ in enumerate(pages) if pat in " " + t_ + " "), last)
        row["source"] = f"page {hit}, row {i}"
        last = hit
    rr.summary_rows.append({"page": len(pages), "label": "TOTAL", "kind": "total", "rent_aed": stated, "scope_sum_aed": tot,
                            "units": len(units), "rent_basis": "let units"})
    meta = {"document": path.name, "format": "pdf", "pages": len(pages), "area_unit": "sq m" if area_in_sqm_labelled_sqft else "sq ft",
            "area_unit_label": "sq ft", "date_format": "%d.%m.%Y", "summary_rows": rr.summary_rows,
            "note": "Single table flowing across pages with the header repeated."}
    return rr, meta
