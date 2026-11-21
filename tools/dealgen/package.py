"""Turn a true building into what the broker package states: OM facts, rent-roll rows, operating
statement lines. Planted discrepancies are applied here (and in the building spec), never in the
renderers, so truth.json can record exactly what each document says.
"""
from __future__ import annotations

import random
from datetime import date

from .analysis import OCC_LIKE, rera_allowed_uplift
from .building import ITEM_CATEGORY, round_rent

SQM = 10.7639


def r_price(x):
    step = 250000 if x < 30e6 else 500000
    return int(round(x / step) * step)


# --------------------------------------------------------------------------- statement vocabularies
COOLING_LABEL = {
    "Business Bay": "District cooling - Empower (capacity & consumption)",
    "Al Barsha": "District cooling - Empower (capacity & consumption)",
    "Dubai Silicon Oasis": "District cooling charges (capacity & consumption)",
}
VOCAB = {
    "institutional": {
        "fm_contract": "Facilities management contract (MEP & HVAC)", "lift_amc": "Lift maintenance (AMC)",
        "fire_safety": "Fire & life safety systems AMC", "repairs_general": "Repairs & maintenance - reactive",
        "pest_tank": "Pest control & water tank cleaning", "facade_bmu": "Facade cleaning & BMU maintenance",
        "security": "Security services", "cleaning": "Cleaning & housekeeping", "waste": "Waste management",
        "dewa_common": "DEWA - common areas", "cooling": None, "insurance": "Building insurance (property all risks & TPL)",
        "mgmt_fee": "Property management fee", "leasing_comm": "Leasing commissions",
        "marketing": "Marketing & listing portals", "master_community": "Master community service charge",
        "admin": "Administration, Ejari & bank charges", "sinking": "Reserve fund contribution (capex)",
        "_rent_res": "Rental income - residential", "_rent_ret": "Rental income - retail",
        "_other": "Other income (parking, admin & late-payment fees)",
    },
    "accountant": {
        "fm_contract": "Annual maintenance contract", "lift_amc": "Lift maintenance", "fire_safety": "Civil defence & fire alarm maintenance",
        "repairs_general": "Repairs and maintenance", "pest_tank": "Pest control and tank cleaning", "facade_bmu": "Facade cleaning",
        "security": "Security and cleaning services", "cleaning": "Security and cleaning services", "waste": "Security and cleaning services",
        "dewa_common": "Electricity and water - common areas", "cooling": "Chiller plant - electricity and maintenance",
        "insurance": "Insurance", "mgmt_fee": "Management fees", "leasing_comm": "Commission and advertisement",
        "marketing": "Commission and advertisement", "master_community": "Community service fees",
        "admin": "General and administrative expenses", "sinking": "Provision for major repairs (sinking fund)",
        "_rent_res": "Rental income - apartments", "_rent_ret": "Rental income - shops", "_other": "Other income",
    },
    "pm_company": {
        "fm_contract": "FM contract", "lift_amc": "Lift AMC", "fire_safety": "Fire fighting AMC", "repairs_general": "R&M - general",
        "pest_tank": "Pest control / tank cleaning", "facade_bmu": "BMU / facade cleaning", "security": "Security",
        "cleaning": "Cleaning", "waste": "Garbage collection", "dewa_common": "DEWA common", "cooling": "AC charges - Empower",
        "insurance": "Building insurance", "mgmt_fee": "Mgmt fee", "leasing_comm": "Leasing commission",
        "marketing": "Advertising", "master_community": "Master community charges", "admin": "Admin & Ejari",
        "sinking": "Sinking fund", "_rent_res": "Rent - residential", "_rent_ret": "Rent - retail", "_other": "Other income",
    },
    "landlord": {
        "fm_contract": "Building maintenance (FM)", "lift_amc": "Lifts", "fire_safety": "Fire systems", "repairs_general": "Repairs",
        "pest_tank": "Pest control", "facade_bmu": "Facade cleaning", "security": "Security & cleaning",
        "cleaning": "Security & cleaning", "waste": "Waste", "dewa_common": "DEWA - landlord account",
        "cooling": "Empower", "insurance": "Building insurance", "mgmt_fee": "Management fee (4%)",
        "leasing_comm": "Leasing & marketing", "marketing": "Leasing & marketing", "master_community": "Master community fees",
        "admin": "Admin & sundry", "sinking": "Capex reserve", "_rent_res": "Residential rent",
        "_rent_ret": "Retail rent (excl. VAT)", "_other": "Parking & other income",
    },
    "owner": {
        "fm_contract": "Maintenance company", "lift_amc": "Lift service", "fire_safety": "Civil defence", "repairs_general": "Repairs",
        "pest_tank": "Pest control", "facade_bmu": "Facade cleaning", "security": "Watchman salary",
        "cleaning": "Cleaner salary", "waste": "Garbage", "dewa_common": "DEWA (common)", "cooling": "Chiller DEWA + maintenance",
        "insurance": "Insurance", "mgmt_fee": "Management fee", "leasing_comm": "Agent commission",
        "marketing": "Advertisement", "master_community": "Community charges", "admin": "Office & misc",
        "sinking": "Sinking fund", "_rent_res": "Rent received - flats", "_rent_ret": "Rent received - shops", "_other": "Other income",
    },
    "strata": {
        "oa_general": "Service charges - general fund (OA, via Mollak)", "oa_reserve": "Service charges - reserve fund (OA, via Mollak)",
        "repairs_general": "In-unit repairs & maintenance", "insurance": "Landlord insurance (contents & loss of rent)",
        "mgmt_fee": "Leasing & property management fee", "leasing_comm": "Leasing commissions", "marketing": "Marketing",
        "admin": "Admin, Ejari & DEWA move-in charges", "_rent_res": "Rental income", "_other": "Other income",
    },
    "master_owner": {
        "insurance": "Building insurance (landlord)", "sinking": "Reserve fund contribution", "asset_mgmt_fee": "Asset management fee",
        "admin": "Audit, legal & administration", "master_community": "Master community charges",
        "_rent_res": "Master lease rent - Silverline Homes Management L.L.C", "_other": "Other income",
    },
}

