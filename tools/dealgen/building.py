"""Build the 'true building' for a deal spec: physical facts, unit-by-unit leases, a true trailing
12-month operating statement (monthly), and the asking price.

Everything is driven by a seeded random.Random so output is deterministic.
"""
from __future__ import annotations

import calendar
import math
import random
from datetime import date, timedelta
from pathlib import Path

import yaml

from . import refdata

REPO = Path(__file__).resolve().parents[2]


def load_refs():
    mandate = yaml.safe_load((REPO / "data" / "mandate.yaml").read_text())
    market = yaml.safe_load((REPO / "data" / "market" / "areas.yaml").read_text())
    return mandate, market


# --------------------------------------------------------------------------- dates
def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def lease_end_for(start: date, years: int = 1) -> date:
    try:
        anniv = start.replace(year=start.year + years)
    except ValueError:  # 29 Feb
        anniv = start.replace(year=start.year + years, day=28)
    return anniv - timedelta(days=1)


def month_list(end_month: date, n: int = 12):
    """List of first-of-month dates for the n months ending with end_month (inclusive)."""
    first = date(end_month.year, end_month.month, 1)
    return [add_months(first, -(n - 1 - i)) for i in range(n)]


# --------------------------------------------------------------------------- helpers
def r500(x):
    return int(round(x / 500.0) * 500)


def r1000(x):
    return int(round(x / 1000.0) * 1000)


def round_rent(x):
    return r1000(x) if x >= 100000 else r500(x)


def weighted_choice(rng, weights: dict):
    keys = list(weights)
    tot = sum(weights.values())
    x = rng.uniform(0, tot)
    acc = 0
    for k in keys:
        acc += weights[k]
        if x <= acc:
            return k
    return keys[-1]


def person_name(rng, area):
    grp = weighted_choice(rng, refdata.AREA_NATIONALITY_WEIGHTS[area])
    firsts, lasts = refdata.NAME_GROUPS[grp]
    first = rng.choice(firsts)
    last = rng.choice(lasts)
    if grp == "russian" and first in refdata.FEMALE_FIRST and last.endswith(("ov", "ev", "in")):
        last = last + "a"
    if grp == "chinese":
        return f"{last} {first}" if rng.random() < 0.5 else f"{first} {last}"
    return f"{first} {last}"


def company_name(rng, area, used):
    for _ in range(50):
        sfx = rng.choice(refdata.COMPANY_SUFFIX_BY_AREA.get(area, refdata.COMPANY_SUFFIX_DEFAULT))
        nm = f"{rng.choice(refdata.COMPANY_PREFIX)} {rng.choice(refdata.COMPANY_ACTIVITY)} {sfx}"
        if nm not in used:
            used.add(nm)
            return nm
    raise RuntimeError("company names exhausted")


def ejari_no(rng, start: date):
    # 16-digit style: leading 0, registration year, then a running number
    return f"01{start.year}{start.month:02d}{rng.randint(0, 99999999):08d}"


