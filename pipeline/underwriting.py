"""Stage 7, underwrite: build engine ``deal_inputs`` from trusted values only, then call the engine.

Rules:
* Only verified OM fields are used. An unverified field is treated as not stated, so a gap
  falls to a mandate default (labelled ``default``) or makes the run unable to underwrite.
* Unit income comes from the rent roll, never from the OM.
* Opex comes from the mapped operating statement (verified lines only); missing categories
  are left out so the engine fills them from mandate defaults and labels them.
* Every input records where it came from (doc, page or cell, quote, verification status).
"""

from __future__ import annotations

import copy
import re
from typing import Any

import engine

from .opex import EXPENSES
from .rentroll import ENGINE_UNIT_TYPES
from .verify import TRUSTED


class CannotUnderwrite(ValueError):
    """A required input is missing or unverified."""


def trusted(fields: dict, name: str) -> dict | None:
    """The field record if it is verified, else None."""
    f = fields.get(name)
    return f if f and f.get("status") in TRUSTED else None


def _om_source(f: dict, name: str) -> dict:
    return {"from": f"om.{name}", "status": f["status"], "doc": f["source"]["doc"], "page": f["source"]["page"],
            "bbox": f["source"].get("bbox"), "quote": f.get("quote")}


def chiller_from_rent_roll(units: list[dict]) -> tuple[bool | None, str]:
    """Read the rent roll's chiller column: True if >= 80% of units say chiller-free / included."""
    texts = [u.get("chiller") for u in units if u.get("chiller")]
    if not texts:
        return None, "no chiller column"
    landlord = sum(1 for t in texts if re.search(r"free|included|landlord|inclusive", t, re.I))
    tenant = sum(1 for t in texts if re.search(r"tenant|empower|emicool|dewa|separate", t, re.I) and
                 not re.search(r"free|included", t, re.I))
    if landlord >= 0.8 * len(texts):
        return True, f"rent roll chiller column: {landlord}/{len(texts)} units chiller-free"
    if tenant >= 0.8 * len(texts):
        return False, f"rent roll chiller column: {tenant}/{len(texts)} units tenant-paid"
    return None, f"rent roll chiller column is mixed ({landlord} landlord, {tenant} tenant of {len(texts)})"


def chiller_landlord_pays(om_fields: dict, units: list[dict]) -> tuple[bool | None, dict]:
    """OM statement first (verified), then the rent roll's chiller column."""
    f = trusted(om_fields, "chiller_arrangement")
    if f and f["value"] in ("landlord_pays", "tenant_pays"):
        return f["value"] == "landlord_pays", _om_source(f, "chiller_arrangement")
    value, note = chiller_from_rent_roll(units)
    return value, {"from": "rent_roll.chiller", "status": "derived" if value is not None else "not_stated",
                   "note": note}