ITEM_ORDER = ["fm_contract", "lift_amc", "fire_safety", "repairs_general", "pest_tank", "facade_bmu", "security", "cleaning",
              "waste", "dewa_common", "cooling", "oa_general", "oa_reserve", "insurance", "master_community", "mgmt_fee",
              "asset_mgmt_fee", "leasing_comm", "marketing", "admin", "sinking"]


def statement_lines(spec, b):
    """Statement lines as presented (labels merged per vocabulary), monthly values from the true T-12."""
    vocab = dict(VOCAB[spec["stmt"]["vocab"]])
    if vocab.get("cooling") is None and "cooling" in b["opex_items"]:
        vocab["cooling"] = COOLING_LABEL.get(b["area"], "District cooling charges")
    if b["chiller_arrangement"] == "landlord_plant" and spec["stmt"]["vocab"] in ("institutional", "pm_company"):
        vocab["cooling"] = "Chiller plant - DEWA & O&M"
    t = b["t12"]
    months = t["months"]
    # income lines
    ret_share = 0.0
    if not spec.get("owner_statement_master_lease"):
        occ = [u for u in b["units"] if u["status"] in OCC_LIKE]
        tot = sum(u["annual_rent_aed"] for u in occ)
        ret_share = sum(u["annual_rent_aed"] for u in occ if u["type"] == "retail") / tot
    income = []
    if ret_share > 0:
        ret = [int(round(x * ret_share)) for x in t["rental_income"]]
        res = [a - r for a, r in zip(t["rental_income"], ret)]
        income.append({"label": vocab["_rent_res"], "category": "rental_income", "monthly": res})
        income.append({"label": vocab["_rent_ret"], "category": "rental_income", "monthly": ret})
    else:
        income.append({"label": vocab["_rent_res"], "category": "rental_income", "monthly": list(t["rental_income"])})
    if sum(t["other_income"]):
        income.append({"label": vocab["_other"], "category": "other_income", "monthly": list(t["other_income"])})
    expenses = []
    index = {}
    for key in ITEM_ORDER:
        if key not in t["opex"]:
            continue
        if key in spec.get("hidden_true_items", []):
            continue
        lab = vocab[key]
        if lab in index:
            ln = index[lab]
            ln["monthly"] = [a + c for a, c in zip(ln["monthly"], t["opex"][key])]
            ln["items"].append(key)
        else:
            ln = {"label": lab, "category": ITEM_CATEGORY[key], "monthly": list(t["opex"][key]), "items": [key]}
            index[lab] = ln
            expenses.append(ln)
    for ln in income + expenses:
        ln["total"] = sum(ln["monthly"])
    return months, income, expenses


