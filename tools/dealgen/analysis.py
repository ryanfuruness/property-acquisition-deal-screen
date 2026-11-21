"""Metrics, an approximate underwriting estimate (for price calibration only), and reference
implementations of the discrepancy rules used to verify each package plants exactly what truth says.

The estimate is NOT the engine. It mirrors the engine description in docs/DESIGN.md closely enough
to calibrate asking prices; truth.json labels its output as a generator estimate.
"""
from __future__ import annotations

from datetime import date, timedelta

OCC_LIKE = {"occupied", "notice_served", "under_renewal", "legal_case"}


def rera_max_increase(rent, index_rent, bands):
    if index_rent <= 0 or rent >= index_rent:
        return 0.0
    gap = 1 - rent / index_rent
    for b in bands:
        if gap <= b["below_index_up_to"] + 1e-9:
            return b["max_increase"]
    return bands[-1]["max_increase"]


def rr_metrics(rows, roll_date: date, nsa_hint=None):
    """rows: canonical parsed rent-roll rows (dicts with unit_type, area_sqft, status, annual_rent_aed,
    lease_end (iso), ejari_no, asking_rent_aed)."""
    n = len(rows)
    occ = [r for r in rows if r["status"] in OCC_LIKE]
    in_place = sum(r["annual_rent_aed"] or 0 for r in occ)
    vac_asking = sum(r.get("asking_rent_aed") or 0 for r in rows if r["status"] == "vacant")
    area_tot = sum(r["area_sqft"] for r in rows)
    area_occ = sum(r["area_sqft"] for r in occ)
    by_type = {}
    for r in rows:
        t = by_type.setdefault(r["unit_type"], {"units": 0, "occupied": 0, "area_sqft": 0.0, "rent_aed": 0, "occ_area": 0.0})
        t["units"] += 1
        t["area_sqft"] += r["area_sqft"]
        if r["status"] in OCC_LIKE:
            t["occupied"] += 1
            t["rent_aed"] += r["annual_rent_aed"] or 0
            t["occ_area"] += r["area_sqft"]
    for t in by_type.values():
        t["avg_rent_psf"] = round(t["rent_aed"] / t["occ_area"], 2) if t["occ_area"] else None
        t["area_sqft"] = round(t["area_sqft"], 2)
        del t["occ_area"]
    expired = [r["unit"] for r in occ if r["lease_end"] and date.fromisoformat(r["lease_end"]) < roll_date]
    missing_ejari = [r["unit"] for r in occ if not r.get("ejari_no")]
    return {
        "unit_count": n,
        "occupied_units": len(occ),
        "vacant_units": n - len(occ),
        "occupancy_units": round(len(occ) / n, 4),
        "occupancy_area": round(area_occ / area_tot, 4),
        "in_place_rent_aed": in_place,
        "vacant_asking_rent_aed": vac_asking,
        "potential_rent_aed": in_place + vac_asking,
        "total_area_sqft": round(area_tot, 2),
        "by_type": by_type,
        "status_counts": {s: sum(1 for r in rows if r["status"] == s) for s in sorted({r["status"] for r in rows})},
        "expired_but_occupied_units": expired,
        "missing_ejari_units": missing_ejari,
        "deposits_held_aed": sum(r.get("deposit_aed") or 0 for r in occ),
    }


def expiry_profile(units, roll_date: date):
    """Share of in-place rent expiring by month, and max share in any rolling 3- and 12-month window."""
    occ = [u for u in units if u["status"] in OCC_LIKE and u.get("annual_rent_aed")]
    tot = sum(u["annual_rent_aed"] for u in occ)
    by_month = {}
    for u in occ:
        e = u["lease_end"] if isinstance(u["lease_end"], date) else date.fromisoformat(u["lease_end"])
        key = max(e, roll_date).strftime("%Y-%m")  # already expired counts as now
        by_month[key] = by_month.get(key, 0) + u["annual_rent_aed"]
    months = sorted(by_month)

    def window(n):
        best, best_start = 0.0, None
        y, m = roll_date.year, roll_date.month
        for i in range(0, 48):
            mm = (m - 1 + i) % 12 + 1
            yy = y + (m - 1 + i) // 12
            keys = []
            for j in range(n):
                k2 = (mm - 1 + j) % 12 + 1
                y2 = yy + (mm - 1 + j) // 12
                keys.append(f"{y2}-{k2:02d}")
            s = sum(by_month.get(k, 0) for k in keys) / tot
            if s > best + 1e-12:
                best, best_start = s, keys[0]
        return round(best, 4), best_start

    w3, w3s = window(3)
    w12, w12s = window(12)
    nxt12 = sum(v for k, v in by_month.items() if k <= (roll_date.replace(year=roll_date.year + 1) - timedelta(days=1)).strftime("%Y-%m")) / tot
    return {
        "by_month_share": {k: round(by_month[k] / tot, 4) for k in months},
        "max_share_any_3_months": w3, "max_3m_window_start": w3s,
        "max_share_any_12_months": w12, "max_12m_window_start": w12s,
        "share_expiring_next_12_months": round(nxt12, 4),
    }


def over_rent(units, tolerance=0.0):
    occ = [u for u in units if u["status"] in OCC_LIKE and u.get("annual_rent_aed")]
    tot = sum(u["annual_rent_aed"] for u in occ)
    over = [u for u in occ if u["annual_rent_aed"] > u["market_rent_aed"] * (1 + tolerance)]
    excess = sum(u["annual_rent_aed"] - u["market_rent_aed"] for u in over)
    return {
        "share_of_income": round(sum(u["annual_rent_aed"] for u in over) / tot, 4),
        "units": len(over),
        "excess_over_market_aed": int(excess),
    }