# --------------------------------------------------------------------------- core
def build_true_building(spec, mandate, market):
    rng = random.Random(spec["seed"])
    area = spec["area"]
    am = market["areas"][area]
    factors = market["unit_type_factors"]
    psf_1br = am["market_rent_aed_psf_1br"]
    fall = -(am["rent_change_yoy"] if am["rent_change_yoy"] is not None else spec.get("assumed_rent_change_yoy", -0.03))
    roll_date = spec["roll_date"]

    # ---- physical units
    units = []
    for f in range(1, spec["res_floors"] + 1):
        plan = spec.get("floor_overrides", {}).get(f, spec["floor_plan"])
        for s, (typ, size) in enumerate(plan, 1):
            units.append({"unit": f"{f}{s:02d}", "floor": f, "type": typ, "area_sqft": float(size)})
    for code, size in spec.get("retail", []):
        units.append({"unit": code, "floor": 0, "type": "retail", "area_sqft": float(size)})

    for u in units:
        u["market_rent_aed"] = round(psf_1br * factors[u["type"]] * u["area_sqft"])

    n = len(units)
    nsa = round(sum(u["area_sqft"] for u in units), 2)
    bua = int(round(nsa / spec["efficiency"] / 10.0) * 10)

    # ---- occupancy
    n_vac = int(round(n * (1 - spec["occupancy"])))
    res_idx = [i for i, u in enumerate(units) if u["type"] != "retail"]
    ret_idx = [i for i, u in enumerate(units) if u["type"] == "retail"]
    vac = set(rng.sample(res_idx, n_vac - spec.get("vacant_retail", 0)))
    if spec.get("vacant_retail", 0):
        vac |= set(rng.sample(ret_idx, spec["vacant_retail"]))

    # ---- company blocks (corporate leases taking several units)
    used_companies = set()
    occ_res = [i for i in res_idx if i not in vac]
    rng.shuffle(occ_res)
    company_of = {}
    n_company_units = int(round(len(occ_res) * spec.get("company_share", 0.25)))
    k = 0
    while k < n_company_units:
        block = rng.choice([1, 1, 1, 2, 2, 3, 4, 6]) if spec.get("company_blocks", True) else 1
        nm = company_name(rng, area, used_companies)
        for i in occ_res[k:k + block]:
            company_of[i] = nm
        k += block

    mix = spec["tenancy_mix"]  # {'sitting':p,'new':p,'peak':p}
    ratios = spec.get("ratios", {})
    sit_lo, sit_hi = ratios.get("sitting", (0.82, 0.97))
    new_lo, new_hi = ratios.get("new", (0.94, 1.01))
    peak_lo, peak_hi = ratios.get("peak", (1.08, 1.20))

    window = spec.get("start_window")  # (start, end, share)
    retail_tenants = list(refdata.RETAIL_TENANTS)
    rng.shuffle(retail_tenants)

    for i, u in enumerate(units):
        u["chiller"] = spec["chiller"]
        if i in vac:
            u.update(status="vacant", tenant=None, tenant_type=None, ejari_no=None, lease_start=None,
                     lease_end=None, cheques=None, deposit_aed=None,
                     annual_rent_aed=None, tenancy_category=None,
                     asking_rent_aed=round_rent(u["market_rent_aed"] * rng.uniform(1.00, 1.06)))
            continue
        if u["type"] == "retail":
            yrs = 3
            start = roll_date - timedelta(days=rng.randint(30, 3 * 365 - 30))
            start = start.replace(day=1)
            ratio = rng.uniform(0.86, 1.02)
            cat = "retail"
            tenant = retail_tenants.pop()
            ttype = "company"
        else:
            yrs = 1
            if window and rng.random() < window[2]:
                span = (window[1] - window[0]).days
                start = window[0] + timedelta(days=rng.randint(0, span))
            else:
                start = roll_date - timedelta(days=rng.randint(1, 362))
            r = rng.random()
            if r < 0.45:
                start = start.replace(day=1)
            elif r < 0.60:
                start = start.replace(day=15)
            cat = weighted_choice(rng, mix)
            months_ago = (roll_date - start).days / 30.44
            if cat == "sitting":
                ratio = rng.uniform(sit_lo, sit_hi)
            elif cat == "new":
                ratio = (1 + fall * months_ago / 12.0) * rng.uniform(new_lo, new_hi)
            else:
                ratio = rng.uniform(peak_lo, peak_hi)
            if i in company_of:
                tenant, ttype = company_of[i], "company"
            else:
                tenant, ttype = person_name(rng, area), "individual"
        while lease_end_for(start, yrs) < roll_date + timedelta(days=3):
            start = add_months(start, 1)
        end = lease_end_for(start, yrs)
        rent = round_rent(u["market_rent_aed"] * ratio)
        if ttype == "company":
            cheques = rng.choice([1, 1, 2, 4, 4])
        elif area == "International City":
            cheques = rng.choice([4, 4, 6, 6, 12, 12, 2])
        else:
            cheques = rng.choice([1, 2, 4, 4, 4, 6, 12, 2])
        if u["type"] == "retail":
            cheques = 4
            dep = int(round(rent * 0.10 / 100.0) * 100)
        elif cat == "sitting" and rng.random() < 0.5:
            dep = int(round(rent * rng.uniform(0.86, 0.95) * 0.05 / 50.0) * 50)  # deposit not topped up
        else:
            dep = int(round(rent * 0.05))
        u.update(status="occupied", tenant=tenant, tenant_type=ttype, ejari_no=ejari_no(rng, start),
                 lease_start=start, lease_end=end, cheques=cheques, deposit_aed=dep,
                 annual_rent_aed=rent, tenancy_category=cat, asking_rent_aed=None)

    # ---- statuses beyond 'occupied'
    occ = [u for u in units if u["status"] == "occupied" and u["type"] != "retail"]
    soon = sorted([u for u in occ if u["lease_end"] <= roll_date + timedelta(days=45)], key=lambda x: x["lease_end"])
    for u in soon[: spec.get("under_renewal", 2)]:
        u["status"] = "under_renewal"
    mid = [u for u in occ if u["status"] == "occupied"
           and roll_date + timedelta(days=20) <= u["lease_end"] <= roll_date + timedelta(days=100)]
    rng.shuffle(mid)
    for u in mid[: spec.get("notice_served", 1)]:
        u["status"] = "notice_served"
    pool = [u for u in occ if u["status"] == "occupied" and u["tenant_type"] == "individual"]
    rng.shuffle(pool)
    for u in pool[: spec.get("legal_case", 0)]:
        u["status"] = "legal_case"

    # ---- planted rent-roll facts that are also true facts (holding over, missing Ejari)
    hold = spec.get("holding_over", 0)
    if hold:
        cands = [u for u in units if u["status"] == "occupied" and u["type"] != "retail"]
        rng.shuffle(cands)
        for u in cands[:hold]:
            # lease expired 1-4 months before the roll date; tenant still in, Ejari lapsed
            end = roll_date - timedelta(days=rng.randint(20, 120))
            u["lease_end"] = end
            u["lease_start"] = end - timedelta(days=364)
            u["holding_over"] = True
    miss = spec.get("missing_ejari", 0)
    if miss:
        cands = [u for u in units if u["status"] == "occupied" and not u.get("holding_over") and u["type"] != "retail"]
        rng.shuffle(cands)
        for u in cands[:miss]:
            u["ejari_no"] = None

    for u in units:
        if u["annual_rent_aed"]:
            u["rent_to_market"] = round(u["annual_rent_aed"] / u["market_rent_aed"], 4)
            u["rent_psf"] = round(u["annual_rent_aed"] / u["area_sqft"], 2)

    occupied_like = [u for u in units if u["status"] != "vacant"]
    in_place = sum(u["annual_rent_aed"] for u in occupied_like)
    vacant_asking = sum(u["asking_rent_aed"] for u in units if u["status"] == "vacant")

    # ---- master lease (look-through: units above are the operator's sub-tenancies)
    master = None
    if spec.get("master_lease"):
        ml = dict(spec["master_lease"])
        ml["annual_rent_aed"] = r1000(in_place * ml.pop("rent_over_subleases"))
        master = ml

    # ---- other income
    other_income = r1000(in_place * spec.get("other_income_pct", 0.008))

    b = {
        "name": spec["name"], "area": area, "sub_community": spec.get("sub_community"),
        "dld_area": refdata.LOCATION[area]["dld_area"] if not spec.get("dld_area") else spec["dld_area"],
        "plot_number": spec["plot"], "plot_area_sqft": spec.get("plot_area_sqft"),
        "tenure": spec["tenure"], "title": spec["title"],
        "nationality_restriction": spec.get("nationality_restriction"),
        "completion_year": spec["completion_year"], "floors": spec["floors_label"],
        "residential_floors": spec["res_floors"],
        "unit_count": n, "unit_mix": mix_counts(units),
        "bua_sqft": bua, "nsa_sqft": nsa, "efficiency_nsa_bua": round(nsa / bua, 4),
        "parking_spaces": spec["parking"], "lifts": spec.get("lifts", max(2, math.ceil(n / 45))),
        "chiller_arrangement": spec["chiller"],
        "chiller_landlord_pays": spec["chiller"] in ("landlord_district", "landlord_plant"),
        "lease_structure": "master_lease" if master else "direct_leases",
        "master_lease": master,
        "seller": spec.get("seller"),
        "rent_roll_date": roll_date,
        "units": units,
        "in_place_rent_aed": in_place,
        "vacant_asking_rent_aed": vacant_asking,
        "potential_rent_aed": in_place + vacant_asking,
        "other_income_aed": other_income,
        "occupancy_units": round(len(occupied_like) / n, 4),
        "occupancy_area": round(sum(u["area_sqft"] for u in occupied_like) / nsa, 4),
    }
    b["opex_items"] = opex_items(spec, b, rng)
    b["t12"] = monthly_t12(spec, b, rng)
    return b, rng


