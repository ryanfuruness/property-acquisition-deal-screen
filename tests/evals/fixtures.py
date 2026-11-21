"""Synthetic run.json fixtures built from truth, in the pipeline's run.json shape.

``perfect_run(truth)`` is what a flawless pipeline would write: every OM field right and
verified on the truth page, every unit row, the statement totals, exactly the planted
discrepancies, the engine run on the true inputs, the right verdict and a fully anchored memo.
Tests then break specific things and check the scorer counts exactly those.
"""

from __future__ import annotations

import copy
import re

import engine

from evals.docs import rent_roll_path, value_in_unit_row

LET = {"occupied", "under_renewal", "notice_served", "legal_case"}


def _om_field(tf: dict | None, value, **extra) -> dict:
    if tf is None or value is None:
        return {"value": None, "status": "not_stated", "source": None, "quote": None, "reason": "not stated"}
    return {"value": value, "unit": None, "quote": tf.get("quote"), "status": "verified", "reason": None,
            "source": {"doc": "om.pdf", "page": tf.get("page"), "bbox": [], "match": "exact"}, **extra}


def _om(truth: dict) -> dict:
    t = truth["om_fields"]
    v = lambda k: (t.get(k) or {}).get("value")  # noqa: E731
    tt = v("title_type") or {}
    tenure = tt.get("tenure", "unstated")
    tenure = "unstated" if str(tenure).startswith("unstated") else tenure
    ls = v("lease_structure") or {}
    pp = v("price_psf")
    out = {
        "building_name": _om_field(t.get("building_name"), v("building_name")),
        "asset_type": _om_field(t.get("asset_type"), {"mixed_use_ground_floor_retail": "mixed_use_residential_retail"}
                                .get(v("asset_type"), v("asset_type"))),
        "area": _om_field(t.get("area"), (t.get("area") or {}).get("quote")),
        "market_area": _om_field(t.get("area"), v("area")),
        "plot_number": _om_field(t.get("plot_number"), v("plot_number")),
        "title_type": _om_field(t.get("title_type"), {"tenure": tenure, "ownership": tt.get("title", "unstated")}),
        "completion_year": _om_field(t.get("completion_year"), v("completion_year")),
        "floors": _om_field(t.get("floors"), v("floors")),
        "unit_count": _om_field(t.get("unit_count"), v("unit_count")),
        "unit_mix": _om_field(t.get("unit_mix"), v("unit_mix")),
        "bua_sqft": _om_field(t.get("bua_sqft"), float(v("bua_sqft"))),
        "nsa_sqft": _om_field(t.get("nsa_sqft"), float(v("nsa_sqft"))),
        "parking_spaces": _om_field(t.get("parking_spaces"), v("parking_spaces")),
        "occupancy_stated": _om_field(t.get("occupancy_stated"), v("occupancy_stated")),
        "annual_rent_stated": _om_field(t.get("annual_rent_stated"), v("annual_rent_stated"),
                                        basis=(t.get("annual_rent_stated") or {}).get("basis")),
        "net_income_stated_aed": _om_field(None, None),
        "opex_stated_aed": _om_field(t.get("opex_stated_aed"), v("opex_stated_aed")),
        "yield_stated": _om_field(t.get("yield_stated"), v("yield_stated"),
                                  basis=(t.get("yield_stated") or {}).get("basis")),
        "asking_price_aed": _om_field(t.get("asking_price_aed"), float(v("asking_price_aed"))),
        "price_psf_stated": (_om_field(t.get("price_psf"), pp["value"],
                                       basis=pp["basis"] if pp.get("basis_labelled") else "unstated")
                             if pp else _om_field(None, None)),
        "chiller_arrangement": _om_field(t.get("chiller_arrangement"), v("chiller_arrangement")),
        "lease_structure": _om_field(t.get("lease_structure"),
                                     {"type": ls.get("value"), "master_tenant": ls.get("master_tenant")}),
        "upside_claims": [{"quote": q, "status": "verified", "claimed_uplift": None,
                           "source": {"doc": "om.pdf", "page": (t.get("upside_claims") or {}).get("page")}}
                          for q in (v("upside_claims") or [])],
    }
    return out


def _row(source: str):
    m = re.match(r"^(?P<sheet>.+?)!A(?P<row>\d+)", str(source or ""))
    if m:
        return m.group("sheet"), int(m.group("row"))
    m = re.match(r"^line (\d+)", str(source or ""))
    return (None, int(m.group(1))) if m else (None, None)


