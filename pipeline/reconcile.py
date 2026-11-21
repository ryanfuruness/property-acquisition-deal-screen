"""Stage 6, reconcile: deterministic rules, then a model review for what rules cannot test.

Each rule-detected item of the DESIGN.md catalogue is one function below, with its thresholds
in :class:`pipeline.config.ReconcileThresholds`. A rule reads only verified OM fields, the
code-parsed rent roll, the code-totalled statement and the engine result; it returns zero or
one discrepancy record. Impacts are computed by the engine wherever the discrepancy changes an
engine input (``underwriting.impact``), otherwise they are stated as the gap between sources.

The model review (``review``) covers the catalogue items marked (model) and OM language. Every
finding must carry at least one quote that code verifies on its page or cell; findings without
one are rejected and recorded, never shown as discrepancies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import config
from .config import ReconcileThresholds
from .extract import om_content
from .ingest import Document, sheet_as_text
from .llm import ModelClient, ToolResult, load_prompt
from .numbers import close
from .opex import EXPENSES as OPEX_EXPENSES
from .schemas import om_tools
from .underwriting import impact, metric, trusted, with_changes
from .verify import TRUSTED, contains_any, verify_evidence

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_MEASURE_UNIT = {"annual_rent": "aed", "deposit": "aed", "area": "sqft", "occupancy": "pct",
                 "unit_count": "count", "occupied_units": "count", "vacant_units": "count"}

# Costs an owners' association budget (service charge) covers in a strata building.
COMMON_AREA_CATEGORIES = ("utilities_common", "security_cleaning", "maintenance_repairs", "district_cooling")
# Costs a landlord still bears while a master tenant runs the building.
LANDLORD_COSTS_UNDER_MASTER_LEASE = ("insurance", "sinking_fund")

# Words a quote must contain for a model title doubt to stand against a verified freehold tenure. Title check
# (catalogue 16) is about tenure and eligibility; strata ownership is tested by the mandate's title filter.
TITLE_DOUBT_KEYWORDS = ("non-freehold", "non freehold", "leasehold", "gcc", "uae national", "nationals",
                        "restricted", "eligib", "usufruct", "musataha", "grant")


@dataclass
class Context:
    """Everything the rules read. ``uw`` and ``deal_inputs`` are None if the deal could not be underwritten."""

    om: dict
    rr: dict | None
    opex: dict | None
    uw: dict | None
    deal_inputs: dict | None
    mandate: dict
    market: dict
    t: ReconcileThresholds = config.THRESHOLDS

    def f(self, name: str) -> dict | None:
        return trusted(self.om, name)

    def m(self, name: str) -> float | None:
        return metric(self.uw, name)


# Every source carries the display unit of its value, for the site: aed | pct | sqft | count | date | text.
SOURCE_UNITS = ("aed", "pct", "sqft", "count", "date", "text")


def record(id: str, severity: str, title: str, sources: list[dict], relied_on: str, why: str,
           impact_: dict | None, analyst_action: str, detected_by: str = "rule") -> dict:
    """A discrepancy in the DESIGN.md shape."""
    return {"id": id, "severity": severity, "title": title, "sources": sources, "relied_on": relied_on,
            "why": why, "impact": impact_, "analyst_action": analyst_action, "detected_by": detected_by}


def om_source(field: dict, unit: str, value: Any = None, label: str | None = None) -> dict:
    s = field["source"]
    v = field["value"] if value is None else value
    return {"doc": s["doc"], "page": s["page"], "bbox": s.get("bbox") or [], "quote": field.get("quote"),
            "value": v, "unit": unit, **({"label": label} if label else {})}


def rr_source(rr: dict, value: Any, label: str, unit: str, cells: str | None = None) -> dict:
    return {"doc": rr["doc"], "cell": cells or rr_range(rr), "value": value, "unit": unit, "label": label}


def rr_range(rr: dict) -> str:
    """Cell range(s) of the unit rows, from the layout the model mapped."""
    parts = []
    for t in rr["layout"].get("tables", []):
        cols = [c.get("column") for c in t.get("columns", []) if c.get("column")]
        last_col = max(cols, key=lambda c: (len(c), c)) if cols else "A"
        parts.append(f"{t['sheet']}!A{t.get('first_data_row')}:{last_col}{t.get('last_data_row')}")
    return ", ".join(parts)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _aed(x: float | None) -> str:
    return "n/a" if x is None else f"AED {x:,.0f}"


# ---------------------------------------------------------------------------- rules (catalogue order)


def occupancy_mismatch(c: Context) -> dict | None:
    f = c.f("occupancy_stated")
    if not f or not c.rr:
        return None
    s = c.rr["summary"]
    om_occ, rr_occ = f["value"], s["occupancy_by_units"]
    if rr_occ is None or abs(om_occ - rr_occ) <= c.t.occupancy_points + 1e-9:
        return None
    gap_units = round((om_occ - rr_occ) * s["unit_count"])
    let_avg = s["in_place_rent_aed"] / s["let_units"] if s["let_units"] else 0
    dated = f" (as of {f['as_of']})" if f.get("as_of") else " (undated)"
    return record(
        "occupancy_mismatch", "high" if abs(om_occ - rr_occ) > 0.05 else "medium",
        f"OM occupancy {_pct(om_occ)} vs rent roll {_pct(rr_occ)}",
        [om_source(f, label=f"OM occupancy{dated}", unit="pct"),
         rr_source(c.rr, rr_occ, f"rent roll: {s['let_units']} of {s['unit_count']} units let"
                   + (f" at {s['as_of']}" if s["as_of"] else ""), "pct")],
        "rent_roll",
        f"The rent roll is unit-level{' and dated ' + s['as_of'] if s['as_of'] else ''}; the OM figure{dated} "
        f"is a headline the screen cannot trace to units. A gap of {abs(om_occ - rr_occ) * 100:.1f} points is "
        f"about {abs(gap_units)} units.",
        {"metric": "annual_rent", "delta_aed": round(-abs(gap_units) * let_avg, 0),
         "basis": f"{abs(gap_units)} units x average in-place rent {_aed(let_avg)} (estimate of income the OM implies "
                  f"but the roll does not show)"},
        "Ask for the Ejari export and the vacancy list at the rent-roll date; reconcile the OM figure to unit numbers.")


def potential_rent_as_income(c: Context) -> dict | None:
    f = c.f("annual_rent_stated")
    if not f or not c.rr:
        return None
    s = c.rr["summary"]
    om_rent, in_place, potential = f["value"], s["in_place_rent_aed"], s["potential_rent_aed"]
    ml = c.rr.get("master_lease")
    if ml and ml.get("annual_rent_aed") and close(om_rent, ml["annual_rent_aed"], rel=c.t.potential_rent_tolerance):
        return None    # the OM income is the master-lease rent; master_lease_related_party covers it
    basis = f.get("basis")
    market_vacant = None
    if c.uw:
        units = c.uw["unit_schedule"]["units"]
        market_vacant = sum(u["market_rent_reference_aed"] for u in units if u["status"] == "vacant")
    how = None
    if basis == "potential":
        how = "the OM itself calls the figure potential income"
    elif om_rent > in_place * (1 + c.t.in_place_excess):
        if s["vacant_units_with_asking_rent"] and close(om_rent, potential, rel=c.t.potential_rent_tolerance):
            how = (f"it equals the rent roll's in-place rent plus asking rent on {s['vacant_units_with_asking_rent']} "
                   f"vacant units ({_aed(potential)})")
        elif market_vacant and close(om_rent, in_place + market_vacant, rel=0.03):
            how = f"it is close to in-place rent plus market rent on the vacant units ({_aed(in_place + market_vacant)})"
        else:
            how = f"it is {om_rent / in_place - 1:.1%} above the rent roll's in-place rent"
    if not how:
        return None
    yield_note = ""
    if c.uw and c.f("asking_price_aed"):
        yield_note = (f" Gross yield on price falls from {_pct(om_rent / c.f('asking_price_aed')['value'])} "
                      f"to {_pct(c.m('gross_yield_in_place_on_price'))} on in-place rent.")
    return record(
        "potential_rent_as_income", "high" if om_rent > in_place * 1.03 else "medium",
        f"OM income {_aed(om_rent)} vs in-place rent {_aed(in_place)}",
        [om_source(f, label=f"OM annual rent (basis: {basis})", unit="aed"),
         rr_source(c.rr, in_place, f"rent roll in-place rent, {s['let_units']} let units", "aed"),
         rr_source(c.rr, potential, "rent roll potential incl. asking rent on vacant units", "aed")],
        "rent_roll",
        f"The OM figure is not contracted income: {how}. The screen underwrites let units at their contract "
        f"rent and vacant units at market after downtime.{yield_note}",
        {"metric": "annual_rent", "delta_aed": round(in_place - om_rent, 0),
         "basis": "rent-roll in-place rent minus OM stated income"},
        "Ask for signed leases or Ejari certificates behind any unit the OM counts as income; treat the rest as vacant.")


def gross_yield_as_net(c: Context) -> dict | None:
    f = c.f("yield_stated")
    if not f or (f.get("basis") or {}).get("measure") != "net" or not c.uw:
        return None
    check = c.uw.get("om_yield_check") or {}
    stated = f["value"]
    price = c.f("asking_price_aed")["value"] if c.f("asking_price_aed") else None
    rent_f = c.f("annual_rent_stated")
    om_rent = rent_f["value"] if rent_f else c.rr["summary"]["in_place_rent_aed"]
    gross = om_rent / price if price else None          # the OM's rent on asking price, for comparison only
    buyer = (check.get("buyer_net_on_total_cost") or {}).get("value")
    on_cost = (f.get("basis") or {}).get("on") == "total_cost"
    denom = (c.m("total_cost_aed") if on_cost else price) or price
    net_f = c.f("net_income_stated_aed")
    implied_net = net_f["value"] if net_f else (stated * denom if denom else None)
    buyer_costs = c.m("operating_costs_year1")
    noi = c.m("noi_year1")
    reasons = []
    if gross is not None and abs(stated - gross) <= c.t.net_vs_gross_points:
        reasons.append(f"the 'net' yield equals the gross yield on asking price ({_pct(gross)})")
    if implied_net is not None and buyer_costs:
        deducted = om_rent - implied_net
        if deducted < c.t.net_yield_min_cost_share * buyer_costs:
            reasons.append(f"it deducts {_aed(max(deducted, 0))} of costs from {_aed(om_rent)}, against "
                           f"{_aed(buyer_costs)} of Year-1 operating costs a buyer bears")
    if not reasons:
        return None
    sources = [om_source(f, label=f"OM 'net' yield ({(f.get('basis') or {}).get('on')})", unit="pct")]
    if net_f:
        sources.append(om_source(net_f, label="OM net income", unit="aed"))
    return record(
        "gross_yield_as_net", "high", f"OM 'net' yield {_pct(stated)} vs buyer's net {_pct(buyer)}",
        sources + [{"doc": "engine", "value": buyer, "unit": "pct", "label": "Year-1 NOI / (price + acquisition costs), engine"}],
        "engine",
        "The OM calls the yield net, but " + "; and ".join(reasons) + ". The screen uses Year-1 NOI after the "
        "mandate's vacancy, collection loss, management fee, full opex and input VAT.",
        {"metric": "noi", "delta_aed": round(noi - implied_net, 0) if implied_net is not None and noi is not None else None,
         "basis": "engine Year-1 NOI minus the net income the OM yield implies"},
        "Ask the broker for the costs behind the net yield; rebuild NOI from the operating statement and service-charge budget.")


def yield_excludes_acquisition_costs(c: Context) -> dict | None:
    f = c.f("yield_stated")
    if not f or not c.uw:
        return None
    on = (f.get("basis") or {}).get("on", "unstated")
    check = c.uw.get("om_yield_check") or {}
    if on == "total_cost":
        return None
    if on == "unstated" and not check.get("reproduces_stated"):
        return None    # cannot tell what the denominator is
    stated = f["value"]
    measure = (f.get("basis") or {}).get("measure", "unstated")
    on_cost = (check.get("stated_income_on_total_cost") if measure != "net" else check.get("buyer_net_on_total_cost")) or {}
    acq = c.m("acquisition_costs_aed")
    return record(
        "yield_excludes_acquisition_costs", "medium",
        f"OM yield {_pct(stated)} is on asking price, before {_pct(c.m('acquisition_costs_pct_of_price'))} acquisition costs",
        [om_source(f, label="OM yield" + (" (denominator not stated; reproduces on asking price)" if on == "unstated" else ""),
                   unit="pct"),
         {"doc": "engine", "value": acq, "unit": "aed", "label": "acquisition costs (DLD 4%, broker, trustee, mortgage registration)"}],
        "engine",
        f"A buyer pays {_aed(acq)} on top of the price. On price plus costs the same income gives "
        f"{_pct(on_cost.get('value'))}.",
        {"metric": "yield", "delta": round((on_cost.get("value") or stated) - stated, 4),
         "basis": "OM income on price plus acquisition costs, minus the stated yield"},
        "Compare deals on yield on total cost; ask the broker to restate the yield on that basis.")


def over_rented_vs_market(c: Context) -> dict | None:
    if not c.uw:
        return None
    share = c.m("over_rent_share_of_income")
    limit = c.t.over_rent_material_share or c.mandate["buy_box"]["soft"].get("max_over_rent_share_of_income", 0.2)
    if share is None or share <= limit:
        return None
    units = [u for u in c.uw["unit_schedule"]["units"] if (u.get("rent_vs_market") or 0) > 0
             and u["status"] in ("occupied", "under_renewal", "notice_served")]
    excess = sum(u["in_place_rent_aed"] - u["market_rent_reference_aed"] for u in units)
    alt_units = []
    for u in c.deal_inputs["units"]:
        ref = next((x for x in units if x["unit"] == str(u["unit"])), None)
        alt_units.append(u | {"annual_rent_aed": ref["market_rent_reference_aed"]} if ref else u)
    imp = impact(c.deal_inputs, c.uw, with_changes(c.deal_inputs, units=alt_units), c.mandate, c.market)
    if imp:
        imp["basis"] = (f"engine Year-1 NOI with the {len(units)} over-rented leases at market reference rent today, "
                        f"minus the base case (which resets them only at expiry)")
    return record(
        "over_rented_vs_market", "high" if share > 2 * limit else "medium",
        f"{_pct(share)} of in-place rent is from units let above market",
        [rr_source(c.rr, round(sum(u["in_place_rent_aed"] for u in units), 0),
                   f"{len(units)} let units above the area reference rent", "aed"),
         {"doc": "data/market/areas.yaml", "value": c.deal_inputs["area"], "unit": "text", "label": "area reference rent (illustrative)"}],
        "engine",
        f"In a falling 2026 market these leases are {_aed(excess)} a year above reference rent; the engine resets "
        f"each to market at expiry. The mandate limit is {_pct(limit)}.",
        imp, "Check the over-rented leases' expiry dates and tenants; price the reset into the offer.")


def upside_exceeds_rera_cap(c: Context) -> dict | None:
    claims = [cl for cl in c.om.get("upside_claims", []) if cl["status"] in TRUSTED and cl.get("claimed_uplift")]
    if not claims or not c.uw:
        return None
    # the engine's own renewal rule (RERA bands, notice window, market path) at each unit's first expiry
    # in the next 24 months; a claim is flagged only if it exceeds what the best-placed unit can get
    changes = []
    for u in c.uw["unit_schedule"]["units"]:
        ev = next((e for e in u.get("events", []) if e.get("type") == "expiry"), None)
        if ev and ev.get("current_rent") and ev.get("renewal_rent") is not None and ev["month"] < 24:
            changes.append((ev["renewal_rent"] / ev["current_rent"] - 1, ev["current_rent"]))
    if not changes:
        return None
    best = max(ch for ch, _ in changes)
    average = sum(ch * w for ch, w in changes) / sum(w for _, w in changes)
    worst = max(claims, key=lambda cl: cl["claimed_uplift"])
    if worst["claimed_uplift"] <= best + c.t.rera_claim_tolerance_points:
        return None
    allowed = best
    return record(
        "upside_exceeds_rera_cap", "high",
        f"OM claims {_pct(worst['claimed_uplift'])} rental uplift; RERA bands and the market allow at most {_pct(allowed)}",
        [{"doc": worst["source"]["doc"], "page": worst["source"]["page"], "bbox": worst["source"]["bbox"],
          "quote": worst["quote"], "value": worst["claimed_uplift"], "unit": "pct", "label": "OM upside claim"},
         {"doc": "engine", "value": round(allowed, 4), "unit": "pct",
          "label": "largest change at renewal for any lease expiring in the next 24 months (RERA bands, notice period)"},
         {"doc": "engine", "value": round(average, 4), "unit": "pct", "label": "rent-weighted average change at those renewals"}],
        "engine",
        "Under the RERA rent-increase bands a renewal increase is capped by how far the rent sits below the RERA "
        "index, and needs prior written notice; over-rented units reset down. Applied unit by unit, no lease expiring in the next two "
        f"years can rise by more than {_pct(allowed)}, and renewals move rent by {_pct(average)} on average, not "
        f"{_pct(worst['claimed_uplift'])}.",
        {"metric": "rent_change_at_renewal", "delta": round(allowed - worst["claimed_uplift"], 4),
         "basis": "engine renewal rule minus OM claim"},
        "Ignore the claimed reversion; ask the broker which units it relies on and check each against the RERA calculator.")


def missing_opex_items(c: Context) -> dict | None:
    if not c.opex or not c.uw:
        return None
    absent = list(c.opex["absent_standard_categories"])
    totals = c.opex["totals_by_category"]
    stated_opex = sum(v for k, v in totals.items() if k in OPEX_EXPENSES)
    title = c.f("title_type")
    strata = bool(title and (title["value"] or {}).get("ownership") == "strata")
    oa_budget = strata or (stated_opex and totals.get("service_charge", 0) >= c.t.oa_service_charge_share * stated_opex)
    if oa_budget:   # the owners' association budget pays for common services
        absent = [a for a in absent if a not in COMMON_AREA_CATEGORIES]
    if (c.rr or {}).get("master_lease"):
        # under a master lease the operator bears running costs; the landlord keeps only these
        absent = [a for a in absent if a in LANDLORD_COSTS_UNDER_MASTER_LEASE]
    if not absent:
        return None
    priced = [a for a in absent if a != "property_management"]   # the engine always charges its own fee
    alt = dict(c.deal_inputs.get("opex_aed") or {})
    for a in priced:
        alt[a] = 0.0
    imp = impact(c.deal_inputs, c.uw, with_changes(c.deal_inputs, opex_aed=alt), c.mandate, c.market) if priced else None
    if imp:
        imp["basis"] = ("engine Year-1 NOI if the absent costs were zero, as the statement implies, minus the base "
                        "case with mandate defaults; the delta is how much the statement overstates NOI")
    chiller = "district_cooling" in absent
    defaults = {k: v for k, v in (c.uw.get("inputs") or {}).items() if k.startswith("deal.opex_aed.")
                and v.get("provenance") == "default" and k.split(".")[-1] in absent}
    material = chiller or (imp and c.m("noi_year1") and abs(imp["delta_aed"]) > 0.05 * c.m("noi_year1"))
    return record(
        "missing_opex_items", "high" if material else "medium",
        "Operating statement omits " + ", ".join(a.replace("_", " ") for a in absent),
        [{"doc": c.opex["doc"], "value": None, "unit": "aed", "label": f"no line for {a.replace('_', ' ')}"} for a in absent]
        + [{"doc": "data/mandate.yaml", "value": v["value"], "unit": "aed", "label": f"mandate default for {k.split('.')[-1]}"}
           for k, v in defaults.items()],
        "mandate_defaults",
        ("The building is chiller-free, so the landlord pays district cooling, yet the statement has no cooling line. "
         if chiller else "") + "A whole-building owner bears these costs; the screen fills each from the mandate "
        "default per sq ft of NSA (the management fee is always the mandate's % of EGI).",
        imp, "Request the missing bills (Empower/chiller, insurance schedule, reserve study, management agreement).")


def area_basis_confusion(c: Context) -> dict | None:
    findings, sources = [], []
    nsa = c.f("nsa_sqft")
    rr_area = c.rr["summary"]["area_sqft_total"] if c.rr else None
    if nsa and rr_area and (nsa.get("stated") or {}).get("unit", "sqft") == "sqft":
        ratio = nsa["value"] / rr_area
        if abs(ratio * config.SQM_TO_SQFT - 1) < c.t.sqm_ratio_tolerance:
            findings.append(f"OM NSA {nsa['value']:,.0f} is the rent roll's area in sq m labelled sq ft")
        elif abs(ratio / config.SQM_TO_SQFT - 1) < c.t.sqm_ratio_tolerance:
            findings.append(f"OM NSA {nsa['value']:,.0f} looks like sq ft read as sq m")
        if findings:
            sources += [om_source(nsa, label="OM NSA", unit="sqft"), rr_source(c.rr, rr_area, "sum of rent-roll unit areas (sq ft)", "sqft")]
    psf = c.f("price_psf_stated")
    bua, price = c.f("bua_sqft"), c.f("asking_price_aed")
    if psf and price and (psf.get("basis") or "unstated") == "unstated":
        on_bua = price["value"] / bua["value"] if bua else None
        on_nsa = c.m("price_per_sqft_nsa")
        if on_bua and close(psf["value"], on_bua, rel=c.t.psf_match_tolerance) and not (
                on_nsa and close(psf["value"], on_nsa, rel=c.t.psf_match_tolerance)):
            findings.append(f"the OM's AED {psf['value']:,.0f}/sq ft is on BUA without saying so; on NSA it is "
                            f"AED {on_nsa:,.0f}/sq ft" if on_nsa else "")
            sources += [om_source(psf, label="OM price per sq ft (basis not stated)", unit="aed"),
                        om_source(bua, label="OM BUA", unit="sqft")]
            if on_nsa:
                sources.append({"doc": "engine", "value": round(on_nsa, 0), "unit": "aed", "label": "price per sq ft NSA (rent-roll area)"})
    if not findings:
        return None
    return record(
        "area_basis_confusion", "medium", "Area basis: " + "; ".join(x for x in findings if x),
        sources, "rent_roll",
        "Price per sq ft and opex per sq ft are only comparable on the same area basis. The screen uses the "
        "rent roll's unit areas (converted to sq ft) as NSA.",
        {"metric": "price_per_sqft_nsa", "value": round(c.m("price_per_sqft_nsa"), 0) if c.m("price_per_sqft_nsa") else None},
        "Ask for the title deed and affection plan areas; restate price per sq ft on NSA.")


def rent_roll_does_not_foot(c: Context) -> dict | None:
    if not c.rr or not c.rr.get("stated_totals"):
        return None
    s = c.rr["summary"]
    computed = {
        "annual_rent": [s["in_place_rent_aed"], s["potential_rent_aed"]],
        "area": [s["area_sqft_total"]] + ([round(s["area_sqft_total"] / config.SQM_TO_SQFT, 1)]),
        "unit_count": [s["unit_count"]],
        "occupied_units": [s["let_units"], s["status_counts"]["occupied"]],
        "vacant_units": [s["vacant_units"]],
        "occupancy": [s["occupancy_by_units"], s["occupancy_by_area"]],
        "deposit": [s["deposits_aed"]],
    }
    ml_cells = set(((c.rr.get("master_lease") or {}).get("source") or {}).get("cells", {}).values())
    ml_sheets = {x.split("!")[0] for x in ml_cells}
    breaks = []
    for st in c.rr["stated_totals"]:
        if st["cell"] in ml_cells or st["cell"].split("!")[0] in ml_sheets:
            continue    # a master-lease term, not a total of unit rows
        options = computed.get(st["measure"])
        if not options:
            continue
        tol = 0.0051 if st["measure"] == "occupancy" else max(c.t.foot_abs_tolerance_aed if st["measure"] in
                                                               ("annual_rent", "deposit") else 0.5, 0)
        ok = any(o is not None and (abs(st["value"] - o) <= tol or close(st["value"], o, rel=c.t.foot_rel_tolerance))
                 for o in options)
        if not ok:
            breaks.append((st, options[0]))
    if not breaks:
        return None
    rent_break = next((b for b in breaks if b[0]["measure"] == "annual_rent"), None)
    sources = []
    for st, comp in breaks:
        sources.append({"doc": c.rr["doc"], "cell": st["cell"], "page": st.get("page"), "bbox": [st["bbox"]] if st.get("bbox") else [],
                        "value": st["value"], "unit": _MEASURE_UNIT.get(st["measure"], "count"), "label": f"stated {st['measure'].replace('_', ' ')} ({st['label']})"})
        sources.append(rr_source(c.rr, comp, f"sum of unit rows: {st['measure'].replace('_', ' ')}",
                                 _MEASURE_UNIT.get(st["measure"], "count")))
    return record(
        "rent_roll_does_not_foot", "high" if rent_break and abs(rent_break[0]["value"] - rent_break[1]) > 0.02 * rent_break[1] else "medium",
        "Rent roll totals do not equal the sum of its rows: " + ", ".join(b[0]["measure"].replace("_", " ") for b in breaks),
        sources, "rent_roll_rows",
        "The stated total is not the sum of the unit rows (it may be stale or typed over). The screen re-sums the "
        "rows and ignores the stated totals.",
        {"metric": "annual_rent", "delta_aed": round(rent_break[1] - rent_break[0]["value"], 0),
         "basis": "sum of rows minus stated total"} if rent_break else None,
        "Ask the property manager for a system export of the rent roll at the same date.")


def unit_mix_mismatch(c: Context) -> dict | None:
    if not c.rr:
        return None
    s = c.rr["summary"]
    diffs, sources = [], []
    uc = c.f("unit_count")
    if uc and abs(uc["value"] - s["unit_count"]) > c.t.unit_count_tolerance:
        diffs.append(f"OM {uc['value']} units vs rent roll {s['unit_count']}")
        sources.append(om_source(uc, label="OM unit count", unit="count"))
    mix = c.f("unit_mix")
    if mix:
        for k, v in mix["value"].items():
            if k == "other" or v is None:
                continue
            got = s["by_type"].get(k, {}).get("units", 0)
            if v != got:
                diffs.append(f"{k}: OM {v} vs roll {got}")
        if any(d.split(":")[0] in mix["value"] for d in diffs):
            sources.append(om_source(mix, label="OM unit mix", unit="count"))
    if not diffs:
        return None
    sources.append(rr_source(c.rr, {k: v["units"] for k, v in s["by_type"].items()}, "rent roll unit count by type", "count"))
    return record(
        "unit_mix_mismatch", "medium", "OM unit count or mix differs from the rent roll: " + "; ".join(diffs),
        sources, "rent_roll",
        "The rent roll lists the units that exist and are leased; an OM mix that differs is often a developer "
        "brochure figure or includes merged / combined units.",
        None, "Ask for the as-built unit schedule (DLD / affection plan) and reconcile unit numbers.")


def expired_lease_counted_occupied(c: Context) -> dict | None:
    if not c.rr:
        return None
    s = c.rr["summary"]
    expired, no_ejari = s["expired_leases_shown_occupied"], s["let_units_missing_ejari"]
    if not expired and not no_ejari:
        return None
    by_unit = {u["unit"]: u for u in c.rr["units"]}
    at_risk = sum(by_unit[u]["annual_rent_aed"] or 0 for u in set(expired) | set(no_ejari) if u in by_unit)
    parts = []
    if expired:
        parts.append(f"{len(expired)} unit(s) marked occupied with leases that ended before {s['as_of']} ({', '.join(expired[:8])})")
    if no_ejari:
        parts.append(f"{len(no_ejari)} let unit(s) with no Ejari number ({', '.join(no_ejari[:8])})")
    sources = [{"doc": c.rr["doc"], "cell": by_unit[u]["source"]["range"], "page": by_unit[u]["source"].get("page"),
                "value": by_unit[u]["lease_end"], "unit": "date", "label": f"unit {u}: lease end {by_unit[u]['lease_end']}, status occupied"}
               for u in expired[:10] if u in by_unit]
    sources += [{"doc": c.rr["doc"], "cell": by_unit[u]["source"]["range"], "page": by_unit[u]["source"].get("page"),
                 "value": None, "unit": "text", "label": f"unit {u}: no Ejari number"} for u in no_ejari[:10] if u in by_unit]
    share = at_risk / s["in_place_rent_aed"] if s["in_place_rent_aed"] else 0
    return record(
        "expired_lease_counted_occupied", "high" if share > 0.05 else "medium", "; ".join(parts),
        sources, "rent_roll_rows",
        "A tenant holding over on an expired or unregistered lease has a weaker legal position for the landlord "
        "(an unregistered contract lacks legal standing). The engine rolls expired leases at the start of the "
        f"analysis; {_aed(at_risk)} of in-place rent ({_pct(share)}) sits on these units.",
        {"metric": "annual_rent_at_risk", "delta_aed": round(-at_risk, 0), "basis": "in-place rent on the affected units"},
        "Request Ejari certificates and renewal status for each listed unit.")


def collections_gap(c: Context) -> dict | None:
    if not c.opex or not c.rr:
        return None
    collected = c.opex["totals_by_category"].get("rental_income")
    in_place = c.rr["summary"]["in_place_rent_aed"]
    if not collected or not in_place:
        return None
    gap = 1 - collected / in_place
    if gap <= c.t.collections_gap:
        return None
    lines = [ln for ln in c.opex["lines"] if ln["category"] == "rental_income" and ln["status"] == "verified"]
    return record(
        "collections_gap", "high" if gap > 0.10 else "medium",
        f"Statement rental income {_aed(collected)} is {_pct(gap)} below rent-roll in-place rent {_aed(in_place)}",
        [{"doc": c.opex["doc"], **{k: v for k, v in ln["source"].items() if k != "doc"}, "value": ln["amount_aed"], "unit": "aed",
          "label": ln["label"]} for ln in lines]
        + [rr_source(c.rr, in_place, "rent-roll in-place rent (annual)", "aed")],
        "rent_roll",
        "Physical occupancy is not economic occupancy: units on the roll are not paying in full (arrears, "
        "concessions, bounced cheques or tenants not paying). The engine applies the mandate collection loss, "
        f"which is far smaller than this gap ({c.opex['period'].get('annualisation', {}).get('note', '')}).",
        {"metric": "annual_rent", "delta_aed": round(collected - in_place, 0),
         "basis": "statement rental income minus rent-roll in-place rent"},
        "Request the aged receivables report and bank statements for the statement period.")


def annualised_partial_period(c: Context) -> dict | None:
    if not c.opex:
        return None
    p = c.opex["period"]
    months = p.get("months_used")
    if not months or months >= c.t.full_period_months or not (p.get("presented_as_annual") or p.get("annualised")):
        return None
    ev = [e for e in p.get("evidence", []) if e["status"] in TRUSTED]
    return record(
        "annualised_partial_period", "medium",
        f"Operating statement covers {months} months but is presented as a full year",
        [{"doc": e["doc"], "page": e.get("page"), "cell": e.get("cell"), "bbox": e.get("bbox", []), "quote": e["quote"],
          "value": months, "unit": "count", "label": "period evidence"} for e in ev] or [{"doc": c.opex["doc"], "value": months, "unit": "count",
                                                                          "label": "months of data"}],
        "operating_statement",
        "Annualising part of a year misstates seasonal and one-off costs (insurance renewals, annual maintenance "
        f"contracts) and hides recent changes. {p['annualisation']['note']}.",
        None, "Request a full year of monthly statements, with the general ledger for one-off items.")


def master_lease(c: Context) -> dict | None:
    """Rule half of item 14: a master lease exists. The model review judges the related party."""
    ml = (c.rr or {}).get("master_lease")
    ls = c.f("lease_structure")
    om_ml = ls and (ls["value"] or {}).get("type") == "master_lease"
    if not ml and not om_ml:
        return None
    sources = []
    if om_ml:
        sources.append(om_source(ls, label="OM lease structure", unit="text"))
    if ml:
        sources.append({"doc": c.rr["doc"], "cell": ml["source"]["range"], "value": ml.get("annual_rent_aed"), "unit": "aed",
                        "label": f"master lease: {ml.get('tenant')}, ends {ml.get('lease_end')}"})
    sub = c.rr["summary"]["in_place_rent_aed"] if c.rr else None
    premium = (ml["annual_rent_aed"] / sub - 1) if ml and ml.get("annual_rent_aed") and sub else None
    return record(
        "master_lease_related_party", "high",
        "Income depends on a master lease" + (f" at {_pct(premium)} over the sub-tenants' rent" if premium else ""),
        sources, "rent_roll_sub_leases",
        "The building's income is one tenant's covenant. If the master tenant pays more than it collects from "
        "sub-tenants, the rent is supported by the seller's side, not the market; at expiry income falls to what "
        "the units earn.",
        {"metric": "annual_rent", "delta_aed": round(sub - ml["annual_rent_aed"], 0),
         "basis": "sub-tenancy rent minus master-lease rent"} if premium is not None else None,
        "Obtain the master lease, the master tenant's accounts and ownership; confirm whether it is related to the seller.")


def expiry_concentration(c: Context) -> dict | None:
    if not c.uw:
        return None
    share = c.m("max_expiry_share_quarter")
    soft = c.mandate["buy_box"]["soft"]
    limit = c.t.expiry_share_limit or soft.get("max_lease_expiry_share_in_any_quarter")
    if share is None or limit is None or share <= limit:
        return None
    windows = c.uw["expiry_windows"]["windows"]
    top = max(windows, key=lambda w: w["share"] or 0)
    span = f"{top['start']} to {top['end']}"
    return record(
        "expiry_concentration", "high" if share > 1.5 * limit else "medium",
        f"{_pct(share)} of in-place rent expires between {span}",
        [rr_source(c.rr, top["expiring_rent_aed"], f"leases ending {span} (rent roll lease end dates)", "aed")],
        "rent_roll",
        f"A cluster of expiries means one leasing season sets most of the income, in a falling market. The mandate "
        f"limit is {_pct(limit)} in any 3-month window of the 12 months from {c.uw['expiry_windows']['basis_date']}.",
        {"metric": "rent_expiring_in_window", "delta_aed": round(-top["expiring_rent_aed"], 0),
         "basis": f"in-place rent expiring {span}"},
        "Ask for the renewal status and notices on the expiring leases; consider a price holdback or rent guarantee.")


def title_check(c: Context) -> dict | None:
    """Rule half of item 16: the OM does not state freehold tenure, or states a non-freehold plot.

    Ownership (strata vs single title) is not this item: a verified strata title fails the mandate's
    title test directly. Never decides title."""
    f = c.f("title_type")
    raw = c.om.get("title_type") or {}
    value = (f or {}).get("value") or {}
    if f and value.get("tenure") == "freehold":
        return None
    if f:
        what = f"the OM states tenure {value.get('tenure')}, ownership {value.get('ownership')}"
        sources = [om_source(f, label="OM title", unit="text")]
    elif raw.get("status") == "unverified":
        what = f"the OM's title statement could not be verified ({raw.get('reason')})"
        sources = [{"doc": (raw.get("source") or {}).get("doc"), "page": (raw.get("source") or {}).get("page"),
                    "quote": raw.get("quote"), "value": raw.get("value"), "unit": "text",
                    "label": "OM title (unverified)"}]
    else:
        what = "the OM does not state tenure or title"
        sources = [{"doc": "om", "value": None, "unit": "text", "label": "no title statement found"}]
    non_freehold = value.get("tenure") == "non_freehold"
    return record(
        "title_check", "high",
        "OM indicates a non-freehold plot" if non_freehold else "Title not stated; legal check required before any further work",
        sources, "none",
        f"The mandate requires freehold single title; {what}. The screen does not decide title; until legal "
        "confirms it, nothing else about the deal matters.",
        None, "Obtain the title deed(s) and DLD ownership records; legal to confirm freehold status and any "
              "nationality restriction before any further work.")


RULES: list[Callable[[Context], dict | None]] = [
    occupancy_mismatch, potential_rent_as_income, gross_yield_as_net, yield_excludes_acquisition_costs,
    over_rented_vs_market, upside_exceeds_rera_cap, missing_opex_items, area_basis_confusion,
    rent_roll_does_not_foot, unit_mix_mismatch, expired_lease_counted_occupied, collections_gap,
    annualised_partial_period, master_lease, expiry_concentration, title_check,
]


def run_rules(ctx: Context) -> tuple[list[dict], list[dict]]:
    """Every rule; a rule that raises is recorded as an error, not a silent pass."""
    out, errors = [], []
    for rule in RULES:
        try:
            r = rule(ctx)
        except Exception as exc:  # noqa: BLE001 - a broken rule must not stop the screen, and is reported
            errors.append({"rule": rule.__name__, "error": f"{exc.__class__.__name__}: {exc}"})
            continue
        if r:
            out.append(r)
    return out, errors


# ---------------------------------------------------------------------------- model review


def review_context(ctx: Context, rule_findings: list[dict], docs: list[Document]) -> str:
    """What the reviewer sees besides the OM: rule findings, rent-roll facts, statement lines, master lease grid."""
    parts = ["Rule-based findings already recorded (do not repeat these unless you add new evidence):"]
    parts += [f"- {d['id']}: {d['title']}" for d in rule_findings] or ["- none"]
    if ctx.rr:
        s = ctx.rr["summary"]
        parts.append("\nRent roll facts (computed by code): " + json.dumps(
            {k: s[k] for k in ("as_of", "unit_count", "let_units", "occupancy_by_units", "in_place_rent_aed",
                               "potential_rent_aed", "status_counts")}))
        doc = next((d for d in docs if d.doc_id == ctx.rr["doc"]), None)
        ml = ctx.rr.get("master_lease")
        if ml and doc:
            for name in sorted({c.split("!")[0] for c in ml["source"]["cells"].values()}):
                if doc.sheet(name):
                    parts.append(f"\nMaster-lease sheet of `{doc.doc_id}` (cite cells as Sheet!A1):\n"
                                 + sheet_as_text(doc.sheet(name)))
        tenants = sorted({u["tenant"] for u in ctx.rr["units"] if u.get("tenant")})
        parts.append(f"\nRent-roll tenant names ({len(tenants)}): " + "; ".join(tenants[:60]))
    if ctx.opex:
        parts.append(f"\nOperating statement `{ctx.opex['doc']}` lines: "
                     + "; ".join(f"{ln['label']} -> {ln['category']}" for ln in ctx.opex["lines"]))
        if ctx.opex.get("notes"):
            parts.append("Statement notes: " + ctx.opex["notes"])
    return "\n".join(parts)


def review(client: ModelClient, model: str, om_doc: Document, docs: list[Document], ctx: Context,
           rule_findings: list[dict], market_areas: list[str]) -> tuple[list[dict], list[dict], str, ToolResult]:
    """Model pass over the OM (cached) for the (model) catalogue items and OM claims.

    Returns (accepted findings, rejected findings, lease-structure conclusion, raw result).
    """
    instruction = load_prompt("review", context=review_context(ctx, rule_findings, docs))
    result = client.call_tool(stage="review", model=model, system=load_prompt("om_system"),
                              content=om_content(om_doc) + [{"type": "text", "text": instruction}],
                              tools=om_tools(market_areas), tool_name="record_review_findings")
    accepted, rejected = [], []
    for f in result.data.get("findings", []):
        ev = verify_evidence(f.get("evidence"), docs)
        good = [e for e in ev if e["status"] in TRUSTED]
        contradiction = contradicted_by_code(f, ctx)
        if not good or contradiction:
            rejected.append({**f, "evidence": ev, "rejected_because": contradiction or
                             "no quote could be verified on its page or cell"})
            continue
        accepted.append(record(
            f["id"], f["severity"], f["title"],
            [{"doc": e["doc"], "page": e.get("page"), "cell": e.get("cell"), "bbox": e.get("bbox", []),
              "quote": e["quote"], "value": None, "unit": "text", "label": "verified quote"} for e in good],
            "documents", f["why"], None, f["analyst_action"], detected_by="model")
            | {"related_party": f.get("related_party"),
               "unverified_evidence": [e for e in ev if e["status"] not in TRUSTED]})
    return accepted, rejected, result.data.get("lease_structure_conclusion", "unclear"), result


def contradicted_by_code(finding: dict, ctx: Context) -> str | None:
    """A model finding that code-computed facts refute is rejected (the rules own these quantities)."""
    if finding.get("id") == "potential_rent_as_income" and ctx.rr:
        f = ctx.f("annual_rent_stated")
        in_place = ctx.rr["summary"]["in_place_rent_aed"]
        if f and in_place and abs(f["value"] / in_place - 1) <= ctx.t.in_place_excess:
            return (f"contradicted by the rent roll: OM income {_aed(f['value'])} equals in-place rent "
                    f"{_aed(in_place)} within {ctx.t.in_place_excess:.0%}")
    if finding.get("id") == "title_check":
        title = ctx.f("title_type")
        if title and (title["value"] or {}).get("tenure") == "freehold":
            quotes = " ".join(e.get("quote") or "" for e in finding.get("evidence") or [])
            if not contains_any(quotes, TITLE_DOUBT_KEYWORDS):
                return ("the OM states freehold tenure (verified) and no quoted evidence names a tenure or "
                        "eligibility restriction; strata ownership is tested by the mandate's title filter")
    return None


def merge(rule_findings: list[dict], model_findings: list[dict]) -> list[dict]:
    """One record per catalogue id; a model finding with the same id adds its quotes to the rule's record."""
    by_id: dict[str, dict] = {}
    out: list[dict] = []
    for d in rule_findings:
        by_id[d["id"]] = d
        out.append(d)
    for m in model_findings:
        if m["id"] in by_id and m["id"] != "other_om_claim":
            r = by_id[m["id"]]
            r["sources"] += m["sources"]
            r["detected_by"] = "rule+model"
            r["why"] += " Review: " + m["why"]
            if m.get("related_party") is not None:
                r["related_party"] = m["related_party"]
            if SEVERITY_ORDER[m["severity"]] < SEVERITY_ORDER[r["severity"]]:
                r["severity"] = m["severity"]
        else:
            out.append(m)
    return sorted(out, key=lambda d: SEVERITY_ORDER.get(d["severity"], 3))


def related_party_flag(discrepancies: list[dict], conclusion: str, om: dict) -> tuple[bool | None, str | None]:
    """(master_lease_related_party, lease_structure) for mandate_fit, from verified evidence only."""
    ml = next((d for d in discrepancies if d["id"] == "master_lease_related_party"), None)
    if ml and ml.get("related_party") is True and ml["detected_by"] in ("model", "rule+model"):
        return True, "master_lease"
    ls = trusted(om, "lease_structure")
    if ml:
        return (False if conclusion == "master_lease_third_party" else None), "master_lease"
    if ls and (ls["value"] or {}).get("type") == "direct_leases":
        return False, "direct_leases"
    if conclusion == "direct_leases":
        return False, "direct_leases"
    return None, None