def mix_counts(units):
    out = {}
    for t in ["studio", "1br", "2br", "3br", "retail"]:
        c = sum(1 for u in units if u["type"] == t)
        if c:
            out[t] = c
    return out


# --------------------------------------------------------------------------- opex
# internal item key -> chart-of-accounts category
ITEM_CATEGORY = {
    "fm_contract": "maintenance_repairs", "lift_amc": "maintenance_repairs", "fire_safety": "maintenance_repairs",
    "repairs_general": "maintenance_repairs", "pest_tank": "maintenance_repairs", "facade_bmu": "maintenance_repairs",
    "security": "security_cleaning", "cleaning": "security_cleaning", "waste": "security_cleaning",
    "dewa_common": "utilities_common", "cooling": "district_cooling", "insurance": "insurance",
    "mgmt_fee": "property_management", "leasing_comm": "marketing_leasing", "marketing": "marketing_leasing",
    "master_community": "service_charge", "oa_general": "service_charge", "oa_reserve": "sinking_fund",
    "admin": "admin_other", "sinking": "sinking_fund", "asset_mgmt_fee": "property_management",
}


def opex_items(spec, b, rng):
    nsa, bua = b["nsa_sqft"], b["bua_sqft"]
    age = 2026 - b["completion_year"]
    rent = b["in_place_rent_aed"]
    o = spec.get("opex", {})
    U = rng.uniform
    items = {}
    if spec.get("owner_statement_master_lease"):
        # owner's costs under a master lease: operator bears running costs
        items["insurance"] = nsa * U(0.85, 1.1)
        items["sinking"] = nsa * U(1.0, 1.4)
        items["asset_mgmt_fee"] = b["master_lease"]["annual_rent_aed"] * 0.02
        items["admin"] = nsa * U(0.2, 0.35)
        items["master_community"] = bua * U(0.5, 0.7)
    elif b["title"] == "strata":
        items["oa_general"] = nsa * U(13.2, 14.2)
        items["oa_reserve"] = nsa * U(1.6, 2.0)
        items["repairs_general"] = nsa * U(0.6, 0.9)
        items["insurance"] = nsa * U(0.25, 0.35)  # landlord's contents / loss-of-rent cover
        items["admin"] = nsa * U(0.35, 0.5)
    else:
        items["fm_contract"] = nsa * U(2.2, 2.8) * (1 + 0.01 * age)
        items["lift_amc"] = b["lifts"] * U(16000, 21000)
        items["fire_safety"] = nsa * U(0.25, 0.38)
        items["repairs_general"] = nsa * U(0.7, 1.1) * (1 + 0.035 * age)
        items["pest_tank"] = nsa * U(0.10, 0.14)
        items["security"] = max(72000, nsa * U(1.1, 1.5))
        items["cleaning"] = max(54000, nsa * U(0.9, 1.25))
        items["waste"] = nsa * U(0.12, 0.18)
        items["dewa_common"] = nsa * U(1.8, 2.4)
        if b["chiller_landlord_pays"]:
            items["cooling"] = nsa * U(7.2, 8.6)
        items["insurance"] = nsa * U(0.85, 1.2)
        items["master_community"] = bua * U(0.45, 0.8)
        items["sinking"] = nsa * U(1.0, 1.6)
        items["admin"] = nsa * U(0.35, 0.6)
        if b["residential_floors"] >= 10:
            items["facade_bmu"] = nsa * U(0.2, 0.3)
    if not spec.get("owner_statement_master_lease"):
        if spec.get("mgmt_fee_pct"):
            items["mgmt_fee"] = rent * spec["mgmt_fee_pct"]
        items["leasing_comm"] = rent * U(0.004, 0.008)
        items["marketing"] = U(9000, 24000)
    for k in o.get("drop", []):
        items.pop(k, None)
    for k, mult in o.get("scale", {}).items():
        items[k] *= mult
    return {k: int(round(v)) for k, v in items.items()}