def statement_doc(spec, b):
    months, income, expenses = statement_lines(spec, b)
    lay = spec["stmt"]["layout"]
    doc = {"months": months, "income": income, "expenses": expenses, "layout": lay}
    if lay == "ytd_annualised":
        # keep only Jan-Sep of the final calendar year, quarterly columns, then x 12/9
        idx = [i for i, m in enumerate(months) if m.year == months[-1].year and m.month <= 9]
        assert len(idx) == 9, idx
        for ln in income + expenses:
            q = [sum(ln["monthly"][i] for i in idx[j * 3:(j + 1) * 3]) for j in range(3)]
            ln["quarters"] = q
            ln["ytd"] = sum(q)
            ln["annualised"] = int(round(ln["ytd"] * 12 / 9))
            ln["stated"] = ln["annualised"]
        doc["period"] = {"start": months[idx[0]].isoformat(), "end": date(months[-1].year, 9, 30).isoformat(),
                         "months_covered": 9, "annualised": True, "annualisation_factor": "12/9",
                         "presented_as": "FY2026"}
    else:
        for ln in income + expenses:
            ln["stated"] = ln["total"]
        rng = random.Random(spec["seed"] + 77)
        if lay == "annual_comparative":
            for ln in income + expenses:
                ln["prior"] = int(round(ln["total"] * rng.uniform(0.92, 1.07) / 10) * 10)
        end = months[-1]
        import calendar
        doc["period"] = {"start": months[0].isoformat(),
                         "end": date(end.year, end.month, calendar.monthrange(end.year, end.month)[1]).isoformat(),
                         "months_covered": 12, "annualised": False, "presented_as": "12 months"}
    return doc


# --------------------------------------------------------------------------- OM facts
TITLE_TEXT = {
    ("freehold", "single_title"): "Freehold - single title deed (whole building)",
    ("freehold", "strata"): None,  # set per deal
}