def rera_allowed_uplift(units, bands, renewing_before=None):
    """Max contractual uplift at next renewal under Decree 43 bands vs today's index (area reference),
    for every occupied unit (or only those expiring before `renewing_before`)."""
    occ = [u for u in units if u["status"] in OCC_LIKE and u.get("annual_rent_aed")]
    allowed = 0.0
    gap_dist = {"at_or_above_index": 0, "0-10%": 0, "10-20%": 0, "20-30%": 0, "30-40%": 0, ">40%": 0}
    for u in occ:
        e = u["lease_end"] if isinstance(u["lease_end"], date) else date.fromisoformat(u["lease_end"])
        if renewing_before and e >= renewing_before:
            continue
        r, idx = u["annual_rent_aed"], u["market_rent_aed"]
        inc = rera_max_increase(r, idx, bands)
        allowed += min(r * inc, max(0, idx - r))
        g = 1 - r / idx
        k = ("at_or_above_index" if g <= 0 else "0-10%" if g <= 0.10 else "10-20%" if g <= 0.20 else
             "20-30%" if g <= 0.30 else "30-40%" if g <= 0.40 else ">40%")
        gap_dist[k] += 1
    tot = sum(u["annual_rent_aed"] for u in occ)
    return {"allowed_uplift_aed": int(allowed), "allowed_uplift_pct_of_in_place": round(allowed / tot, 4),
            "units_by_gap_to_index": gap_dist}


# --------------------------------------------------------------------------- approximate engine
def estimate(ei, mandate, market):
    uw = mandate["underwriting"]
    ops = uw["operations"]
    area = ei["area"]
    g = uw["market_view"]["rent_growth_by_year"].get(area, uw["market_view"]["rent_growth_by_year"]["default"])[0]
    am = market["areas"][area]
    f = market["unit_type_factors"]
    start = date.fromisoformat(uw["analysis_start"])
    p, dt = ops["renewal_probability"], ops["downtime_months_on_turnover"]
    bands = uw["rera"]["increase_bands"]
    gross = 0.0
    leasing = 0.0
    for u in ei["units"]:
        idx = am["market_rent_aed_psf_1br"] * f[u["type"]] * u["area_sqft"]
        mkt = idx * (1 + g)
        if u["status"] == "vacant" or not u["annual_rent_aed"]:
            gross += mkt * max(0, 12 - dt) / 12
            leasing += mkt / 12 * ops["leasing_fee_months_on_turnover"]
            continue
        cur = u["annual_rent_aed"]
        end = date.fromisoformat(u["lease_end"])
        mb = 0 if end < start else min(12, (end - start).days / 30.44)
        if cur > mkt:
            ren = mkt
        else:
            ren = min(cur * (1 + rera_max_increase(cur, idx, bands)), mkt)
        rest = 12 - mb
        after = p * ren * rest + (1 - p) * mkt * max(0, rest - dt)
        gross += (cur * mb + after) / 12
        if rest > 0:
            leasing += (1 - p) * mkt / 12 * ops["leasing_fee_months_on_turnover"]
    egi = gross * (1 - ops["structural_vacancy"] - ops["collection_loss"]) + ei["other_income_aed"]
    mgmt = egi * ops["property_management_pct_of_egi"]
    defaults = ops["opex_defaults_aed_per_sqft_nsa"]
    opex = {k: v for k, v in ei["opex_aed"].items() if k not in ("property_management", "marketing_leasing")}
    filled = {}
    for k in ["maintenance_repairs", "insurance", "security_cleaning", "utilities_common", "admin_other", "sinking_fund"]:
        if k not in opex and not (k in ("security_cleaning", "utilities_common", "maintenance_repairs") and opex.get("service_charge", 0) > 5 * ei["nsa_sqft"]):
            filled[k] = defaults[k] * ei["nsa_sqft"]
    if ei["chiller_landlord_pays"] and "district_cooling" not in opex:
        filled["district_cooling"] = defaults["district_cooling_if_landlord_pays"] * ei["nsa_sqft"]
    opex_tot = (sum(opex.values()) + sum(filled.values())) * (1 + ops["input_vat_on_opex_pct"])
    noi = egi - mgmt - opex_tot - leasing
    P = ei["price_aed"]
    ac = uw["acquisition_costs"]
    costs = P * ac["dld_transfer_fee_pct"] + ac["dld_admin_aed"] + ac["trustee_fee_aed"] + P * ac["broker_fee_pct"] * (1 + ac["broker_fee_vat_pct"])
    d = uw["debt"]
    loan = P * d["ltv"]
    r = d["base_rate_3m_eibor"] + d["margin"]
    ds = loan * r / (1 - (1 + r) ** -d["amortisation_years"])
    dscr = noi / ds
    # price at which DSCR = covenant
    noi_ratio = noi / P
    price_for_dscr = None
    return {
        "note": "Generator estimate for price calibration only (simplified Year-1 of the engine described in DESIGN.md). Not the engine output.",
        "year1_gross_rent_aed": int(gross), "year1_egi_aed": int(egi), "year1_opex_incl_vat_aed": int(opex_tot),
        "year1_mgmt_fee_aed": int(mgmt), "year1_leasing_fees_aed": int(leasing),
        "opex_defaults_filled": sorted(filled), "year1_noi_aed": int(noi),
        "acquisition_costs_aed": int(costs), "net_yield_on_price": round(noi / P, 4),
        "net_yield_on_total_cost": round(noi / (P + costs), 4), "loan_aed": int(loan),
        "annual_debt_service_aed": int(ds), "dscr_year1": round(dscr, 3),
        "price_at_dscr_1_30_aed": int(noi / (1.30 * d["ltv"] * r / (1 - (1 + r) ** -d["amortisation_years"]))),
    }