# seasonal weights for cooling/utilities by calendar month
SEASON = {1: 0.55, 2: 0.55, 3: 0.7, 4: 0.9, 5: 1.15, 6: 1.35, 7: 1.5, 8: 1.5, 9: 1.35, 10: 1.1, 11: 0.75, 12: 0.6}


def _spread(rng, kind, annual, months, *, pay_month=None, pay_months=None):
    """Return list of 12 monthly amounts summing to annual."""
    n = len(months)
    if kind == "flat":
        w = [1.0] * n
    elif kind == "season":
        w = [SEASON[m.month] for m in months]
    elif kind == "lumpy":
        w = [rng.gammavariate(1.6, 1.0) for _ in months]
    elif kind == "noisy":
        w = [rng.uniform(0.85, 1.15) for _ in months]
    elif kind == "once":
        w = [1.0 if m.month == pay_month else 0.0 for m in months]
    elif kind == "multi":
        w = [1.0 if m.month in pay_months else 0.0 for m in months]
    else:
        raise ValueError(kind)
    tot = sum(w)
    vals = [int(round(annual * x / tot)) for x in w]
    vals[max(range(n), key=lambda i: w[i])] += annual - sum(vals)
    return vals


ITEM_PATTERN = {
    "fm_contract": ("flat",), "security": ("flat",), "cleaning": ("flat",), "waste": ("flat",),
    "lift_amc": ("multi", None, (1, 4, 7, 10)), "fire_safety": ("multi", None, (3, 9)),
    "repairs_general": ("lumpy",), "pest_tank": ("multi", None, (2, 5, 8, 11)),
    "dewa_common": ("season",), "cooling": ("season",), "insurance": ("once", 4, None),
    "leasing_comm": ("lumpy",), "marketing": ("lumpy",), "master_community": ("multi", None, (1, 7)),
    "admin": ("noisy",), "sinking": ("flat",), "oa_general": ("multi", None, (1, 4, 7, 10)),
    "oa_reserve": ("multi", None, (1, 4, 7, 10)), "facade_bmu": ("multi", None, (2, 11)),
    "asset_mgmt_fee": ("flat",),
}