def build_deal_inputs(deal_id: str, om_fields: dict, rent_roll: dict | None, opex: dict | None,
                      market: dict, related_party: bool | None = None,
                      collection_loss_override: float | None = None) -> tuple[dict, dict, list[str]]:
    """Return (deal_inputs, provenance by input, notes). Raises CannotUnderwrite with the reason.

    ``collection_loss_override`` is the observed gap between statement collections and rent-roll rent,
    passed when the collections_gap check fires, so income is underwritten at what is collected.
    """
    prov: dict[str, Any] = {}
    notes: list[str] = []

    price = trusted(om_fields, "asking_price_aed")
    if not price:
        raise CannotUnderwrite("asking price is not stated or not verified")
    prov["price_aed"] = _om_source(price, "asking_price_aed")

    area_f = trusted(om_fields, "market_area")
    if not area_f:
        raise CannotUnderwrite("market area is not verified, so no market reference applies")
    if area_f["value"] not in (market.get("areas") or {}):
        raise CannotUnderwrite(f"area is outside the market reference data ({area_f.get('quote')!r})")
    prov["area"] = _om_source(area_f, "market_area")

    if not rent_roll or not rent_roll.get("units"):
        raise CannotUnderwrite("no parsed rent roll")
    units_in, excluded = [], []
    for u in rent_roll["units"]:
        why = None
        if u["unit_type"] not in ENGINE_UNIT_TYPES:
            why = f"unit type {u.get('unit_type_text')!r} not recognised"
        elif not u["area_sqft"]:
            why = "no area"
        if why:
            excluded.append({"unit": u["unit"], "reason": why, "source": u["source"]["range"]})
            continue
        status, rent = u["status"], u["annual_rent_aed"]
        if status in ("occupied", "under_renewal", "notice_served") and not rent:
            notes.append(f"Unit {u['unit']}: let with no rent on the roll; underwritten as vacant.")
            status = "vacant"
        units_in.append({"unit": u["unit"] or u["source"]["range"], "unit_type": u["unit_type"],
                         "area_sqft": u["area_sqft"], "status": status, "annual_rent_aed": rent,
                         "lease_end": u["lease_end"]})
    if not units_in:
        raise CannotUnderwrite("no rent-roll unit could be underwritten")
    prov["units"] = {"from": "rent_roll", "doc": rent_roll["doc"], "units": len(units_in), "excluded": excluded,
                     "status": "parsed", "note": "unit rows parsed by code from the cells the layout mapping named"}
    if excluded:
        notes.append(f"{len(excluded)} rent-roll row(s) not underwritten: "
                     + "; ".join(f"{e['unit']}: {e['reason']}" for e in excluded[:5]))

    unit_area = sum(u["area_sqft"] for u in units_in)
    nsa_f = trusted(om_fields, "nsa_sqft")
    all_areas = all(u["area_sqft"] for u in rent_roll["units"])
    if all_areas:
        nsa = round(sum(u["area_sqft"] for u in rent_roll["units"]), 1)
        prov["nsa_sqft"] = {"from": "rent_roll.sum_of_unit_areas", "doc": rent_roll["doc"], "status": "derived",
                            "note": "sum of unit areas on the rent roll" + (
                                f"; OM states {nsa_f['value']:,.0f} sq ft" if nsa_f else "")}
    elif nsa_f:
        nsa = nsa_f["value"]
        prov["nsa_sqft"] = _om_source(nsa_f, "nsa_sqft")
    else:
        nsa = round(unit_area, 1)
        prov["nsa_sqft"] = {"from": "rent_roll.sum_of_unit_areas", "status": "derived",
                            "note": "some units have no area; sum of the rest"}

    bua_f = trusted(om_fields, "bua_sqft")
    if bua_f:
        prov["bua_sqft"] = _om_source(bua_f, "bua_sqft")

    deal_inputs: dict[str, Any] = {
        "deal_id": deal_id, "price_aed": price["value"], "area": area_f["value"], "nsa_sqft": nsa,
        "bua_sqft": bua_f["value"] if bua_f else None, "units": units_in,
    }
    year = trusted(om_fields, "completion_year")
    if year:
        deal_inputs["completion_year"] = int(year["value"])
        prov["completion_year"] = _om_source(year, "completion_year")
    deposits = rent_roll["summary"].get("deposits_aed") or 0
    if deposits > 0:
        deal_inputs["security_deposits_aed"] = deposits
        prov["security_deposits_aed"] = {"from": "rent_roll.sum_of_deposits", "doc": rent_roll["doc"],
                                         "status": "parsed", "note": "sum of the deposit column; a closing credit"}
    if collection_loss_override is not None:
        deal_inputs["collection_loss_override"] = round(collection_loss_override, 4)
        prov["collection_loss_override"] = {"from": "collections_gap", "status": "derived",
                                            "note": "statement rental income vs rent-roll in-place rent"}
    if rent_roll["summary"].get("as_of"):
        deal_inputs["rent_roll_date"] = rent_roll["summary"]["as_of"]
        prov["rent_roll_date"] = {"from": "rent_roll.as_of", "doc": rent_roll["doc"], "status": "parsed",
                                  **(rent_roll.get("as_of_source") or {})}

    master = rent_roll.get("master_lease")
    if master and master.get("annual_rent_aed") and master.get("lease_end"):
        deal_inputs["master_lease"] = {"tenant": master.get("tenant"), "related_party": related_party,
                                       "annual_rent_aed": master["annual_rent_aed"],
                                       "lease_end": master["lease_end"], "cheques": master.get("cheques")}
        prov["master_lease"] = {"from": "rent_roll.master_lease", "doc": rent_roll["doc"],
                                "cells": master["source"]["cells"], "status": "parsed",
                                "related_party_from": "model review (verified quotes)" if related_party is not None
                                else "unknown"}

    # opex: verified statement lines only; absent categories fall to mandate defaults in the engine
    if opex:
        totals = opex["totals_by_category"]
        stated = {c: totals[c] for c in EXPENSES if totals.get(c)}
        deal_inputs["opex_aed"] = stated
        for c, v in stated.items():
            prov[f"opex_aed.{c}"] = {"from": "operating_statement", "doc": opex["doc"], "status": "verified",
                                     "lines": [ln["source"] | {"label": ln["label"], "amount_aed": ln["amount_aed"]}
                                               for ln in opex["lines"] if ln["category"] == c
                                               and ln["status"] == "verified"],
                                     "annualisation": opex["period"]["annualisation"]}
        if totals.get("other_income"):
            deal_inputs["other_income_aed"] = totals["other_income"]
            prov["other_income_aed"] = {"from": "operating_statement", "doc": opex["doc"], "status": "verified"}
        if opex.get("vat_basis") == "includes_vat":
            deal_inputs["opex_includes_vat"] = True
    else:
        notes.append("No operating statement: every cost is a mandate default.")

    chiller, chiller_src = chiller_landlord_pays(om_fields, rent_roll["units"])
    deal_inputs["chiller_landlord_pays"] = chiller
    prov["chiller_landlord_pays"] = chiller_src

    om_stated = om_stated_block(om_fields)
    if om_stated:
        deal_inputs["om_stated"] = om_stated
        prov["om_stated"] = {k: _om_source(om_fields[n], n) for k, n in
                             (("annual_rent_aed", "annual_rent_stated"), ("net_income_aed", "net_income_stated_aed"),
                              ("yield", "yield_stated")) if trusted(om_fields, n)}
    return deal_inputs, prov, notes


