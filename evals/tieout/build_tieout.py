"""Build the independent Excel tie-out of the underwriting engine for one deal.

The workbook is written from the method in engine/README.md and the raw inputs
(the deal fixture, data/mandate.yaml, data/market/areas.yaml). No engine code is
imported or copied: the engine is used only as a black box, through the JSON it
prints (`python -m engine <fixture> --json`), and its numbers appear only on the
EngineOutput sheet, where the TieOut sheet compares them with the workbook's own
formulas.

Usage (from the repo root):
    python -m engine tests/engine/fixtures/jvc_60_units.json --json > evals/tieout/engine_output_jvc_60_units.json
    python evals/tieout/build_tieout.py
    python <xlsx skill>/scripts/recalc.py evals/tieout/tieout_jvc_60_units.xlsx 120
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as CL
from openpyxl.workbook.defined_name import DefinedName

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tests/engine/fixtures/jvc_60_units.json"
MANDATE = ROOT / "data/mandate.yaml"
AREAS = ROOT / "data/market/areas.yaml"
ENGINE_JSON = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).with_name("engine_output_jvc_60_units.json")
OUT = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path(__file__).with_name("tieout_jvc_60_units.xlsx")

deal = json.loads(FIXTURE.read_text())
mandate = yaml.safe_load(MANDATE.read_text())
market = yaml.safe_load(AREAS.read_text())
engine = json.loads(ENGINE_JSON.read_text())["underwriting"]

uw = mandate["underwriting"]
ops, debt, acq, mv, rera = uw["operations"], uw["debt"], uw["acquisition_costs"], uw["market_view"], uw["rera"]
area = deal["area"]
mkt_area = market["areas"][area]

# ---------------------------------------------------------------- styles
FONT = "Arial"
F_BASE = Font(name=FONT, size=10)
F_INPUT = Font(name=FONT, size=10, color="0000FF")
F_LINK = Font(name=FONT, size=10, color="008000")
F_BOLD = Font(name=FONT, size=10, bold=True)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT, size=13, bold=True)
F_NOTE = Font(name=FONT, size=9, italic=True, color="555555")
FILL_HEAD = PatternFill("solid", fgColor="1F3864")
FILL_SUB = PatternFill("solid", fgColor="D9E1F2")
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
FILL_PASS = PatternFill("solid", fgColor="C6EFCE")
THIN = Side(style="thin", color="999999")
TOP = Border(top=THIN)

AED = '#,##0;(#,##0);"-"'
AED2 = '#,##0.00;(#,##0.00);"-"'
PCT = '0.00%;(0.00%);"-"'
PCT4 = '0.0000%;(0.0000%);"-"'
MULT = '0.000"x"'
DATE = "yyyy-mm-dd"
GEN = "General"

wb = Workbook()
wb.remove(wb.active)


def style(cell, font=F_BASE, fmt=None, fill=None, bold=False):
    cell.font = Font(name=FONT, size=font.size, color=font.color, bold=bold or font.bold, italic=font.italic)
    if fmt:
        cell.number_format = fmt
    if fill:
        cell.fill = fill
    return cell


def put(ws, ref, value, font=F_BASE, fmt=None, fill=None, bold=False):
    c = ws[ref]
    c.value = value
    return style(c, font, fmt, fill, bold)


def header_row(ws, row, labels, start_col=1, fill=FILL_HEAD, font=F_HEAD):
    for i, lab in enumerate(labels):
        c = ws.cell(row=row, column=start_col + i, value=lab)
        c.font = font
        c.fill = fill
        c.alignment = Alignment(wrap_text=True, vertical="center")


def name(nm, sheet, ref):
    wb.defined_names[nm] = DefinedName(nm, attr_text=f"{sheet}!{ref}")


# ======================================================================= Inputs
wsI = wb.create_sheet("Inputs")
wsI.column_dimensions["A"].width = 44
wsI.column_dimensions["B"].width = 18
wsI.column_dimensions["C"].width = 12
wsI.column_dimensions["D"].width = 30
wsI.column_dimensions["E"].width = 90
put(wsI, "A1", "Inputs: deal, mandate and market assumptions used by the tie-out", F_TITLE)
put(wsI, "A2", "Blue = hard-coded input copied from the named source file. Black = formula. Every model cell on the other sheets refers back here (named ranges).", F_NOTE)
header_row(wsI, 4, ["Input", "Value", "Unit", "Name (used in formulas)", "Source"])

try:
    FIX = str(FIXTURE.relative_to(ROOT))
except ValueError:
    FIX = FIXTURE.name
MAN = "data/mandate.yaml"
ARE = "data/market/areas.yaml"
ERM = "engine/README.md"

row = 5


def section(title):
    global row
    row += 1
    c = wsI.cell(row=row, column=1, value=title)
    c.font = F_BOLD
    c.fill = FILL_SUB
    for col in range(2, 6):
        wsI.cell(row=row, column=col).fill = FILL_SUB
    row += 1


def inp(label, value, unit, nm, source, fmt=GEN, formula=False, key=False):
    """One input row. Returns the absolute cell ref of the value."""
    global row
    put(wsI, f"A{row}", label)
    put(wsI, f"B{row}", value, F_BASE if formula else F_INPUT, fmt, FILL_KEY if key else None)
    put(wsI, f"C{row}", unit)
    put(wsI, f"D{row}", nm or "")
    put(wsI, f"E{row}", source, F_NOTE)
    ref = f"$B${row}"
    if nm:
        name(nm, "Inputs", ref)
    row += 1
    return ref


section("Deal (fixture)")
inp("Deal id", deal["deal_id"], "", None, f"{FIX}: deal_id")
inp("Price", deal["price_aed"], "AED", "Price", f"{FIX}: price_aed", AED, key=True)
inp("Area", area, "", "AreaName", f"{FIX}: area")
inp("NSA", deal["nsa_sqft"], "sq ft", "NSA", f"{FIX}: nsa_sqft", AED)
inp("BUA", deal["bua_sqft"], "sq ft", "BUA", f"{FIX}: bua_sqft", AED)
inp("Completion year", deal["completion_year"], "year", "CompletionYear", f"{FIX}: completion_year")
inp("Rent roll date", dt.date.fromisoformat(deal["rent_roll_date"]), "date", "RentRollDate", f"{FIX}: rent_roll_date", DATE)
inp("Other income, Year 1", deal["other_income_aed"], "AED/yr", "OtherIncome", f"{FIX}: other_income_aed", AED)
inp("Chiller: landlord pays cooling?", {False: "FALSE", True: "TRUE", None: ""}[deal.get("chiller_landlord_pays")], "flag", "ChillerLandlordPays", f"{FIX}: chiller_landlord_pays (false = not a chiller-free building; no cooling default)")
inp("Stated opex includes VAT?", "TRUE" if deal.get("opex_includes_vat") else "FALSE", "flag", "OpexInclVAT", f"{FIX}: opex_includes_vat not given; README default false")
_clo = deal.get("collection_loss_override")
inp("Collection loss override", "" if _clo is None else _clo, "ratio", "CollLossOverride", f"{FIX}: collection_loss_override" + (" not given, so the mandate rate applies" if _clo is None else ""), PCT)
inp("Number of units", "=COUNTA(Units!$A$8:$A$67)", "units", "UnitCount", "Formula: rows on Units", formula=True)

section("Stated operating costs, Year 1 (fixture opex_aed; blank = not stated)")
opex_stated = deal.get("opex_aed", {})
OPEX_CATS = [
    ("service_charge", "Service charge", None),
    ("district_cooling", "District cooling", "district_cooling_if_landlord_pays"),
    ("utilities_common", "Utilities (common)", "utilities_common"),
    ("maintenance_repairs", "Maintenance and repairs", "maintenance_repairs"),
    ("insurance", "Insurance", "insurance"),
    ("security_cleaning", "Security and cleaning", "security_cleaning"),
    ("marketing_leasing", "Marketing and leasing", None),
    ("admin_other", "Admin and other", "admin_other"),
    ("sinking_fund", "Sinking fund", "sinking_fund"),
]
for key, lab, _ in OPEX_CATS:
    v = opex_stated.get(key)
    inp(f"Stated: {lab}", "" if v is None else v, "AED/yr", f"Stated_{key}",
        f"{FIX}: opex_aed.{key}" + (" (not stated)" if v is None else ""), AED)

section("Market (areas.yaml)")
inp(f"Screen reference rent, 1BR, {area}", mkt_area["market_rent_aed_psf_1br"], "AED/sqft/yr", "RefPsf1BR", f"{ARE}: areas.{area}.market_rent_aed_psf_1br", AED2, key=True)
tf_start = row
for t, f in market["unit_type_factors"].items():
    inp(f"Unit-type factor: {t}", f, "x", None, f"{ARE}: unit_type_factors.{t}", "0.00")
tf_end = row - 1
# lookup table: keys in column A text after the colon -> use a helper column C? keep simple: put keys in col D
for r_, t in zip(range(tf_start, tf_end + 1), market["unit_type_factors"].keys()):
    wsI[f"D{r_}"].value = t
name("TypeKeys", "Inputs", f"$D${tf_start}:$D${tf_end}")
name("TypeFactors", "Inputs", f"$B${tf_start}:$B${tf_end}")
put(wsI, f"E{tf_end}", f"{ARE}: unit_type_factors.retail. Column D holds the lookup keys (TypeKeys / TypeFactors).", F_NOTE)

section("Timeline (mandate)")
inp("Analysis start", dt.date.fromisoformat(uw["analysis_start"]), "date", "AnalysisStart", f"{MAN}: underwriting.analysis_start", DATE)
inp("Hold", uw["hold_years"], "years", "HoldYears", f"{MAN}: underwriting.hold_years")

section("Reference rent path (mandate market_view.rent_growth_by_year.default; JVC has no area-specific path)")
put(wsI, f"A{row}", "Year")
put(wsI, f"B{row}", "Growth")
put(wsI, f"C{row}", "Cum. factor", F_BASE)
put(wsI, f"E{row}", "Cum. factor for year t = product of (1+g1..gt): year 1 already carries the first change (README 'Screen reference rent').", F_NOTE)
row += 1
g_start = row
for i, gval in enumerate(mv["rent_growth_by_year"]["default"]):
    put(wsI, f"A{row}", i + 1)
    put(wsI, f"B{row}", gval, F_INPUT, PCT)
    put(wsI, f"C{row}", f"=(1+B{row})" if i == 0 else f"=C{row-1}*(1+B{row})", F_BASE, "0.000000")
    put(wsI, f"E{row}", f"{MAN}: underwriting.market_view.rent_growth_by_year.default[{i}]", F_NOTE)
    row += 1
name("RefPath", "Inputs", f"$C${g_start}:$C${row-1}")

section("Leasing and operations (mandate underwriting.operations)")
inp("Renewal probability", ops["renewal_probability"], "ratio", "RenewProb", f"{MAN}: operations.renewal_probability", PCT, key=True)
inp("Downtime on turnover", ops["downtime_months_on_turnover"], "months", "Downtime", f"{MAN}: operations.downtime_months_on_turnover", "0.00")
inp("Leasing fee on turnover", ops["leasing_fee_months_on_turnover"], "months of new rent", "LeaseFeeMonths", f"{MAN}: operations.leasing_fee_months_on_turnover", "0.00")
inp("Structural vacancy allowance", ops["structural_vacancy"], "ratio", "StructVac", f"{MAN}: operations.structural_vacancy", PCT)
inp("Collection loss (mandate)", ops["collection_loss"], "ratio", "CollLossMandate", f"{MAN}: operations.collection_loss", PCT)
inp("Collection loss applied", "=IF(ISNUMBER(CollLossOverride),CollLossOverride,CollLossMandate)", "ratio", "CollLoss", "Formula: deal override if given, else mandate", PCT, formula=True)
inp("Property management fee", ops["property_management_pct_of_egi"], "of EGI", "MgmtPct", f"{MAN}: operations.property_management_pct_of_egi", PCT)
inp("Input VAT on costs", ops["input_vat_on_opex_pct"], "ratio", "VATPct", f"{MAN}: operations.input_vat_on_opex_pct", PCT)
inp("Opex growth (from Year 2)", ops["opex_growth"], "ratio/yr", "OpexGrowth", f"{MAN}: operations.opex_growth", PCT)
inp("Other income growth (from Year 2)", ops["other_income_growth"], "ratio/yr", "OIGrowth", f"{MAN}: operations.other_income_growth", PCT)

section("Opex defaults per sq ft NSA (mandate operations.opex_defaults_aed_per_sqft_nsa; used only for unstated lines)")
dflt = ops["opex_defaults_aed_per_sqft_nsa"]
for key, lab, dkey in OPEX_CATS:
    if dkey is None:
        inp(f"Default: {lab}", 0, "AED/sqft", f"Default_{key}", f"No mandate default for {key}: README says a missing line with no default is 0", AED2)
    else:
        inp(f"Default: {lab}", dflt[dkey], "AED/sqft", f"Default_{key}", f"{MAN}: opex_defaults_aed_per_sqft_nsa.{dkey}", AED2)

section("Sinking fund age multiplier (engine constant SINKING_FUND_AGE_MULTIPLIERS, README 'Engine constants')")
inp("Multiplier, age under 10", 1.0, "x", "SF_Mult_u10", f"{ERM}: x1.0 under 10 years", "0.00")
inp("Multiplier, age 10-19", 1.5, "x", "SF_Mult_10_19", f"{ERM}: x1.5 for 10-19 years", "0.00")
inp("Multiplier, age 20+", 2.0, "x", "SF_Mult_20", f"{ERM}: x2.0 for 20 years and over (also when age unknown)", "0.00")
inp("Building age at analysis start", "=YEAR(AnalysisStart)-CompletionYear", "years", "AgeStart", "Formula: start year - completion year (README 'Building age')", "0", formula=True)
inp("Building age at exit", "=YEAR(AnalysisStart)+HoldYears-CompletionYear", "years", "AgeExit", "Formula: start year + hold - completion year", "0", formula=True)
inp("Sinking fund multiplier applied", "=IF(AgeStart>=20,SF_Mult_20,IF(AgeStart>=10,SF_Mult_10_19,SF_Mult_u10))", "x", "SF_Mult", "Formula", "0.00", formula=True)

section("RERA renewal bands (mandate underwriting.rera; Decree 43 of 2013, applied to the screen reference as proxy)")
put(wsI, f"A{row}", "Gap below reference, up to (inclusive)")
put(wsI, f"B{row}", "Max increase")
row += 1
b_start = row
for b in rera["increase_bands"]:
    put(wsI, f"A{row}", b["below_index_up_to"], F_INPUT, PCT)
    put(wsI, f"B{row}", b["max_increase"], F_INPUT, PCT)
    put(wsI, f"E{row}", f"{MAN}: rera.increase_bands", F_NOTE)
    row += 1
name("BandUpTo", "Inputs", f"$A${b_start}:$A${row-1}")
name("BandInc", "Inputs", f"$B${b_start}:$B${row-1}")
inp("Notice days for change", rera["notice_days_for_change"], "days", "NoticeDays", f"{MAN}: rera.notice_days_for_change", "0")
inp("Notice window (expiry months with no increase: month index < this)", "=NoticeDays/30", "months", "NoticeMonths", "Formula. README: expiries in months 0-2 after the analysis start get no increase (90 days = 3 months)", "0.00", formula=True)

section("Acquisition costs (mandate underwriting.acquisition_costs)")
inp("DLD transfer fee", acq["dld_transfer_fee_pct"], "of price", "DLDPct", f"{MAN}: acquisition_costs.dld_transfer_fee_pct", PCT)
inp("DLD admin", acq["dld_admin_aed"], "AED", "DLDAdmin", f"{MAN}: acquisition_costs.dld_admin_aed", AED)
inp("Trustee fee", acq["trustee_fee_aed"], "AED", "TrusteeFee", f"{MAN}: acquisition_costs.trustee_fee_aed", AED)
inp("Broker fee", acq["broker_fee_pct"], "of price", "BrokerPct", f"{MAN}: acquisition_costs.broker_fee_pct", PCT)
inp("VAT on broker fee", acq["broker_fee_vat_pct"], "of broker fee", "BrokerVATPct", f"{MAN}: acquisition_costs.broker_fee_vat_pct", PCT)
inp("Mortgage registration", acq["mortgage_registration_pct"], "of loan", "MortRegPct", f"{MAN}: acquisition_costs.mortgage_registration_pct", PCT4)
inp("Mortgage registration admin", acq["mortgage_registration_admin_aed"], "AED", "MortRegAdmin", f"{MAN}: acquisition_costs.mortgage_registration_admin_aed", AED)

section("Debt (mandate underwriting.debt)")
inp("Max LTV", debt["max_ltv"], "of price", "MaxLTV", f"{MAN}: debt.max_ltv", PCT, key=True)
inp("Sizing DSCR", debt["sizing_dscr"], "x", "SizingDSCR", f"{MAN}: debt.sizing_dscr", MULT, key=True)
inp("3M EIBOR (held flat)", debt["base_rate_3m_eibor"], "ratio", "EIBOR", f"{MAN}: debt.base_rate_3m_eibor ({debt['rate_note']})", PCT)
inp("Margin", debt["margin"], "ratio", "Margin", f"{MAN}: debt.margin", PCT)
inp("Interest rate", "=EIBOR+Margin", "ratio", "Rate", "Formula: EIBOR + margin", PCT, formula=True)
inp("Amortisation", debt["amortisation_years"], "years", "AmortYears", f"{MAN}: debt.amortisation_years", "0")
inp("Arrangement fee", debt["arrangement_fee_pct"], "of loan", "ArrFeePct", f"{MAN}: debt.arrangement_fee_pct", PCT)

section("Exit (mandate underwriting.market_view)")
inp(f"Area house-view exit yield, {area}", mv["exit_net_yield_by_area"][area], "ratio", "AreaExitYield", f"{MAN}: market_view.exit_net_yield_by_area.{area}", PCT)
inp("Exit yield expansion", mv["exit_yield_expansion_bps"], "bps", "ExitExpBps", f"{MAN}: market_view.exit_yield_expansion_bps", "0")
inp("Exit age premium", mv["exit_age_premium_bps"], "bps", "AgePremBps", f"{MAN}: market_view.exit_age_premium_bps", "0")
inp("Age premium applies from", mv["exit_age_premium_from_years"], "years at exit", "AgePremFrom", f"{MAN}: market_view.exit_age_premium_from_years", "0")
inp("Selling costs", mv["selling_costs_pct"], "of gross exit value", "SellPct", f"{MAN}: market_view.selling_costs_pct", PCT)
put(wsI, f"A{row}", "Exit yield rule (mandate text):", F_BOLD)
put(wsI, f"E{row}", mv["exit_yield_rule"], F_NOTE)
row += 1

section("Buy box parameters used (mandate buy_box.soft)")
inp("Over-rent threshold", mandate["buy_box"]["soft"]["over_rent_threshold"], "ratio", "OverRentThr", f"{MAN}: buy_box.soft.over_rent_threshold", PCT)
inp("Target unlevered IRR (walk-away test)", mandate["buy_box"]["soft"]["target_unlevered_irr"], "ratio", "TargetIRR", f"{MAN}: buy_box.soft.target_unlevered_irr", PCT)
wsI.freeze_panes = "A5"

# ======================================================================= Units
wsU = wb.create_sheet("Units")
FIRST, N = 8, len(deal["units"])
LAST = FIRST + N - 1
TOT = LAST + 2

put(wsU, "A1", "Units: per-unit lease logic, expected-value blend of renewal (RERA band on the tenant's own rent) and turnover (re-let at reference after downtime)", F_TITLE)
notes = [
    "Each unit's leases roll every 12 months from its roll month M0 (day after lease end, rounded to the nearest month start: day 1-15 that month, day 16+ the next). Vacant units lease up in month 0 (an expiry with renewal probability 0).",
    "Expiry block j: tenant 'chains' are the possible tenants in place. Chain 0 = the current tenant; chain i = the tenant who arrived by turnover at expiry i. At each expiry every chain renews with prob p (rent: reset to reference if above it; else +RERA band on its own gap, capped at reference; no increase inside the notice window) or turns over (re-let at that year's reference).",
    "Expected rent after expiry j = sum(weight x chain rent). Annual potential rent = months before the expiry at the old blend + months after at the new blend. Downtime: turnover share x reference/12 x downtime months, spilling into the next year if the expiry is late in the year. Leasing fee: turnover share x fee months x reference/12 in the re-let month.",
]
for i, t in enumerate(notes):
    put(wsU, f"A{2+i}", t, F_NOTE)

fixed = ["Unit", "Unit type", "Area (sq ft)", "Status", "In-place rent (AED/yr)", "Lease end",
         "Type factor", "Screen reference rent, as-of (AED/yr)", "Rent vs reference", "Over-rented (> threshold)?",
         "In-place rent counted (AED/yr)", "Roll date (lease end + 1)", "Roll month M0 (0 = Jan 2027)",
         "Month-in-year of expiries k", "Year shift (INT(M0/12))", "Renewal prob. at first expiry", "Rent before first expiry E0"]
col = {}
for i, h in enumerate(fixed):
    col[h] = i + 1
header_row(wsU, 7, fixed)
c_next = len(fixed) + 1

# expiry blocks
blk = {}
for j in range(1, 7):
    b = {}
    start = c_next
    for lab in ["m", "yr", "ref", "p", "win", "turn"]:
        b[lab] = c_next
        c_next += 1
    b["chain"] = []
    for v in range(j + 1):
        b["chain"].append(c_next)
        c_next += 1
    b["w"] = []
    for v in range(j + 1):
        b["w"].append(c_next)
        c_next += 1
    b["E"] = c_next
    c_next += 1
    blk[j] = b
    heads = [f"Exp {j}: month index", f"Exp {j}: year", f"Exp {j}: reference rent that year", f"Exp {j}: renewal prob.",
             f"Exp {j}: in notice window?", f"Exp {j}: turnover-weighted ref. (1-p) x ref"]
    heads += [f"Exp {j}: rent, chain {v}" + (" (current tenant)" if v == 0 else f" (in by turnover at exp {v})") for v in range(j + 1)]
    heads += [f"Exp {j}: weight, chain {v}" for v in range(j + 1)]
    heads += [f"Exp {j}: EXPECTED RENT AFTER"]
    header_row(wsU, 7, heads, start_col=start, fill=FILL_HEAD if j % 2 else PatternFill("solid", fgColor="2E75B6"))
    wsU.cell(row=6, column=start, value=f"Expiry {j}").font = F_BOLD

# year blocks
yb = {}
for y in range(1, 7):
    b = {}
    start = c_next
    for lab in ["jy", "Ebef", "Eaft", "pot", "dt", "fee", "net"]:
        b[lab] = c_next
        c_next += 1
    yb[y] = b
    heads = [f"Y{y}: expiry # in year", f"Y{y}: expected rent before expiry", f"Y{y}: expected rent after expiry",
             f"Y{y}: POTENTIAL RENT (AED)", f"Y{y}: DOWNTIME LOSS (AED)", f"Y{y}: LEASING FEE (AED)", f"Y{y}: expected rent net of downtime"]
    header_row(wsU, 7, heads, start_col=start, fill=PatternFill("solid", fgColor="375623"))
    wsU.cell(row=6, column=start, value=f"Year {y}").font = F_BOLD
c_chk = c_next
header_row(wsU, 7, ["Sum |workbook - engine| expected rent net of downtime, Y1-Y6 (AED)"], start_col=c_chk, fill=PatternFill("solid", fgColor="7F6000"))
c_retail = c_chk + 1
header_row(wsU, 7, ["Retail? (VAT recovery)"], start_col=c_retail)

L = lambda h: CL(col[h])


def band_expr(prev, ref):
    # increase for gap=(ref-prev)/ref: first band whose inclusive upper bound >= gap
    return f"INDEX(BandInc,SUMPRODUCT(--(BandUpTo<({ref}-{prev})/{ref}))+1)"


for i, u in enumerate(deal["units"]):
    r = FIRST + i
    put(wsU, f"A{r}", u["unit"], F_INPUT)
    put(wsU, f"B{r}", u["unit_type"].lower().replace(" ", ""), F_INPUT)
    put(wsU, f"C{r}", u["area_sqft"], F_INPUT, AED)
    put(wsU, f"D{r}", u["status"], F_INPUT)
    put(wsU, f"E{r}", u["annual_rent_aed"] if u["annual_rent_aed"] is not None else "", F_INPUT, AED)
    put(wsU, f"F{r}", dt.date.fromisoformat(u["lease_end"]) if u["lease_end"] else "", F_INPUT, DATE)
    if i == 0:
        wsU[f"A{r}"].comment = Comment(f"Columns A-F: rent roll copied from {FIX} (units[]).", "tie-out")
    put(wsU, f"G{r}", f"=INDEX(TypeFactors,MATCH(B{r},TypeKeys,0))", F_LINK, "0.00")
    put(wsU, f"H{r}", f"=RefPsf1BR*G{r}*C{r}", F_BASE, AED)
    put(wsU, f"I{r}", f'=IF(D{r}="vacant","",E{r}/H{r}-1)', F_BASE, PCT)
    put(wsU, f"J{r}", f'=IF(D{r}="vacant",FALSE,E{r}>H{r}*(1+OverRentThr))', F_BASE)
    put(wsU, f"K{r}", f'=IF(OR(D{r}="vacant",D{r}="legal_case"),0,E{r})', F_BASE, AED)
    put(wsU, f"L{r}", f'=IF(D{r}="vacant","",F{r}+1)', F_BASE, DATE)
    put(wsU, f"M{r}", f'=IF(D{r}="vacant",0,MAX(0,(YEAR(L{r})-YEAR(AnalysisStart))*12+MONTH(L{r})-MONTH(AnalysisStart)+IF(DAY(L{r})>15,1,0)))', F_BASE, "0")
    put(wsU, f"N{r}", f"=MOD(M{r},12)", F_BASE, "0")
    put(wsU, f"O{r}", f"=INT(M{r}/12)", F_BASE, "0")
    put(wsU, f"P{r}", f'=IF(OR(D{r}="vacant",D{r}="notice_served"),0,RenewProb)', F_BASE, PCT)
    put(wsU, f"Q{r}", f'=IF(D{r}="vacant",0,E{r})', F_BASE, AED)

    for j in range(1, 7):
        b = blk[j]
        m, yr, ref, p, win, turn = (f"{CL(b[k])}{r}" for k in ["m", "yr", "ref", "p", "win", "turn"])
        put(wsU, m, f"=M{r}+12*{j-1}", F_BASE, "0")
        put(wsU, yr, f"=INT({m}/12)+1", F_BASE, "0")
        put(wsU, ref, f"=H{r}*INDEX(RefPath,MIN({yr},6))", F_BASE, AED2)
        put(wsU, p, f"=P{r}" if j == 1 else "=RenewProb", F_BASE, PCT)
        put(wsU, win, f"={m}<NoticeMonths", F_BASE)
        put(wsU, turn, f"=(1-{p})*{ref}", F_BASE, AED2)
        for v in range(j + 1):
            cc = f"{CL(b['chain'][v])}{r}"
            if v == j:
                put(wsU, cc, f"={ref}", F_BASE, AED2)
            else:
                prev = f"Q{r}" if j == 1 else f"{CL(blk[j-1]['chain'][v])}{r}"
                put(wsU, cc, f"=IF({prev}>{ref},{ref},IF({win},{prev},MIN({ref},{prev}*(1+{band_expr(prev, ref)}))))", F_BASE, AED2)
            wc = f"{CL(b['w'][v])}{r}"
            if v == j:
                put(wsU, wc, f"=1-{p}", F_BASE, "0.0000")
            else:
                prevw = "1" if j == 1 else f"{CL(blk[j-1]['w'][v])}{r}"
                put(wsU, wc, f"={prevw}*{p}", F_BASE, "0.0000")
        c0, c1 = CL(b["chain"][0]), CL(b["chain"][-1])
        w0, w1 = CL(b["w"][0]), CL(b["w"][-1])
        put(wsU, f"{CL(b['E'])}{r}", f"=SUMPRODUCT({c0}{r}:{c1}{r},{w0}{r}:{w1}{r})", F_BOLD, AED2)

    Es = [f"{CL(blk[j]['E'])}{r}" for j in range(1, 7)]
    Ts = [f"{CL(blk[j]['turn'])}{r}" for j in range(1, 7)]
    for y in range(1, 7):
        b = yb[y]
        jy, eb, ea, pot, dtc, fee, net = (f"{CL(b[k])}{r}" for k in ["jy", "Ebef", "Eaft", "pot", "dt", "fee", "net"])
        put(wsU, jy, f"={y}-O{r}", F_BASE, "0")
        put(wsU, eb, f"=IF({jy}<=1,Q{r},CHOOSE({jy}-1,{','.join(Es[:5])}))", F_BASE, AED2)
        put(wsU, ea, f"=IF({jy}<1,Q{r},CHOOSE({jy},{','.join(Es)}))", F_BASE, AED2)
        put(wsU, pot, f"=IF({jy}<1,Q{r},(N{r}*{eb}+(12-N{r})*{ea})/12)", F_BOLD, AED2)
        put(wsU, dtc, (f"=IF({jy}<1,0,CHOOSE({jy},{','.join(Ts)})*MIN(Downtime,12-N{r})/12)"
                       f"+IF({jy}<2,0,CHOOSE({jy}-1,{','.join(Ts[:5])})*MAX(0,Downtime-(12-N{r}))/12)"), F_BOLD, AED2)
        put(wsU, fee, (f"=LeaseFeeMonths/12*IF(N{r}+INT(Downtime)<12,"
                       f"IF({jy}<1,0,CHOOSE({jy},{','.join(Ts)})),"
                       f"IF({jy}<2,0,CHOOSE({jy}-1,{','.join(Ts[:5])})))"), F_BOLD, AED2)
        put(wsU, net, f"={pot}-{dtc}", F_BASE, AED2)
    nets = [f"{CL(yb[y]['net'])}{r}" for y in range(1, 7)]
    eo_row = r  # EngineOutput per-unit rows are aligned with Units rows
    put(wsU, f"{CL(c_chk)}{r}", "=" + "+".join(f"ABS({nets[y]}-EngineOutput!{CL(3+y)}{eo_row})" for y in range(6)), F_BASE, AED2)
    put(wsU, f"{CL(c_retail)}{r}", f'=B{r}="retail"', F_BASE)

# totals
put(wsU, f"A{TOT}", "Total / check", F_BOLD)
for h in ["Area (sq ft)", "In-place rent (AED/yr)", "Screen reference rent, as-of (AED/yr)", "In-place rent counted (AED/yr)"]:
    cl = L(h)
    put(wsU, f"{cl}{TOT}", f"=SUM({cl}{FIRST}:{cl}{LAST})", F_BOLD, AED)
for y in range(1, 7):
    for k in ["pot", "dt", "fee", "net"]:
        cl = CL(yb[y][k])
        put(wsU, f"{cl}{TOT}", f"=SUM({cl}{FIRST}:{cl}{LAST})", F_BOLD, AED)
put(wsU, f"{CL(c_chk)}{TOT}", f"=SUM({CL(c_chk)}{FIRST}:{CL(c_chk)}{LAST})", F_BOLD, AED2)
for c in range(1, c_next + 2):
    wsU.cell(row=TOT, column=c).border = TOP
wsU.freeze_panes = wsU.cell(row=FIRST, column=5)
for c in range(1, c_next + 2):
    wsU.column_dimensions[CL(c)].width = 13
wsU.column_dimensions["A"].width = 8
wsU.column_dimensions["D"].width = 13
wsU.row_dimensions[7].height = 80

# Rent-roll statistics block (below totals)
rs = TOT + 3
put(wsU, f"A{rs}", "Rent-roll statistics", F_BOLD)
stats = [
    ("Occupancy by units (excl. vacant and legal case)", f'=(COUNTA(A{FIRST}:A{LAST})-COUNTIF(D{FIRST}:D{LAST},"vacant")-COUNTIF(D{FIRST}:D{LAST},"legal_case"))/COUNTA(A{FIRST}:A{LAST})', PCT, "OccUnits"),
    ("Occupancy by area", f'=(SUM(C{FIRST}:C{LAST})-SUMIF(D{FIRST}:D{LAST},"vacant",C{FIRST}:C{LAST})-SUMIF(D{FIRST}:D{LAST},"legal_case",C{FIRST}:C{LAST}))/NSA', PCT, "OccArea"),
    ("In-place rent (AED/yr)", f"=SUM(K{FIRST}:K{LAST})", AED, "InPlaceRent"),
    ("Screen reference rent, all units, as-of (AED/yr)", f"=SUM(H{FIRST}:H{LAST})", AED, "RefRentTotal"),
    ("Over-rent share of income", f"=SUMPRODUCT(--(J{FIRST}:J{LAST}),K{FIRST}:K{LAST})/InPlaceRent", PCT, "OverRentShare"),
    ("Over-rent excess at expiry (AED/yr)", f"=SUMPRODUCT(--(J{FIRST}:J{LAST}),K{FIRST}:K{LAST}-H{FIRST}:H{LAST})", AED, "OverRentExcess"),
]
for i in range(4):
    lo = f"EDATE(RentRollDate,{3*i})"
    hi = f"EDATE(RentRollDate,{3*(i+1)})"
    # leases already expired at the rent roll date count in window 1
    extra = f'+SUMIFS(K{FIRST}:K{LAST},F{FIRST}:F{LAST},"<"&RentRollDate)' if i == 0 else ""
    stats.append((f"Expiring rent share, window {i+1} [roll date +{3*i}m, +{3*(i+1)}m)",
                  f'=(SUMIFS(K{FIRST}:K{LAST},F{FIRST}:F{LAST},">="&{lo},F{FIRST}:F{LAST},"<"&{hi}){extra})/InPlaceRent', PCT, f"ExpShareW{i+1}"))
stats.append(("Max 3-month expiry share", "=MAX(ExpShareW1,ExpShareW2,ExpShareW3,ExpShareW4)", PCT, "MaxExpShare"))
for i, (lab, f, fmt, nm) in enumerate(stats):
    rr = rs + 1 + i
    put(wsU, f"A{rr}", lab)
    put(wsU, f"H{rr}", f, F_BOLD, fmt)
    name(nm, "Units", f"$H${rr}")

# ======================================================================= CashFlow
wsC = wb.create_sheet("CashFlow")
put(wsC, "A1", "CashFlow: annual operating statement, Years 1-6 (Year 6 = forward NOI year for the exit)", F_TITLE)
put(wsC, "A2", "Year t runs 1 Jan to 31 Dec of 2026+t. Lines follow engine/README.md 'Operating statement'.", F_NOTE)
header_row(wsC, 4, ["Line", "Note"] + [f"Year {y}" for y in range(1, 7)])
wsC.column_dimensions["A"].width = 40
wsC.column_dimensions["B"].width = 70
for y in range(6):
    wsC.column_dimensions[CL(3 + y)].width = 15
YC = [CL(3 + y) for y in range(6)]  # C..H
cf = {}
r = 5


def cfline(key, label, note, fn, bold=False, fmt=AED, font=F_BASE):
    global r
    put(wsC, f"A{r}", label, F_BOLD if bold else F_BASE)
    put(wsC, f"B{r}", note, F_NOTE)
    for y in range(1, 7):
        put(wsC, f"{YC[y-1]}{r}", fn(y, YC[y-1]), font, fmt, bold=bold)
    cf[key] = r
    r += 1


def blank():
    global r
    r += 1


def U(y, k):
    c = CL(yb[y][k])
    return f"Units!{c}{TOT}"


put(wsC, f"A{r}", "Year index", F_BOLD)
for y in range(1, 7):
    put(wsC, f"{YC[y-1]}{r}", y, F_BASE, "0")
cf["yidx"] = r
r += 1
blank()
cfline("pot", "Potential rental income", "Sum of Units potential rent (expected rent, before downtime)", lambda y, c: f"={U(y,'pot')}", font=F_LINK)
cfline("dt", "Downtime loss", "Sum of Units downtime (turnover and lease-up)", lambda y, c: f"=-{U(y,'dt')}", font=F_LINK)
cfline("gri", "Gross rental income", "Potential - downtime", lambda y, c: f"={c}{cf['pot']}+{c}{cf['dt']}", bold=True)
cfline("oi", "Other income", "Year-1 amount x (1 + other income growth)^(t-1)", lambda y, c: f"=OtherIncome*(1+OIGrowth)^({c}{cf['yidx']}-1)")
cfline("gi", "Gross income", "Gross rental income + other income", lambda y, c: f"={c}{cf['gri']}+{c}{cf['oi']}", bold=True)
cfline("va", "Memo: vacancy allowance", "Structural vacancy x (rent after downtime + other income); not deducted itself", lambda y, c: f"=StructVac*({c}{cf['gri']}+{c}{cf['oi']})")
cfline("topup", "Vacancy allowance top-up", "max(0, allowance - downtime already modelled): the only vacancy deduction", lambda y, c: f"=-MAX(0,{c}{cf['va']}+{c}{cf['dt']})")
cfline("cl", "Collection loss", "Collection loss x (gross income - top-up)", lambda y, c: f"=-CollLoss*({c}{cf['gi']}+{c}{cf['topup']})")
cfline("egi", "Effective gross income (EGI)", "", lambda y, c: f"={c}{cf['gi']}+{c}{cf['topup']}+{c}{cf['cl']}", bold=True)
blank()
cfline("mgmt", "Management fee", "Mgmt % x EGI (a stated management line is not used)", lambda y, c: f"=MgmtPct*{c}{cf['egi']}")
opex_rows = []
for key, lab, dkey in OPEX_CATS:
    if key == "district_cooling":
        y1 = f'IF(ISNUMBER(Stated_{key}),Stated_{key},IF(ChillerLandlordPays="FALSE",0,Default_{key}*NSA))'
        note = "Stated if given; else default x NSA only if landlord pays cooling (true or unstated)"
    elif key == "sinking_fund":
        y1 = f"IF(ISNUMBER(Stated_{key}),Stated_{key},Default_{key}*NSA*SF_Mult)"
        note = "Stated if given; else default x NSA x age multiplier"
    else:
        y1 = f"IF(ISNUMBER(Stated_{key}),Stated_{key},Default_{key}*NSA)"
        note = "Stated if given; else mandate default x NSA (0 if no default)"
    cfline(f"opex_{key}", f"  Opex: {lab}", note + "; grows at opex growth from Year 2",
           lambda y, c, y1=y1: f"={y1}*(1+OpexGrowth)^({c}{cf['yidx']}-1)", font=F_LINK)
    opex_rows.append(cf[f"opex_{key}"])
cfline("opex", "Operating expenses (sum of categories)", "", lambda y, c: f"=SUM({c}{opex_rows[0]}:{c}{opex_rows[-1]})", bold=True)
cfline("lfm", "Memo: leasing fees modelled", "Sum of Units leasing fees (turnover and lease-up)", lambda y, c: f"={U(y,'fee')}", font=F_LINK)
cfline("lf", "Leasing fees (beyond stated marketing line)", "max(0, modelled - stated marketing/leasing line that year)", lambda y, c: f"=MAX(0,{c}{cf['lfm']}-{c}{cf['opex_marketing_leasing']})")
cfline("vatbase", "Memo: VAT base", "Mgmt + leasing fees + opex excl. sinking fund (only mgmt + leasing if stated opex includes VAT)",
       lambda y, c: f'={c}{cf["mgmt"]}+{c}{cf["lf"]}+IF(OpexInclVAT="TRUE",0,{c}{cf["opex"]}-{c}{cf["opex_sinking_fund"]})')
cfline("vatg", "Memo: input VAT gross", "VAT % x base", lambda y, c: f"=VATPct*{c}{cf['vatbase']}")
cfline("cshare", "Memo: commercial share of rent", "Retail unit rent / unit rent (no retail units here)",
       lambda y, c: f"=IF({U(y,'net')}=0,0,SUMIF(Units!{CL(c_retail)}{FIRST}:{CL(c_retail)}{LAST},TRUE,Units!{CL(yb[y]['net'])}{FIRST}:{CL(yb[y]['net'])}{LAST})/{U(y,'net')})", fmt=PCT)
cfline("vatr", "Memo: input VAT recovered", "Gross x commercial share", lambda y, c: f"={c}{cf['vatg']}*{c}{cf['cshare']}")
cfline("vat", "Input VAT (irrecoverable)", "Gross - recovered", lambda y, c: f"={c}{cf['vatg']}-{c}{cf['vatr']}")
cfline("toc", "Total operating costs", "Mgmt + opex + leasing fees + input VAT", lambda y, c: f"={c}{cf['mgmt']}+{c}{cf['opex']}+{c}{cf['lf']}+{c}{cf['vat']}", bold=True)
blank()
cfline("noi", "NET OPERATING INCOME (NOI)", "EGI - total operating costs", lambda y, c: f"={c}{cf['egi']}-{c}{cf['toc']}", bold=True)
for c in range(1, 9):
    wsC.cell(row=cf["noi"], column=c).fill = FILL_SUB
name("NOI1", "CashFlow", f"$C${cf['noi']}")
name("NOIFwd", "CashFlow", f"$H${cf['noi']}")
wsC.freeze_panes = "C5"

# ======================================================================= Debt
wsD = wb.create_sheet("Debt")
wsD.column_dimensions["A"].width = 46
wsD.column_dimensions["B"].width = 18
wsD.column_dimensions["C"].width = 70
for y in range(5):
    wsD.column_dimensions[CL(4 + y)].width = 15
put(wsD, "A1", "Debt: acquisition costs, loan sizing, annuity schedule, DSCR", F_TITLE)
dr = 3


def dline(label, f, fmt=AED, nm=None, note="", bold=False):
    global dr
    put(wsD, f"A{dr}", label, F_BOLD if bold else F_BASE)
    put(wsD, f"B{dr}", f, F_BASE, fmt, bold=bold)
    put(wsD, f"C{dr}", note, F_NOTE)
    if nm:
        name(nm, "Debt", f"$B${dr}")
    dr += 1


def dsec(t):
    global dr
    dr += 1
    put(wsD, f"A{dr}", t, F_BOLD, fill=FILL_SUB)
    dr += 1


dsec("Acquisition costs")
dline("DLD transfer fee", "=DLDPct*Price", nm="AC_DLD", note="4% of price")
dline("DLD admin", "=DLDAdmin", nm="AC_Admin")
dline("Trustee fee", "=TrusteeFee", nm="AC_Trustee")
dline("Broker fee", "=BrokerPct*Price", nm="AC_Broker")
dline("VAT on broker fee", "=BrokerVATPct*AC_Broker", nm="AC_BrokerVAT")
dline("Transfer costs", "=AC_DLD+AC_Admin+AC_Trustee+AC_Broker+AC_BrokerVAT", nm="TransferCosts", bold=True, note="Unlevered outlay = price + transfer costs")
dline("Mortgage registration", "=MortRegPct*Loan+MortRegAdmin", nm="AC_MortReg", note="0.25% of the loan + AED 290 (depends on the loan, hence on NOI)")
dline("Total acquisition costs", "=TransferCosts+AC_MortReg", nm="AcqTotal", bold=True)
dline("Total cost (price + acquisition costs)", "=Price+AcqTotal", nm="TotalCost", bold=True)
dline("Acquisition costs % of price", "=AcqTotal/Price", PCT, nm="AcqPct")

dsec("Loan sizing (lower of max LTV and the DSCR-supported amount)")
dline("Interest rate (EIBOR + margin)", "=Rate", PCT)
dline("Loan constant (annual payment per AED 1)", "=Rate/(1-(1+Rate)^(-AmortYears))", "0.000000", nm="LoanConst", note="Level annuity over amortisation years, paid annually in arrears")
dline("Year-1 NOI", "=NOI1", AED, note="From CashFlow")
dline("Loan at max LTV", "=MaxLTV*Price", nm="LoanLTV")
dline("Loan supported at sizing DSCR", "=NOI1/(SizingDSCR*LoanConst)", nm="LoanDSCR", note="Year-1 NOI / (sizing DSCR x loan constant)")
dline("LOAN", "=MIN(LoanLTV,LoanDSCR)", nm="Loan", bold=True)
dline("Binding constraint", '=IF(LoanLTV<=LoanDSCR,"ltv","dscr")', GEN, nm="SizingConstraint")
dline("LTV (loan / price)", "=Loan/Price", PCT, nm="LTV")
dline("Arrangement fee (paid at closing)", "=ArrFeePct*Loan", nm="ArrFee")
dline("Equity (price + acq. costs + arrangement fee - loan)", "=Price+AcqTotal+ArrFee-Loan", nm="Equity", bold=True)
dline("Annual debt service", "=PMT(Rate,AmortYears,-Loan)", nm="DebtService", bold=True, note="Excel PMT, cross-checks the loan constant: = Loan x constant")
dline("DSCR Year 1", "=NOI1/DebtService", MULT, nm="DSCR1", bold=True)
dline("Interest cover Year 1", f"=NOI1/D{dr+5}", MULT, nm="ICR1", note="NOI / Year-1 interest")
dline("Debt yield Year 1", "=NOI1/Loan", PCT, nm="DebtYield1")

dsec("Debt schedule (annuity, annual in arrears)")
header_row(wsD, dr, ["Line", "", ""] + [f"Year {y}" for y in range(1, 6)])
dr += 1
sched = {}
for lab in ["Opening balance", "Interest", "Principal", "Debt service", "Closing balance"]:
    sched[lab] = dr
    put(wsD, f"A{dr}", lab)
    dr += 1
for y in range(5):
    c = CL(4 + y)
    put(wsD, f"{c}{sched['Opening balance']}", "=Loan" if y == 0 else f"={CL(3+y)}{sched['Closing balance']}", F_BASE, AED)
    put(wsD, f"{c}{sched['Interest']}", f"={c}{sched['Opening balance']}*Rate", F_BASE, AED)
    put(wsD, f"{c}{sched['Debt service']}", "=DebtService", F_BASE, AED)
    put(wsD, f"{c}{sched['Principal']}", f"={c}{sched['Debt service']}-{c}{sched['Interest']}", F_BASE, AED)
    put(wsD, f"{c}{sched['Closing balance']}", f"={c}{sched['Opening balance']}-{c}{sched['Principal']}", F_BASE, AED)
# fix ICR reference to Year-1 interest cell
icr_row = [rr for rr in range(1, dr) if wsD[f"A{rr}"].value == "Interest cover Year 1"][0]
wsD[f"B{icr_row}"].value = f"=NOI1/D{sched['Interest']}"
name("LoanBalExit", "Debt", f"$H${sched['Closing balance']}")
put(wsD, f"A{dr}", "DSCR by year (NOI / debt service)")
for y in range(5):
    put(wsD, f"{CL(4+y)}{dr}", f"=CashFlow!{YC[y]}{cf['noi']}/{CL(4+y)}{sched['Debt service']}", F_LINK, MULT)
dr += 1

# ======================================================================= Returns
wsR = wb.create_sheet("Returns")
wsR.column_dimensions["A"].width = 50
wsR.column_dimensions["B"].width = 18
wsR.column_dimensions["C"].width = 60
for y in range(6):
    wsR.column_dimensions[CL(4 + y)].width = 15
put(wsR, "A1", "Returns: exit, unlevered and levered cash flows, IRR (Excel IRR) and equity multiples (pre-tax)", F_TITLE)
rr_ = 3


def rline(label, f, fmt=AED, nm=None, note="", bold=False):
    global rr_
    put(wsR, f"A{rr_}", label, F_BOLD if bold else F_BASE)
    put(wsR, f"B{rr_}", f, F_BASE, fmt, bold=bold)
    put(wsR, f"C{rr_}", note, F_NOTE)
    if nm:
        name(nm, "Returns", f"$B${rr_}")
    rr_ += 1


def rsec(t):
    global rr_
    rr_ += 1
    put(wsR, f"A{rr_}", t, F_BOLD, fill=FILL_SUB)
    rr_ += 1


rsec("Yields")
rline("Entry yield on price (Year-1 NOI / price)", "=NOI1/Price", PCT, "EntryYield", bold=True)
rline("Going-in net yield on total cost", "=NOI1/TotalCost", PCT, "YieldOnCost", bold=True)
rline("Gross yield, in-place rent on price", "=InPlaceRent/Price", PCT, "GrossYield")
rsec("Exit (mandate exit_yield_rule)")
rline("Area house-view exit yield", "=AreaExitYield", PCT)
rline("Base: max(area house view, entry yield)", "=MAX(AreaExitYield,EntryYield)", PCT, "ExitBase")
rline("Base source", '=IF(AreaExitYield>=EntryYield,"area_house_view","entry_yield")', GEN)
rline("Expansion", "=ExitExpBps/10000", PCT)
rline("Age premium (age at exit >= threshold)", "=IF(AgeExit>=AgePremFrom,AgePremBps/10000,0)", PCT, "AgePrem")
rline("EXIT YIELD", "=ExitBase+ExitExpBps/10000+AgePrem", PCT, "ExitYield", bold=True)
rline("Forward NOI (Year 6)", "=NOIFwd", AED, "FwdNOI")
rline("Gross exit value", "=FwdNOI/ExitYield", AED, "GrossExit", bold=True)
rline("Selling costs", "=-SellPct*GrossExit", AED, "SellCosts")
rline("Net sale proceeds", "=GrossExit+SellCosts", AED, "NetSale", bold=True)
rline("Loan balance at exit (end Year 5)", "=LoanBalExit", AED)

rsec("Cash flows (Year 0 = closing; Year 5 includes the sale)")
header_row(wsR, rr_, ["Line", "", ""] + [f"Year {y}" for y in range(0, 6)])
rr_ += 1
cfr = {}
for lab in ["NOI", "Unlevered cash flow", "Debt service", "Loan repayment at exit", "Levered cash flow"]:
    cfr[lab] = rr_
    put(wsR, f"A{rr_}", lab, F_BOLD if "cash flow" in lab else F_BASE)
    rr_ += 1
for y in range(6):
    c = CL(4 + y)
    if y == 0:
        put(wsR, f"{c}{cfr['NOI']}", 0, F_BASE, AED)
        put(wsR, f"{c}{cfr['Unlevered cash flow']}", "=-(Price+TransferCosts)", F_BASE, AED, bold=True)
        put(wsR, f"{c}{cfr['Debt service']}", 0, F_BASE, AED)
        put(wsR, f"{c}{cfr['Loan repayment at exit']}", 0, F_BASE, AED)
        put(wsR, f"{c}{cfr['Levered cash flow']}", "=-Equity", F_BASE, AED, bold=True)
    else:
        put(wsR, f"{c}{cfr['NOI']}", f"=CashFlow!{YC[y-1]}{cf['noi']}", F_LINK, AED)
        put(wsR, f"{c}{cfr['Unlevered cash flow']}", f"={c}{cfr['NOI']}" + ("+NetSale" if y == 5 else ""), F_BASE, AED, bold=True)
        put(wsR, f"{c}{cfr['Debt service']}", f"=-Debt!{CL(3+y)}{sched['Debt service']}", F_LINK, AED)
        put(wsR, f"{c}{cfr['Loan repayment at exit']}", "=-LoanBalExit" if y == 5 else 0, F_BASE, AED)
        put(wsR, f"{c}{cfr['Levered cash flow']}",
            f"={c}{cfr['Unlevered cash flow']}+{c}{cfr['Debt service']}+{c}{cfr['Loan repayment at exit']}", F_BASE, AED, bold=True)
U_RNG = f"D{cfr['Unlevered cash flow']}:I{cfr['Unlevered cash flow']}"
L_RNG = f"D{cfr['Levered cash flow']}:I{cfr['Levered cash flow']}"
rsec("Returns (pre-tax)")
rline("UNLEVERED IRR", f"=IRR({U_RNG})", PCT4, "UnlevIRR", bold=True)
rline("Unlevered equity multiple (inflows / outflows)", f'=SUMIF({U_RNG},">0")/-SUMIF({U_RNG},"<0")', MULT, "UnlevEM", bold=True)
rline("Levered IRR", f"=IRR({L_RNG})", PCT4, "LevIRR", bold=True)
rline("Levered equity multiple (inflows / outflows)", f'=SUMIF({L_RNG},">0")/-SUMIF({L_RNG},"<0")', MULT, "LevEM", bold=True)
rline("Exit gain, levered (net sale - (price + total acq. costs))", "=NetSale-(Price+AcqTotal)", AED, "ExitGainLev")

rsec("Walk-away check (engine's walk-away price, re-tested here)")
put(wsR, f"A{rr_}", "Unlevered IRR at price P depends on P only via the outlay (P + transfer costs) and the exit yield (through the entry yield NOI1/P); NOI does not depend on price. Tested at the engine's walk-away price and one AED 10,000 step above.", F_NOTE)
rr_ += 1
rline("Walk-away price under test (engine value)", "=EngineOutput!C5", AED, "WA_P", note="Linked from EngineOutput; the test is whether it satisfies the README definition")
rline("Step", 10000, AED, "WA_Step", note=f"{ERM}: WALK_AWAY_STEP_AED")
wsR[f"B{rr_-1}"].font = F_INPUT
header_row(wsR, rr_, ["Case", "Price", "Exit yield"] + [f"Year {y}" for y in range(0, 6)] + ["Unlevered IRR"])
rr_ += 1
wa_rows = {}
for lab, pf in [("At walk-away price", "=WA_P"), ("One step above", "=WA_P+WA_Step")]:
    wa_rows[lab] = rr_
    put(wsR, f"A{rr_}", lab)
    put(wsR, f"B{rr_}", pf, F_BASE, AED)
    put(wsR, f"C{rr_}", f"=MAX(AreaExitYield,NOI1/B{rr_})+ExitExpBps/10000+AgePrem", F_BASE, PCT4)
    put(wsR, f"D{rr_}", f"=-(B{rr_}*(1+DLDPct+BrokerPct*(1+BrokerVATPct))+DLDAdmin+TrusteeFee)", F_BASE, AED)
    for y in range(1, 6):
        extra = f"+NOIFwd/C{rr_}*(1-SellPct)" if y == 5 else ""
        put(wsR, f"{CL(4+y)}{rr_}", f"=CashFlow!{YC[y-1]}{cf['noi']}{extra}", F_LINK, AED)
    put(wsR, f"J{rr_}", f"=IRR(D{rr_}:I{rr_})", F_BOLD, PCT4)
    rr_ += 1
name("WA_IRR_at", "Returns", f"$J${wa_rows['At walk-away price']}")
name("WA_IRR_above", "Returns", f"$J${wa_rows['One step above']}")
rline("Walk-away holds? (IRR at P >= target and at P + step < target)", "=AND(WA_IRR_at>=TargetIRR,WA_IRR_above<TargetIRR)", GEN, "WA_OK", bold=True)
wsR.column_dimensions["J"].width = 15

# ======================================================================= EngineOutput
wsE = wb.create_sheet("EngineOutput")
put(wsE, "A1", "EngineOutput: values printed by the engine (black box), pasted as data", F_TITLE)
put(wsE, "A2", f"Source: python -m engine {FIX} --json (engine {engine['engine_version']}), saved as evals/tieout/engine_output_jvc_60_units.json. Blue = pasted engine value. Nothing here feeds the model sheets except via TieOut and the per-unit check on Units.", F_NOTE)
header_row(wsE, 4, ["Metric", "JSON path", "Engine value"])
wsE.column_dimensions["A"].width = 44
wsE.column_dimensions["B"].width = 60
wsE.column_dimensions["C"].width = 18
M = engine["metrics"]
eline = {}
er = 5
scalar_paths = [
    ("walk_away_price_aed", "underwriting.walk_away.price_aed.value", engine["walk_away"]["price_aed"]["value"], AED),
]
for k in ["unlevered_irr_pre_tax", "unlevered_equity_multiple_pre_tax", "entry_yield_on_price", "exit_yield",
          "going_in_net_yield_on_cost", "noi_year1", "potential_rental_income_year1", "gross_rental_income_year1",
          "effective_gross_income_year1", "operating_costs_year1", "acquisition_costs_aed", "total_cost_aed",
          "loan_aed", "ltv", "annual_debt_service_aed", "arrangement_fee_aed", "equity_aed", "dscr_year1",
          "icr_year1", "debt_yield_year1", "forward_noi_aed", "gross_exit_value_aed", "net_sale_proceeds_aed",
          "loan_balance_at_exit_aed", "exit_gain_levered_aed", "levered_irr_pre_tax", "levered_equity_multiple_pre_tax",
          "gross_yield_in_place_on_price", "occupancy_by_units", "occupancy_by_area", "in_place_rent_aed",
          "screen_reference_rent_aed", "over_rent_share_of_income", "over_rent_excess_at_expiry_aed", "max_expiry_share_quarter"]:
    scalar_paths.append((k, f"underwriting.metrics.{k}.value", M[k]["value"], None))
ac = engine["acquisition_costs"]
for k in ["dld_transfer_fee", "broker_fee", "broker_fee_vat", "transfer_costs", "mortgage_registration", "total"]:
    scalar_paths.append((f"acq_{k}", f"underwriting.acquisition_costs.{k}.value", ac[k]["value"], AED))
dbt = engine["debt"]
scalar_paths += [
    ("loan_at_max_ltv_aed", "underwriting.debt.loan_at_max_ltv_aed.value", dbt["loan_at_max_ltv_aed"]["value"], AED),
    ("loan_at_sizing_dscr_aed", "underwriting.debt.loan_at_sizing_dscr_aed.value", dbt["loan_at_sizing_dscr_aed"]["value"], AED),
    ("loan_constant", "underwriting.debt.loan_constant.value", dbt["loan_constant"]["value"], "0.000000"),
    ("sizing_constraint", "underwriting.debt.sizing_constraint", dbt["sizing_constraint"], GEN),
    ("wa_irr_at_price", "underwriting.walk_away.unlevered_irr_at_price.value", engine["walk_away"]["unlevered_irr_at_price"]["value"], PCT4),
    ("wa_irr_one_step_above", "underwriting.walk_away.unlevered_irr_one_step_above.value", engine["walk_away"]["unlevered_irr_one_step_above"]["value"], PCT4),
    ("wa_exit_yield_at_price", "underwriting.walk_away.exit_yield_at_price.value", engine["walk_away"]["exit_yield_at_price"]["value"], PCT4),
]
for k, path, v, fmt in scalar_paths:
    put(wsE, f"A{er}", k)
    put(wsE, f"B{er}", path, F_NOTE)
    put(wsE, f"C{er}", v, F_INPUT, fmt or (PCT4 if (isinstance(v, float) and abs(v) < 5) else AED2))
    eline[k] = f"EngineOutput!$C${er}"
    er += 1
assert eline["walk_away_price_aed"] == "EngineOutput!$C$5"
er += 1
put(wsE, f"A{er}", "Cash-flow lines (underwriting.cash_flow.lines.<line>.values)", F_BOLD)
header_row(wsE, er + 1, ["Line", "JSON path"] + [f"Year {y}" for y in range(1, 7)], start_col=1)
er += 2
eng_cf = engine["cash_flow"]["lines"]
for k in ["potential_rental_income", "downtime_loss", "gross_rental_income", "other_income", "gross_income",
          "vacancy_allowance", "structural_vacancy", "collection_loss", "effective_gross_income", "management_fee",
          "operating_expenses", "leasing_fees_modelled", "leasing_fees", "input_vat_gross", "input_vat_recovered",
          "input_vat", "total_operating_costs", "noi"]:
    put(wsE, f"A{er}", k)
    put(wsE, f"B{er}", f"underwriting.cash_flow.lines.{k}.values", F_NOTE)
    for y, v in enumerate(eng_cf[k]["values"]):
        put(wsE, f"{CL(3+y)}{er}", v, F_INPUT, AED2)
    eline[f"cf_{k}"] = er
    er += 1
er += 1
put(wsE, f"A{er}", "Debt schedule and returns cash flows", F_BOLD)
er += 1
for k in ["opening_balance", "interest", "principal", "debt_service", "closing_balance"]:
    put(wsE, f"A{er}", f"debt_{k}")
    put(wsE, f"B{er}", f"underwriting.debt_schedule.lines.{k}.values (Years 1-5)", F_NOTE)
    for y, v in enumerate(engine["debt_schedule"]["lines"][k]["values"]):
        put(wsE, f"{CL(3+y)}{er}", v, F_INPUT, AED2)
    eline[f"debt_{k}"] = er
    er += 1
for k in ["unlevered_pre_tax", "levered_pre_tax"]:
    put(wsE, f"A{er}", f"rcf_{k}")
    put(wsE, f"B{er}", f"underwriting.returns_cash_flows.lines.{k}.values (Years 0-5)", F_NOTE)
    for y, v in enumerate(engine["returns_cash_flows"]["lines"][k]["values"]):
        put(wsE, f"{CL(3+y)}{er}", v, F_INPUT, AED2)
    eline[f"rcf_{k}"] = er
    er += 1
# per-unit expected rent, aligned with Units rows FIRST..LAST
assert er < FIRST + 0 or True
pu_hdr = max(er + 2, 0)
# Use rows FIRST..LAST in columns D..I for alignment with Units; place them on a separate column band to avoid overlap
# (the scalar block occupies columns A-C, cash-flow blocks columns A-H from row ~60); so put per-unit data in columns K.. instead.
put(wsE, "K4", "Per-unit expected rent net of downtime (underwriting.unit_schedule.units[].expected_rent_by_year)", F_BOLD)
header_row(wsE, FIRST - 1, ["Unit"] + [f"Y{y}" for y in range(1, 7)], start_col=11)
for i, u in enumerate(engine["unit_schedule"]["units"]):
    r = FIRST + i
    assert u["unit"] == deal["units"][i]["unit"]
    put(wsE, f"K{r}", u["unit"], F_INPUT)
    for y, v in enumerate(u["expected_rent_by_year"]):
        put(wsE, f"{CL(12+y)}{r}", v, F_INPUT, AED2)
for c in range(11, 18):
    wsE.column_dimensions[CL(c)].width = 13

# Re-point the Units per-unit check to columns L..Q on EngineOutput
for i in range(N):
    r = FIRST + i
    nets = [f"{CL(yb[y]['net'])}{r}" for y in range(1, 7)]
    wsU[f"{CL(c_chk)}{r}"].value = "=" + "+".join(f"ABS({nets[y]}-EngineOutput!{CL(12+y)}{r})" for y in range(6))

# ======================================================================= TieOut
wsT = wb.create_sheet("TieOut")
put(wsT, "A1", "TieOut: workbook formula vs engine value", F_TITLE)
put(wsT, "A2", "Tolerances: AED amounts pass if |diff| <= AED 1,000 AND |diff| <= 0.1% of the engine value (or the AED 1,000 alone where the engine value is 0). "
               "Ratios (yields, LTV, occupancy, shares): |diff| <= 0.001% (0.1 bp). IRR: |diff| <= 1 bp. Multiples and DSCR: |diff| <= 0.001x.", F_NOTE)
header_row(wsT, 4, ["Figure", "Workbook (formula)", "Engine", "Difference", "Relative diff", "Tolerance", "Kind", "Pass?", "Workbook cell"])
for c, w in zip("ABCDEFGHI", [52, 18, 18, 14, 12, 12, 8, 8, 34]):
    wsT.column_dimensions[c].width = w
tr = 5


def tsec(t):
    global tr
    tr += 1
    put(wsT, f"A{tr}", t, F_BOLD, fill=FILL_SUB)
    tr += 1


def tline(label, wb_ref, eng_ref, kind, ref_label=None):
    global tr
    fmt = {"aed": AED, "ratio": PCT4, "irr": PCT4, "x": MULT, "text": GEN}[kind]
    put(wsT, f"A{tr}", label)
    put(wsT, f"B{tr}", f"={wb_ref}", F_LINK, fmt)
    put(wsT, f"C{tr}", f"={eng_ref}", F_LINK, fmt)
    put(wsT, f"G{tr}", kind)
    if kind == "text":
        put(wsT, f"D{tr}", "")
        put(wsT, f"H{tr}", f'=IF(B{tr}=C{tr},"PASS","FAIL")', F_BOLD)
    else:
        put(wsT, f"D{tr}", f"=B{tr}-C{tr}", F_BASE, AED2 if kind == "aed" else ("0.000000" if kind != "x" else "0.000000"))
        put(wsT, f"E{tr}", f'=IF(C{tr}=0,"",D{tr}/ABS(C{tr}))', F_BASE, PCT4)
        tol = {"aed": "1000", "ratio": "0.00001", "irr": "0.0001", "x": "0.001"}[kind]
        put(wsT, f"F{tr}", float(tol), F_INPUT, {"aed": AED, "ratio": PCT4, "irr": PCT4, "x": MULT}[kind])
        if kind == "aed":
            put(wsT, f"H{tr}", f'=IF(AND(ABS(D{tr})<=F{tr},OR(C{tr}=0,ABS(D{tr})<=0.001*ABS(C{tr}))),"PASS","FAIL")', F_BOLD)
        else:
            put(wsT, f"H{tr}", f'=IF(ABS(D{tr})<=F{tr},"PASS","FAIL")', F_BOLD)
    put(wsT, f"I{tr}", ref_label or wb_ref, F_NOTE)
    tr += 1


def E(k):
    return eline[k]


tsec("Decision metrics (unlevered, pre-tax)")
tline("Unlevered IRR, pre-tax", "UnlevIRR", E("unlevered_irr_pre_tax"), "irr", "Returns: Excel IRR")
tline("Unlevered equity multiple, pre-tax", "UnlevEM", E("unlevered_equity_multiple_pre_tax"), "x")
tline("Entry yield on price", "EntryYield", E("entry_yield_on_price"), "ratio")
tline("Exit yield", "ExitYield", E("exit_yield"), "ratio")
tline("Going-in net yield on total cost", "YieldOnCost", E("going_in_net_yield_on_cost"), "ratio")
tline("Walk-away holds at engine price (IRR >= target, +10k < target)", 'IF(WA_OK,"holds","fails")', '"holds"', "text", "Returns: walk-away check")
tline("Unlevered IRR at walk-away price", "WA_IRR_at", E("wa_irr_at_price"), "irr")
tline("Unlevered IRR one step above walk-away", "WA_IRR_above", E("wa_irr_one_step_above"), "irr")

tsec("Year-1 operating statement")
tline("Potential rental income, Y1", f"CashFlow!C{cf['pot']}", E("potential_rental_income_year1"), "aed")
tline("Gross rental income, Y1", f"CashFlow!C{cf['gri']}", E("gross_rental_income_year1"), "aed")
tline("Effective gross income, Y1", f"CashFlow!C{cf['egi']}", E("effective_gross_income_year1"), "aed")
tline("Total operating costs, Y1", f"CashFlow!C{cf['toc']}", E("operating_costs_year1"), "aed")
tline("NOI, Y1", "NOI1", E("noi_year1"), "aed")

tsec("Cash-flow lines by year (CashFlow vs engine cash_flow.lines)")
cf_map = [("Potential rental income", "pot", "potential_rental_income", 1),
          ("Downtime loss", "dt", "downtime_loss", -1),
          ("Other income", "oi", "other_income", 1),
          ("Vacancy allowance (memo)", "va", "vacancy_allowance", 1),
          ("Vacancy allowance top-up", "topup", "structural_vacancy", -1),
          ("Collection loss", "cl", "collection_loss", -1),
          ("EGI", "egi", "effective_gross_income", 1),
          ("Management fee", "mgmt", "management_fee", 1),
          ("Operating expenses", "opex", "operating_expenses", 1),
          ("Leasing fees", "lf", "leasing_fees", 1),
          ("Input VAT (irrecoverable)", "vat", "input_vat", 1),
          ("Total operating costs", "toc", "total_operating_costs", 1),
          ("NOI", "noi", "noi", 1)]
for lab, k, ek, sign in cf_map:
    for y in range(1, 7):
        wbref = f"{'-' if sign < 0 else ''}CashFlow!{YC[y-1]}{cf[k]}"
        tline(f"{lab}, Y{y}", wbref, f"EngineOutput!{CL(2+y)}{eline['cf_'+ek]}", "aed", f"CashFlow!{YC[y-1]}{cf[k]}")

tsec("Acquisition costs and debt")
tline("DLD transfer fee", "AC_DLD", E("acq_dld_transfer_fee"), "aed")
tline("Broker fee", "AC_Broker", E("acq_broker_fee"), "aed")
tline("VAT on broker fee", "AC_BrokerVAT", E("acq_broker_fee_vat"), "aed")
tline("Transfer costs", "TransferCosts", E("acq_transfer_costs"), "aed")
tline("Mortgage registration", "AC_MortReg", E("acq_mortgage_registration"), "aed")
tline("Total acquisition costs", "AcqTotal", E("acq_total"), "aed")
tline("Total cost", "TotalCost", E("total_cost_aed"), "aed")
tline("Loan constant", "LoanConst", E("loan_constant"), "ratio")
tline("Loan at max LTV", "LoanLTV", E("loan_at_max_ltv_aed"), "aed")
tline("Loan at sizing DSCR", "LoanDSCR", E("loan_at_sizing_dscr_aed"), "aed")
tline("Binding constraint", "SizingConstraint", E("sizing_constraint"), "text")
tline("Loan", "Loan", E("loan_aed"), "aed")
tline("LTV", "LTV", E("ltv"), "ratio")
tline("Arrangement fee", "ArrFee", E("arrangement_fee_aed"), "aed")
tline("Equity", "Equity", E("equity_aed"), "aed")
tline("Annual debt service", "DebtService", E("annual_debt_service_aed"), "aed")
tline("DSCR, Y1", "DSCR1", E("dscr_year1"), "x")
tline("Interest cover, Y1", "ICR1", E("icr_year1"), "x")
tline("Debt yield, Y1", "DebtYield1", E("debt_yield_year1"), "ratio")
for y in range(1, 6):
    tline(f"Interest, Y{y}", f"Debt!{CL(3+y)}{sched['Interest']}", f"EngineOutput!{CL(2+y)}{eline['debt_interest']}", "aed")
tline("Loan balance at exit", "LoanBalExit", E("loan_balance_at_exit_aed"), "aed")

tsec("Exit and returns")
tline("Forward NOI (Y6)", "FwdNOI", E("forward_noi_aed"), "aed")
tline("Gross exit value", "GrossExit", E("gross_exit_value_aed"), "aed")
tline("Net sale proceeds", "NetSale", E("net_sale_proceeds_aed"), "aed")
tline("Exit gain, levered", "ExitGainLev", E("exit_gain_levered_aed"), "aed")
for y in range(0, 6):
    tline(f"Unlevered cash flow, Y{y}", f"Returns!{CL(4+y)}{cfr['Unlevered cash flow']}", f"EngineOutput!{CL(3+y)}{eline['rcf_unlevered_pre_tax']}", "aed")
for y in range(0, 6):
    tline(f"Levered cash flow, Y{y}", f"Returns!{CL(4+y)}{cfr['Levered cash flow']}", f"EngineOutput!{CL(3+y)}{eline['rcf_levered_pre_tax']}", "aed")
tline("Levered IRR, pre-tax", "LevIRR", E("levered_irr_pre_tax"), "irr")
tline("Levered equity multiple, pre-tax", "LevEM", E("levered_equity_multiple_pre_tax"), "x")

tsec("Rent roll")
tline("Occupancy by units", "OccUnits", E("occupancy_by_units"), "ratio")
tline("Occupancy by area", "OccArea", E("occupancy_by_area"), "ratio")
tline("In-place rent", "InPlaceRent", E("in_place_rent_aed"), "aed")
tline("Screen reference rent (all units)", "RefRentTotal", E("screen_reference_rent_aed"), "aed")
tline("Gross yield, in-place on price", "GrossYield", E("gross_yield_in_place_on_price"), "ratio")
tline("Over-rent share of income", "OverRentShare", E("over_rent_share_of_income"), "ratio")
tline("Over-rent excess at expiry", "OverRentExcess", E("over_rent_excess_at_expiry_aed"), "aed")
tline("Max 3-month expiry share", "MaxExpShare", E("max_expiry_share_quarter"), "ratio")
tline("Per-unit expected rent, sum |diff| over 60 units x 6 years", f"Units!{CL(c_chk)}{TOT}", "0", "aed", "Units: check column")

last_t = tr - 1
tr += 1
put(wsT, f"A{tr}", "RESULT", F_BOLD)
put(wsT, f"B{tr}", f'=COUNTIF(H5:H{last_t},"PASS")&" pass, "&COUNTIF(H5:H{last_t},"FAIL")&" fail"', F_BOLD)
name("TieOutResult", "TieOut", f"$B${tr}")
wsT.freeze_panes = "B5"
put(wsT, "A3", "Summary:", F_BOLD)
put(wsT, "B3", "=TieOutResult", F_BOLD)

# sheet order
wb._sheets = [wb[n] for n in ["TieOut", "Inputs", "Units", "CashFlow", "Debt", "Returns", "EngineOutput"]]
for ws in wb.worksheets:
    for rowc in ws.iter_rows():
        for c in rowc:
            if c.font is None or c.font.name != FONT:
                c.font = Font(name=FONT, size=c.font.size if c.font else 10, bold=c.font.bold if c.font else False,
                              color=c.font.color if c.font else None, italic=c.font.italic if c.font else False)
wb.active = 0
wb.save(OUT)
print(f"wrote {OUT}")