def monthly_t12(spec, b, rng):
    end_month = spec["t12_end"]
    months = month_list(end_month, 12)
    base_rent = (b["master_lease"]["annual_rent_aed"] if b["master_lease"] and spec.get("owner_statement_master_lease")
                 else b["in_place_rent_aed"])
    k = spec.get("t12_income_factor", 0.985)
    prof = spec.get("t12_income_profile")  # optional explicit monthly multipliers
    if prof:
        w = prof
    else:
        w = [rng.uniform(0.985, 1.015) for _ in months]
    s = sum(w) / 12.0
    rent_m = [int(round(base_rent / 12.0 * k * x / s)) for x in w]
    oi_m = _spread(rng, "noisy", b["other_income_aed"], months)
    items = b["opex_items"]
    pattern_override = spec.get("opex_patterns", {})
    lines = {}
    for key, annual in items.items():
        if key == "mgmt_fee":
            lines[key] = [int(round(r * spec["mgmt_fee_pct"])) for r in rent_m]
            continue
        p = pattern_override.get(key, ITEM_PATTERN[key])
        if p[0] == "once":
            lines[key] = _spread(rng, "once", annual, months, pay_month=p[1])
        elif p[0] == "multi":
            lines[key] = _spread(rng, "multi", annual, months, pay_months=p[2])
        else:
            lines[key] = _spread(rng, p[0], annual, months)
    # keep annual items equal to the monthly totals
    for key in lines:
        items[key] = sum(lines[key])
    return {"months": months, "rental_income": rent_m, "other_income": oi_m, "opex": lines}