def om_facts(spec, b, stmt, rr, mandate):
    """What the OM states. Returns dict of fields with values; renderers record page and quote."""
    br = spec["broker"]
    plant = set(spec["plant"])
    rrm = rr["metrics"]
    in_place = rrm["in_place_rent_aed"]
    potential = rrm["potential_rent_aed"]
    om = {}
    om["building_name"] = b["name"]
    om["area"] = b["area"]
    om["plot_number"] = b["plot_number"]
    om["completion_year"] = b["completion_year"]
    om["floors"] = b["floors"]
    om["parking_spaces"] = b["parking_spaces"]
    # unit count / mix
    mix = dict(spec.get("om_unit_mix") or b["unit_mix"])
    if spec.get("om_unit_mix") and "retail" in b["unit_mix"]:
        mix["retail"] = b["unit_mix"]["retail"]
    om["unit_mix"] = mix
    om["unit_count"] = sum(mix.values())
    # areas
    om["bua_sqft"] = b["bua_sqft"]
    om["nsa_sqft"] = int(round(b["nsa_sqft"]))
    om["plot_area_sqft"] = b["plot_area_sqft"]
    # occupancy
    if spec.get("om_occupancy_stated") is not None:
        om["occupancy"] = {"value": spec["om_occupancy_stated"], "as_of": spec.get("om_occupancy_as_of")}
    else:
        om["occupancy"] = {"value": round(rrm["occupancy_units"], 3 if br == "harbour_crest" else 2), "as_of": b["rent_roll_date"].strftime("%B %Y")}
    # income
    if b["master_lease"]:
        rent, basis = b["master_lease"]["annual_rent_aed"], "in_place"
    elif 2 in plant:
        rent, basis = potential, "potential"
    else:
        rent, basis = in_place, "in_place"
    style = {"harbour_crest": 1, "marwah_stone": 1, "meridian_gate": 10000, "saffron_key": 1000, "dunecrest": 10000}[br]
    rent_stated = int(round(rent / style) * style)
    om["annual_rent"] = {"value": rent_stated, "basis": basis,
                         "basis_as_labelled": "unstated" if basis == "potential" else "in_place"}
    other = sum(ln["stated"] for ln in stmt["income"] if ln["category"] == "other_income")
    opex_stmt = sum(ln["stated"] for ln in stmt["expenses"])
    # price
    base = rent_stated if spec["price_basis"] == "stated" else in_place
    price = r_price(base / spec["broker_gross_yield"])
    om["asking_price_aed"] = price
    acq = mandate["underwriting"]["acquisition_costs"]
    costs = price * (acq["dld_transfer_fee_pct"] + acq["broker_fee_pct"] * (1 + acq["broker_fee_vat_pct"])) + acq["dld_admin_aed"] + acq["trustee_fee_aed"]
    om["opex_stated_aed"] = None
    om["noi_stated_aed"] = None
    if br in ("harbour_crest", "marwah_stone"):
        noi = rent_stated + other - opex_stmt
        om["opex_stated_aed"] = opex_stmt
        om["other_income_stated_aed"] = other
        om["noi_stated_aed"] = noi
        om["purchaser_costs_aed"] = int(round(costs))
        om["purchaser_costs_pct"] = round(costs / price, 4)
        om["yield"] = {"value": round(noi / (price + costs), 4), "label": "Net Initial Yield", "basis": "net",
                       "on": "total_cost"}
        om["gross_yield_on_price"] = round(rent_stated / price, 4)
    elif 3 in plant:
        deduction = int(round(sum(ln["stated"] for ln in stmt["expenses"] if ln["category"] in ("service_charge",)) / 1000) * 1000)
        deduction = max(deduction, 150000)
        om["opex_stated_aed"] = deduction
        om["yield"] = {"value": round((rent_stated - deduction) / price, 4), "label": "Net Yield", "basis": "net",
                       "on": "asking_price", "deduction_label": "Less: service & community charges"}
    else:
        label = {"dunecrest": "ROI", "saffron_key": "ROI", "meridian_gate": "Gross Yield"}[br]
        if b["master_lease"]:
            label = "Guaranteed ROI"
        om["yield"] = {"value": round(rent_stated / price, 4), "label": label, "basis": "gross", "on": "asking_price"}
    # price psf
    if spec.get("om_price_psf_on") == "bua_unlabelled":
        om["price_psf"] = {"value": int(round(price / b["bua_sqft"])), "basis": "bua", "basis_labelled": False}
    elif br == "dunecrest":
        om["price_psf"] = {"value": int(round(price / b["bua_sqft"])), "basis": "bua", "basis_labelled": True}
    elif br in ("harbour_crest", "marwah_stone", "meridian_gate"):
        om["price_psf"] = {"value": int(round(price / b["nsa_sqft"])), "basis": "nsa", "basis_labelled": True}
    else:
        om["price_psf"] = None
    # chiller
    ch = b["chiller_arrangement"]
    om["chiller_arrangement"] = {"landlord_district": "landlord_pays", "landlord_plant": "landlord_pays",
                                 "tenant_district": "tenant_pays", "tenant_dewa": "tenant_pays"}[ch]
    # lease structure
    if b["master_lease"]:
        om["lease_structure"] = {"value": "master_lease", "master_tenant": b["master_lease"]["tenant"]}
    else:
        om["lease_structure"] = {"value": "direct_leases", "master_tenant": None}
    # title as stated
    om["title_type"] = {"tenure": b["tenure"] if b["tenure"] == "freehold" else "unstated",
                        "title": b["title"] if b["title"] == "strata" else "single_title"}
    if b["tenure"] == "non_freehold":
        om["title_type"] = {"tenure": "unstated (non-freehold indicated)", "title": "single_title"}
    # upside
    om["upside_claims"] = []
    om["_upside"] = None
    bands = mandate["underwriting"]["rera"]["increase_bands"]
    if spec.get("upside") == "compliant":
        occ = [u for u in b["units"] if u["status"] in OCC_LIKE and u["type"] != "retail"]
        n20 = sum(1 for u in occ if u["annual_rent_aed"] < 0.80 * u["market_rent_aed"])
        om["_upside"] = {"kind": "compliant", "units_more_than_20pct_below_index": n20}
    elif spec.get("upside") == "exceeds_rera":
        occ = [u for u in b["units"] if u["status"] in OCC_LIKE]
        under = [u for u in occ if u["annual_rent_aed"] < u["market_rent_aed"]]
        mtm = sum(u["market_rent_aed"] - u["annual_rent_aed"] for u in under)
        mtm = int(round(mtm / 50000) * 50000)
        avg_gap = 1 - sum(u["annual_rent_aed"] for u in under) / sum(u["market_rent_aed"] for u in under)
        allowed = rera_allowed_uplift(b["units"], bands)
        om["_upside"] = {"kind": "exceeds_rera", "claimed_uplift_aed": mtm, "claimed_uplift_pct": round(mtm / in_place, 3),
                         "avg_gap_under_rented": round(avg_gap, 3), "rera_allowed": allowed}
    return om