def om_stated_block(om_fields: dict) -> dict | None:
    """The OM's own income and yield, verified fields only, for the engine's yield check."""
    y = trusted(om_fields, "yield_stated")
    rent = trusted(om_fields, "annual_rent_stated")
    net = trusted(om_fields, "net_income_stated_aed")
    if not y and not rent:
        return None
    basis = (y or {}).get("basis") or {"measure": "unstated", "on": "unstated"}
    return {"annual_rent_aed": rent["value"] if rent else None, "net_income_aed": net["value"] if net else None,
            "yield": y["value"] if y else None,
            "yield_basis": {"measure": basis.get("measure", "unstated"), "on": basis.get("on", "unstated")}}


def deal_facts(om_fields: dict, rent_roll: dict | None, related_party: bool | None,
               lease_structure: str | None) -> tuple[dict, dict]:
    """Facts for ``engine.mandate_fit`` from verified fields; unknowns stay None. Returns (facts, provenance)."""
    facts: dict[str, Any] = {}
    prov: dict[str, Any] = {}
    f = trusted(om_fields, "asset_type")
    if f:
        # the mandate counts a residential building with ground-floor retail as residential
        facts["asset_type"] = "residential_building" if f["value"] in (
            "residential_building", "mixed_use_residential_retail") else f["value"]
        prov["asset_type"] = _om_source(f, "asset_type")
    f = trusted(om_fields, "market_area")
    if f:
        facts["area"] = f["value"] if f["value"] != "none_of_these" else (om_fields.get("area") or {}).get("value")
        prov["area"] = _om_source(f, "market_area")
    f = trusted(om_fields, "title_type")
    if f:
        tenure, own = f["value"].get("tenure"), f["value"].get("ownership")
        if "unstated" not in (tenure, own):
            facts["title_type"] = f"{tenure}_{own}"
            prov["title_type"] = _om_source(f, "title_type")
    if rent_roll and rent_roll.get("units"):
        facts["unit_count"] = rent_roll["summary"]["unit_count"]
        prov["unit_count"] = {"from": "rent_roll", "doc": rent_roll["doc"], "status": "parsed"}
    f = trusted(om_fields, "asking_price_aed")
    if f:
        facts["price_aed"] = f["value"]
        prov["price_aed"] = _om_source(f, "asking_price_aed")
    f = trusted(om_fields, "completion_year")
    if f:
        facts["completion_year"] = f["value"]
        prov["completion_year"] = _om_source(f, "completion_year")
    if lease_structure in ("direct_leases", "master_lease"):
        facts["lease_structure"] = lease_structure
    if related_party is not None:
        facts["master_lease_related_party"] = related_party
    prov["lease_structure"] = {"from": "OM lease_structure (verified) and model review", "value": lease_structure,
                               "related_party": related_party}
    return facts, prov