def _rent_roll(truth: dict) -> dict:
    rr = truth["rent_roll"]
    doc = rent_roll_path(truth)
    units, hidden = [], 0.0
    for u in rr["units"]:
        sheet, row = _row(u.get("source"))
        asking = u.get("asking_rent_aed")
        if asking and u["status"] not in LET and not (doc and value_in_unit_row(doc, u["unit"], asking)):
            hidden += asking
            asking = None
        units.append({**{k: u.get(k) for k in ("unit", "unit_type", "area_sqft", "tenant", "ejari_no", "lease_start",
                                                "lease_end", "annual_rent_aed", "status")},
                      "asking_rent_aed": asking, "source": {"doc": rr["document"], "sheet": sheet, "row": row}})
    tc = rr["totals_computed"]
    summary = {
        "as_of": truth["true_building"]["engine_inputs"].get("rent_roll_date"),
        "unit_count": tc["unit_count"], "let_units": tc["occupied_units"], "vacant_units": tc["vacant_units"],
        "occupancy_by_units": tc["occupancy_units"], "occupancy_by_area": tc["occupancy_area"],
        "in_place_rent_aed": float(tc["in_place_rent_aed"]),
        "vacant_asking_rent_aed": float(tc["vacant_asking_rent_aed"] - hidden),
        "potential_rent_aed": float(tc["potential_rent_aed"] - hidden),
        "expired_leases_shown_occupied": list(tc.get("expired_but_occupied_units") or []),
        "let_units_missing_ejari": list(tc.get("missing_ejari_units") or []),
    }
    return {"doc": rr["document"], "units": units, "summary": summary, "stated_totals": [], "skipped_rows": []}


def _opex(truth: dict) -> dict:
    op = truth["opex"]
    totals = {k: float(v) for k, v in op["opex_by_category_aed"].items()}
    totals["rental_income"] = float(op["rental_income_aed"])
    if op.get("other_income_aed"):
        totals["other_income"] = float(op["other_income_aed"])
    p = op["period"]
    return {"doc": op["document"], "totals_by_category": totals, "total_expenses_aed": float(op["total_opex_aed"]),
            "amount_basis": "annualised_total" if p.get("annualised") else "period_total",
            "period": {"start": p["start"], "end": p["end"], "months_covered": p["months_covered"],
                       "months_used": p["months_covered"], "annualised": p["annualised"],
                       "presented_as_annual": True}, "lines": [], "unverified_lines": []}


def perfect_run(truth: dict) -> dict:
    mandate, market = engine.load_mandate(), engine.load_market()
    ei = copy.deepcopy(truth["true_building"]["engine_inputs"])
    uw = engine.underwrite(ei, mandate, market)
    fit = engine.mandate_fit(truth["true_building"]["deal_facts"], uw, mandate)
    wa = uw["metrics"]["walk_away_price_aed"]["value"]
    occ = truth["rent_roll"]["totals_computed"]["occupancy_units"]
    facts = {"uw.walk_away_price_aed": {"value": wa, "unit": "AED", "label": "walk-away price"},
             "rr.occupancy_by_units": {"value": occ, "unit": "ratio", "label": "occupancy"},
             "deal.unit_count": {"value": truth["rent_roll"]["totals_computed"]["unit_count"], "unit": "units",
                                 "label": "units"}}
    md = (f"**{fit['verdict']}.** Walk-away price AED {wa / 1e6:.2f}m [[uw.walk_away_price_aed]]. "
          f"Occupancy is {occ * 100:.1f}% [[rr.occupancy_by_units]] across "
          f"{truth['rent_roll']['totals_computed']['unit_count']} [[deal.unit_count]] units.")
    return {
        "deal": {"deal_id": truth["deal_id"], "documents_used": {"om": "om.pdf"}},
        "extracted": {"om": _om(truth)},
        "rent_roll_summary": _rent_roll(truth),
        "opex": _opex(truth),
        "discrepancies": [{"id": d["id"], "severity": "high", "title": f"planted {d['id']}", "detected_by": "rule"}
                          for d in truth["planted_discrepancies"]],
        "rejected_model_findings": [],
        "underwriting": {"status": "ok", "error": None, "deal_inputs": ei, "outputs": uw},
        "mandate_fit": fit,
        "fact_sheet": facts,
        "memo": {"status": "passed", "markdown": md, "attempts": [{"attempt": 1, "errors": []}]},
        "notes": [], "errors": [],
        "meta": {"pipeline_version": "test", "engine_version": uw.get("engine_version"), "model": "fixture",
                 "cost_usd": 0.5, "duration_s": 100.0, "tokens": {}, "calls": []},
    }