def underwrite(deal_inputs: dict, mandate: dict, market: dict) -> dict:
    """Call the engine. Pure; raises engine.DealInputError / MarketDataError."""
    return engine.underwrite(copy.deepcopy(deal_inputs), mandate, market)


def metric(result: dict | None, name: str) -> float | None:
    if not result:
        return None
    m = (result.get("metrics") or {}).get(name)
    return None if m is None else m.get("value")


def with_changes(deal_inputs: dict, **changes: Any) -> dict:
    """Copy of deal_inputs with top-level changes (used to price discrepancies with the engine)."""
    out = copy.deepcopy(deal_inputs)
    for k, v in changes.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def impact(base_inputs: dict, base_result: dict, alt_inputs: dict, mandate: dict, market: dict,
           metric_name: str = "noi_year1") -> dict | None:
    """Engine-computed difference between the base case and an alternative reading of the documents.

    Returns ``{"metric", "base", "alternative", "delta_aed", "walk_away_delta_aed"}``. Positive delta
    means the alternative reading is better for the buyer than the screen's base case.
    """
    try:
        alt = underwrite(alt_inputs, mandate, market)
    except (engine.DealInputError, engine.MarketDataError):
        return None
    b, a = metric(base_result, metric_name), metric(alt, metric_name)
    wb, wa = metric(base_result, "walk_away_price_aed"), metric(alt, "walk_away_price_aed")
    if b is None or a is None:
        return None
    return {"metric": metric_name, "base": round(b, 0), "alternative": round(a, 0), "delta_aed": round(a - b, 0),
            "walk_away_delta_aed": round(wa - wb, 0) if wa is not None and wb is not None else None}



def noi_bridge(uw: dict | None, opex: dict | None) -> dict | None:
    """Statement NOI to the screen's Year-1 NOI, one engine component at a time (all from engine Year-1 lines).

    Each step is ``{label, aed}`` with the sign of its effect on NOI; the steps sum to the screen NOI exactly
    (any rounding remainder is shown, never hidden).
    """
    if not uw or not opex:
        return None
    y1 = {k: v["values"][0] for k, v in uw["cash_flow"]["lines"].items() if isinstance(v, dict) and "values" in v}
    by_cat = {k: v["values"][0] for k, v in uw["cash_flow"]["opex_by_category"].items()}
    stated = opex["totals_by_category"]
    inputs = uw.get("inputs") or {}
    steps = []
    statement_income = sum(stated.get(k, 0.0) for k in ("rental_income", "other_income"))
    steps.append({"label": "income: rent-roll leases modelled lease by lease, net of re-letting downtime, vs "
                           "statement income", "aed": y1["gross_income"] - statement_income})
    # the engine's vacancy allowance is met by modelled downtime; only the structural top-up and the collection
    # loss come off gross income
    steps.append({"label": "structural vacancy top-up and collection loss (house view), vs statement losses",
                  "aed": -(y1.get("structural_vacancy", 0) + y1.get("collection_loss", 0)) + opex["total_deductions_aed"]})
    steps.append({"label": "management fee at the mandate rate on EGI, vs the stated fee",
                  "aed": -(y1["management_fee"] - stated.get("property_management", 0.0))})
    carried = 0.0
    for cat, amount in by_cat.items():
        if cat == "property_management":
            continue
        prov = (inputs.get(f"deal.opex_aed.{cat}") or {}).get("provenance")
        diff = amount - stated.get(cat, 0.0)
        if prov == "default" and amount:
            steps.append({"label": f"{cat.replace('_', ' ')}: absent from the statement, mandate default", "aed": -amount})
        else:
            carried += diff
    if abs(carried) >= 1:
        steps.append({"label": "stated costs carried to Year 1", "aed": -carried})
    if y1.get("leasing_fees"):
        steps.append({"label": "leasing fees on modelled turnover", "aed": -y1["leasing_fees"]})
    if y1.get("input_vat"):
        steps.append({"label": "irrecoverable input VAT on costs", "aed": -y1["input_vat"]})
    total = opex["noi_aed"] + sum(st["aed"] for st in steps)
    if abs(total - y1["noi"]) >= 1:
        steps.append({"label": "other", "aed": y1["noi"] - total})
    return {"statement_noi_aed": round(opex["noi_aed"], 0), "screen_noi_year1_aed": round(y1["noi"], 0),
            "steps": [{"label": st["label"], "aed": round(st["aed"], 0)} for st in steps if abs(st["aed"]) >= 1]}
