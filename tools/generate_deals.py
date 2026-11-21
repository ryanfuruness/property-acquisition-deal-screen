#!/usr/bin/env python3
"""Generate the synthetic Dubai residential-building deal set.

    python tools/generate_deals.py                 # all deals into data/deals/
    python tools/generate_deals.py --only d05-larkspur-barsha
    python tools/generate_deals.py --out /tmp/deals --no-check

Deterministic: every deal is driven by its own seed (tools/dealgen/specs.py); PDFs are written with
reportlab's invariant mode and xlsx files with fixed timestamps, so re-running gives identical files.

For each deal it builds a true building, renders the broker package (OM, rent roll, operating
statement) with the planted discrepancies, then checks with reference implementations of the
catalogue rules that exactly the planted discrepancies fire, with margin. It writes
data/deals/<deal_id>/package/* and truth.json, and data/deals/index.json.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf  # noqa: E402

from dealgen import analysis  # noqa: E402
from dealgen.building import ITEM_CATEGORY, build_true_building, load_refs, round_rent  # noqa: E402
from dealgen.package import om_facts, statement_doc  # noqa: E402
from dealgen.render_om import build_om  # noqa: E402
from dealgen.render_rentroll import (write_master_xlsx, write_rentroll_csv, write_rentroll_pdf,  # noqa: E402
                                     write_rentroll_pdf_spanning, write_rentroll_xlsx, write_split_xlsx)
from dealgen.render_stmt import write_stmt_pdf, write_stmt_xlsx  # noqa: E402
from dealgen.scan import scan_pdf  # noqa: E402
from dealgen.specs import CATALOGUE, DEALS, HELDOUT  # noqa: E402

GENERATOR_VERSION = "2.0.0"
REPO = Path(__file__).resolve().parents[1]
OM_FIELDS = ["building_name", "asset_type", "area", "plot_number", "title_type", "completion_year", "floors", "unit_count",
             "unit_mix", "bua_sqft", "nsa_sqft", "parking_spaces", "occupancy_stated", "annual_rent_stated", "yield_stated",
             "asking_price_aed", "chiller_arrangement", "opex_stated_aed", "lease_structure", "upside_claims"]


def iso(o):
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o))


def norm(s):
    return re.sub(r"\s+", " ", s.replace("•", " ")).strip().lower()


# --------------------------------------------------------------------------- rules (reference implementation)
def _add_months(d, n):
    import calendar
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def quarter_shares(rows, roll_date):
    """Share of in-place rent by lease end in four consecutive 3-month windows from the rent-roll date
    (same definition as the engine): an already-expired lease counts in the first window, a lease ending
    12 months or more out counts in none."""
    occ = [r for r in rows if r["status"] in analysis.OCC_LIKE and r["annual_rent_aed"]]
    tot = sum(r["annual_rent_aed"] for r in occ)
    edges = [_add_months(roll_date, 3 * k) for k in range(5)]
    out = {}
    for k in range(4):
        lo, hi = edges[k], edges[k + 1]
        rent = 0
        for r in occ:
            e = date.fromisoformat(r["lease_end"]) if r["lease_end"] else date.min
            if (k == 0 and e < hi) or (k > 0 and lo <= e < hi):
                rent += r["annual_rent_aed"]
        out[f"{lo.isoformat()} to {(hi - timedelta(days=1)).isoformat()}"] = round(rent / tot, 4)
    return out


def check_rules(ctx, mandate, market):
    """Returns {id: {"fired": bool, "values": {...}, "margin_ok": bool}} for ids 1..16."""
    b, om, spec, rr, rrm, stmt = ctx["b"], ctx["om"], ctx["spec"], ctx["rr_rows"], ctx["rrm"], ctx["stmt_truth"]
    soft = mandate["buy_box"]["soft"]
    out = {}
    master = b["master_lease"]

    def put(i, fired, margin_ok, **values):
        out[i] = {"fired": bool(fired), "margin_ok": bool(margin_ok), "values": values}

    d = abs(om["occupancy"]["value"] - rrm["occupancy_units"])
    put(1, d > 0.02, d > 0.04 or d < 0.012, om=om["occupancy"]["value"], rent_roll=rrm["occupancy_units"], gap_points=round(d * 100, 2))
    ref = master["annual_rent_aed"] if master else rrm["in_place_rent_aed"]
    x = om["annual_rent"]["value"] / ref - 1
    put(2, x > 0.01, x > 0.03 or x < 0.006, om=om["annual_rent"]["value"], rent_roll_in_place=rrm["in_place_rent_aed"],
        rent_roll_potential=rrm["potential_rent_aed"], master_lease_rent=master["annual_rent_aed"] if master else None)
    y = om["yield"]
    if y["basis"] == "net":
        deducted = om["opex_stated_aed"] or 0
        share = deducted / stmt["total_opex_aed"]
        put(3, share < 0.5, share < 0.35 or share > 0.8, om_yield=y["value"], om_deduction_aed=deducted,
            statement_opex_aed=stmt["total_opex_aed"], share_of_costs_deducted=round(share, 3))
    else:
        put(3, False, True, om_yield=y["value"], basis=y["basis"])
    put(4, y["on"] == "asking_price", True, om_yield=y["value"], om_label=y["label"], on=y["on"])
    am = market["areas"][b["ref_area"]]
    f = market["unit_type_factors"]
    occ = [r for r in rr if r["status"] in analysis.OCC_LIKE and r["annual_rent_aed"]]
    tot = sum(r["annual_rent_aed"] for r in occ)
    thr = soft.get("over_rent_threshold", 0.0)
    over = [r for r in occ if r["annual_rent_aed"] > (1 + thr) * am["market_rent_aed_psf_1br"] * f[r["unit_type"]] * r["area_sqft"]]
    sh = sum(r["annual_rent_aed"] for r in over) / tot
    put(5, sh > soft["max_over_rent_share_of_income"], sh > 0.27 or sh < 0.15, over_rent_share_of_income=round(sh, 4),
        units_over_reference_by_more_than_threshold=len(over), unit_threshold=thr, threshold=soft["max_over_rent_share_of_income"])
    up = om["_upside"]
    if up and up["kind"] == "exceeds_rera":
        gap = up["claimed_uplift_pct"] - up["supportable_pct"]
        put(6, gap > 0.05, gap > 0.08, claimed_uplift_aed=up["claimed_uplift_aed"], claimed_uplift_pct=up["claimed_uplift_pct"],
            supportable_at_screen_reference_aed=up["supportable_at_screen_reference_aed"],
            supportable_pct=up["supportable_pct"],
            rera_renewal_allowed_aed=up["rera_allowed"]["allowed_uplift_aed"],
            rera_renewal_allowed_pct=up["rera_allowed"]["allowed_uplift_pct_of_in_place"],
            units_by_gap=up["rera_allowed"]["units_by_gap_to_index"],
            note="Supportable = every occupied unit re-let at the screen reference with no RERA cap (re-lets on turnover are uncapped); "
                 "RERA renewal allowed = Decree 43 bands at renewal (top band 20%).")
    else:
        put(6, False, True, claim=(up or {}).get("kind"))
    req = ["property_management", "insurance", "sinking_fund"] + (["district_cooling"] if b["chiller_landlord_pays"] else [])
    missing = [c for c in req if c not in stmt["opex_by_category_aed"]]
    put(7, bool(missing), True, missing_categories=missing, chiller_landlord_pays=b["chiller_landlord_pays"])
    pp = om.get("price_psf")
    mislab = ctx["rr_meta"].get("area_unit_label") and ctx["rr_meta"]["area_unit_label"] != ctx["rr_meta"]["area_unit"]
    put(8, bool(pp and pp["basis"] == "bua" and not pp["basis_labelled"]) or bool(mislab), True,
        rent_roll_area_header=ctx["rr_meta"].get("area_unit_label", ctx["rr_meta"]["area_unit"]),
        rent_roll_area_actual_unit=ctx["rr_meta"]["area_unit"],
        om_price_psf=pp["value"] if pp else None, basis=pp["basis"] if pp else None,
        price_psf_nsa=round(om["asking_price_aed"] / b["nsa_sqft"]), price_psf_bua=round(om["asking_price_aed"] / b["bua_sqft"]))
    tots = [s for s in ctx["rr_meta"]["summary_rows"] if s["kind"] == "total"]
    gaps = [s["rent_aed"] - s["scope_sum_aed"] for s in tots]
    gap = max(gaps, key=abs) if gaps else 0
    scope = max((s["scope_sum_aed"] for s in tots), default=1)
    put(9, abs(gap) > 0.005 * scope, abs(gap) > 0.02 * scope or gap == 0,
        stated_totals=[{"label": s["label"], "stated_aed": s["rent_aed"], "sum_of_rows_aed": s["scope_sum_aed"],
                        **({"sheet": s["sheet"]} if s.get("sheet") else {})} for s in tots], difference_aed=gap)
    rr_mix = {}
    for r in rr:
        rr_mix[r["unit_type"]] = rr_mix.get(r["unit_type"], 0) + 1
    put(10, om["unit_count"] != len(rr) or om["unit_mix"] != rr_mix, True, om_unit_count=om["unit_count"], om_mix=om["unit_mix"],
        rent_roll_unit_count=len(rr), rent_roll_mix=rr_mix)
    put(11, bool(rrm["expired_but_occupied_units"] or rrm["missing_ejari_units"]), True,
        expired_but_occupied=rrm["expired_but_occupied_units"], missing_ejari=rrm["missing_ejari_units"])
    st_rent = stmt["rental_income_aed"]
    ratio = st_rent / ref
    put(12, ratio < 0.90, ratio < 0.87 or ratio > 0.94, statement_rental_income_aed=st_rent, rent_roll_in_place_aed=ref,
        ratio=round(ratio, 4))
    put(13, stmt["period"]["months_covered"] < 12, True, months_covered=stmt["period"]["months_covered"],
        presented_as=stmt["period"]["presented_as"])
    put(14, bool(master), True, master_tenant=master["tenant"] if master else None, related_party=master["related_party"] if master else None)
    qs = quarter_shares(rr, b["rent_roll_date"])
    mq = max(qs.values())
    lim = soft.get("max_lease_expiry_share_in_any_quarter", 0.40)
    put(15, mq > lim, mq > lim + 0.08 or mq < lim - 0.04, max_share_any_3m_window_from_roll_date=mq, by_quarter=qs, threshold=lim)
    put(16, b["tenure"] != "freehold", True, true_tenure=b["tenure"], nationality_restriction=b["nationality_restriction"],
        om_title_text=ctx["om_fields"]["title_type"]["quote"])
    return out


HOW = {
    1: "OM headline occupancy taken from an earlier date or rounded up from marketing copy; rent roll is unit-level and dated.",
    2: "OM 'annual rental income' includes vacant units at the landlord's asking rent (rent-roll potential), presented as income.",
    3: "OM 'net yield' deducts only community/service charges, not the FM, utilities, cooling, insurance and management costs the owner pays.",
    4: "OM yield (ROI) is rent divided by asking price, before DLD 4%, agency 2% + VAT and registration fees.",
    5: "Many tenancies were signed at 2025 peak rents; after the 2026 fall a large share of income sits above the area reference rent.",
    6: "OM claims a double-digit income uplift within 12 months by comparing passing rents with asking rents for new lettings; passing rents already sit near the screen reference, so renewals allow 0% under Decree 43 and even uncapped re-lets at the reference add only a few percent.",
    7: "Operating statement omits standard costs the owner bears.",
    8: "OM quotes price per sq ft without a basis; the figure is on BUA (incl. parking and common areas), which flatters the price.",
    9: "Rent-roll TOTAL row is a hard-coded figure from an earlier version and does not equal the sum of the unit rows.",
    10: "OM unit count and mix are copied from the developer brochure; the rent roll shows units merged after handover.",
    11: "Tenants holding over on expired leases and units without Ejari numbers are shown as occupied.",
    12: "Operating-statement rent collected is well below rent-roll in-place rent (bounced cheques, RDC cases, holding-over tenants not paying).",
    13: "Statement titled for the financial year covers January-September only, annualised x 12/9; annual Q4 items are missing.",
    14: "Income depends on a whole-building master lease to the seller's affiliate at a rent above what the operator collects.",
    15: "The building was leased up in one wave after handover; most rent expires within one 3-month window.",
    16: "OM never states freehold; plot is in Al Barsha 1 and the terms note purchaser eligibility. True title is nationality-restricted.",
}


# --------------------------------------------------------------------------- one deal
def generate(spec, out_root, mandate, market, check=True):
    deal_dir = out_root / spec["deal_id"]
    pkg = deal_dir / "package"
    if deal_dir.exists():
        shutil.rmtree(deal_dir)
    pkg.mkdir(parents=True)
    b, rng = build_true_building(spec, mandate, market)
    rng2 = random.Random(spec["seed"] + 999)

    # strata extras: title deed per unit and OA service charge
    if b["title"] == "strata":
        sc = (b["opex_items"]["oa_general"] + b["opex_items"]["oa_reserve"]) / b["nsa_sqft"]
        spec["_sc_rate"] = round(sc, 2)
        spec["_deed_no"] = lambda u: str(100000 + (int(u["unit"]) * 7919 + spec["seed"]) % 899999)
    stale = None
    if spec["rent_roll"].get("stale_total"):
        vac = [u for u in b["units"] if u["status"] == "vacant"]
        prev = [round_rent(u["market_rent_aed"] * rng2.uniform(0.86, 0.95)) for u in vac[:3]]
        stale = b["in_place_rent_aed"] + sum(prev)

    # ---- rent roll
    rrf = spec["rent_roll"]
    rr_path = pkg / rrf["file"]
    if rrf["fmt"] == "xlsx" and rrf["layout"] == "master_two_sheets":
        rr, meta = write_master_xlsx(rr_path, b, spec)
    elif rrf["fmt"] == "xlsx" and rrf["layout"] == "export_split":
        rr, meta = write_split_xlsx(rr_path, b, spec)
    elif rrf["fmt"] == "pdf" and rrf["layout"] == "pdf_spanning":
        rr, meta = write_rentroll_pdf_spanning(rr_path, b, spec, area_in_sqm_labelled_sqft=rrf.get("sqm_labelled_sqft", False), stale=stale)
    elif rrf["fmt"] == "xlsx":
        rr, meta = write_rentroll_xlsx(rr_path, b, spec, rrf["layout"], stale=stale)
    elif rrf["fmt"] == "csv":
        rr, meta = write_rentroll_csv(rr_path, b, spec)
    else:
        rr, meta = write_rentroll_pdf(rr_path, b, spec)
    rrm = analysis.rr_metrics(rr.rows, b["rent_roll_date"])

    # ---- operating statement
    sdoc = statement_doc(spec, b)
    st_path = pkg / spec["stmt"]["file"]
    stmt_truth = (write_stmt_xlsx if spec["stmt"]["fmt"] == "xlsx" else write_stmt_pdf)(st_path, b, spec, sdoc)

    # ---- OM
    om = om_facts(spec, b, sdoc, {"metrics": rrm}, mandate)
    om_date = date(2026, 11, 3 + spec["seed"] % 14)
    ctx = {"b": b, "spec": spec, "om": om, "stmt_truth": stmt_truth, "om_date": om_date}
    tmpdir = Path(tempfile.mkdtemp())
    text_pdf = tmpdir / "om_text.pdf"
    fields = build_om(text_pdf, ctx)
    fields.setdefault("upside_claims", {"value": [], "quote": None})
    pdoc = pymupdf.open(str(text_pdf))
    pages = [norm(p.get_text()) for p in pdoc]
    n_pages = len(pages)
    for k, fv in fields.items():
        q = fv.get("quote")
        if fv.get("in_image"):
            assert 1 <= fv["page"] <= len(pages), (k, fv["page"])
            continue
        if not q:
            fv["page"] = None
            continue
        hits = [i + 1 for i, t in enumerate(pages) if norm(q) in t]
        if not hits:
            raise AssertionError(f"{spec['deal_id']}: quote for {k} not found in OM text: {q!r}")
        fv["page"] = hits[0]
        if len(hits) > 1:
            fv["also_on_pages"] = hits[1:]
    for i, t in enumerate(pages):
        assert norm("Synthetic document for demonstration. Fictional property.") in t, f"footer missing p{i + 1}"
    pdoc.close()
    if spec.get("scanned_om"):
        scan_pdf(text_pdf, pkg / "om.pdf", spec["seed"], profile=spec.get("scan_profile", "normal"))
    else:
        shutil.copy(text_pdf, pkg / "om.pdf")
    shutil.rmtree(tmpdir)

    # ---- rule audit
    ctx.update(rr_rows=rr.rows, rrm=rrm, rr_meta=meta, om_fields=fields)
    rules = check_rules(ctx, mandate, market)
    fired = sorted(i for i, r in rules.items() if r["fired"])
    if check:
        if fired != sorted(spec["plant"]):
            raise AssertionError(f"{spec['deal_id']}: rules fired {fired} but planted {sorted(spec['plant'])}\n"
                                 + json.dumps({i: rules[i]['values'] for i in set(fired) ^ set(spec['plant'])}, default=iso, indent=1))
        weak = [i for i, r in rules.items() if not r["margin_ok"]]
        if weak:
            raise AssertionError(f"{spec['deal_id']}: rules too close to threshold {weak}: "
                                 + json.dumps({i: rules[i]['values'] for i in weak}, default=iso))

    # ---- engine inputs from TRUE facts
    cats = {}
    for key, v in b["opex_items"].items():
        c = ITEM_CATEGORY[key]
        cats[c] = cats.get(c, 0) + v
    ei_units = [{"unit": u["unit"], "unit_type": u["type"], "area_sqft": u["area_sqft"], "status": u["status"],
                 "annual_rent_aed": u["annual_rent_aed"], "lease_end": u["lease_end"].isoformat() if u["lease_end"] else None}
                for u in b["units"]]
    om_stated = {"annual_rent_aed": om["annual_rent"]["value"],
                 "net_income_aed": (om["noi_stated_aed"] if om.get("noi_stated_aed") is not None else
                                    (om["annual_rent"]["value"] - om["opex_stated_aed"] if om["yield"]["basis"] == "net" else None)),
                 "yield": om["yield"]["value"],
                 "yield_basis": {"measure": om["yield"]["basis"], "on": om["yield"]["on"]}}
    ei = {"deal_id": spec["deal_id"], "price_aed": om["asking_price_aed"], "area": b["area"], "nsa_sqft": b["nsa_sqft"],
          "bua_sqft": b["bua_sqft"], "units": ei_units, "opex_aed": cats, "opex_includes_vat": True,
          "other_income_aed": b["other_income_aed"], "chiller_landlord_pays": b["chiller_landlord_pays"], "om_stated": om_stated,
          "rent_roll_date": b["rent_roll_date"].isoformat()}
    ei["completion_year"] = b["completion_year"]
    ei["security_deposits_aed"] = sum(u["deposit_aed"] or 0 for u in b["units"] if u["status"] != "vacant")
    if 12 in spec["plant"]:
        in_place_paying = sum(u["annual_rent_aed"] for u in b["units"] if u["status"] in ("occupied", "notice_served", "under_renewal"))
        ya = stmt_truth.get("ytd_actual")
        collected = (ya["rental_income_aed"] * 12 / ya["months"]) if ya else stmt_truth["rental_income_aed"]
        ei["collection_loss_override"] = round(max(0.0, 1 - collected / in_place_paying), 4)
    if b["master_lease"]:
        ml = b["master_lease"]
        ei["master_lease"] = {"tenant": ml["tenant"], "related_party": ml["related_party"], "annual_rent_aed": ml["annual_rent_aed"],
                              "lease_end": ml["end"], "cheques": 4}
    est = None

    # ---- hard filters (static) on truth
    hard = mandate["buy_box"]["hard"]
    title_type = ("freehold_single_title" if (b["tenure"] == "freehold" and b["title"] == "single_title") else
                  f"{b['tenure']}_{b['title']}")
    asset_v = "mixed_use_ground_floor_retail" if "retail" in b["unit_mix"] else "residential_building"
    fails = []
    if title_type not in hard["title"]:
        fails.append(f"title: {title_type.replace('_', ' ')}" + (f" (ownership restricted to {b['nationality_restriction']})" if b["nationality_restriction"] else ""))
    if b["area"] not in hard["areas"]:
        fails.append("area")
    if not hard["min_units"] <= b["unit_count"] <= hard["max_units"]:
        fails.append(f"units: {b['unit_count']} outside {hard['min_units']}-{hard['max_units']}")
    if not hard["min_price_aed"] <= om["asking_price_aed"] <= hard["max_price_aed"]:
        fails.append(f"price: AED {om['asking_price_aed']:,} outside AED {hard['min_price_aed']:,}-{hard['max_price_aed']:,}")
    if b["completion_year"] < hard["min_completion_year"]:
        fails.append("completion year")
    if b["master_lease"] and b["master_lease"]["related_party"]:
        fails.append(f"master lease to related party ({b['master_lease']['tenant']})")
    hard_res = {"result": "fail" if fails else "pass", "failed_filters": fails,
                "reason": "; ".join(fails) if fails else "All static hard filters pass on true facts (asset type, title, area, units, price, completion, lease structure).",
                "note": "min_dscr_year1 is engine-computed and not included here; run tools/check_engine.py for the engine's result on truth."}
    deal_facts = {"asset_type": "mixed_use_residential" if asset_v.startswith("mixed") else "residential_building",
                  "area": b["area"], "title_type": title_type, "unit_count": b["unit_count"],
                  "price_aed": om["asking_price_aed"], "completion_year": b["completion_year"],
                  "lease_structure": b["lease_structure"],
                  "master_lease_related_party": bool(b["master_lease"] and b["master_lease"]["related_party"])}

    # ---- truth
    units_out = []
    for u in b["units"]:
        uu = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in u.items()}
        units_out.append(uu)
    om_fields = {}
    for k in OM_FIELDS:
        if k in fields:
            om_fields[k] = fields[k]
        else:
            om_fields[k] = {"value": None, "reason": "not stated in the OM"}
    om_fields["occupancy_stated"]["as_of"] = om["occupancy"]["as_of"]
    om_fields["annual_rent_stated"]["basis"] = om["annual_rent"]["basis"]
    om_fields["annual_rent_stated"]["basis_as_labelled"] = om["annual_rent"]["basis_as_labelled"]
    om_fields["yield_stated"]["label"] = om["yield"]["label"]
    om_fields["yield_stated"]["basis"] = {"measure": om["yield"]["basis"], "on": om["yield"]["on"]}
    for extra in ("price_psf", "broker", "seller", "master_tenant_group"):
        if extra in fields:
            om_fields[extra] = fields[extra]
    if spec.get("scanned_om"):
        om_fields["_note"] = "om.pdf is an image-only scan; quotes are the text visible on the page image (no text layer)."
    planted = []
    for i in sorted(spec["plant"]):
        planted.append({"num": i, "id": CATALOGUE[i], "how_planted": HOW[i], "expected": rules[i]["values"]})
    rr_out = {"document": rr_path.name, **meta, "units": rr.rows, "totals_computed": rrm,
              "totals_stated": [s for s in meta["summary_rows"] if s["kind"] in ("total", "summary", "subtotal")],
              "expiry_by_3m_window_from_roll_date": quarter_shares(rr.rows, b["rent_roll_date"])}
    if b["master_lease"]:
        from dealgen.building import opex_items
        op_spec = {k: v for k, v in spec.items() if k not in ("owner_statement_master_lease",)}
        op_spec["mgmt_fee_pct"] = 0.05
        op_costs = sum(opex_items(op_spec, dict(b, lease_structure="direct_leases"), random.Random(spec["seed"] + 3)).values())
        sub_rent = sum(u["annual_rent_aed"] for u in b["units"] if u["status"] in analysis.OCC_LIKE)
        b["master_lease"]["operator_economics"] = {
            "sub_let_in_place_rent_aed": sub_rent, "sub_let_occupancy": b["occupancy_units"],
            "operator_running_costs_aed": int(op_costs), "master_rent_aed": b["master_lease"]["annual_rent_aed"],
            "operator_annual_shortfall_aed": int(b["master_lease"]["annual_rent_aed"] + op_costs - sub_rent),
            "note": "The operator collects less than the master rent and also bears running costs, so the rent depends on "
                    "support from the Silverline Group (covenant risk). On reversion the owner gets the sub-let income less costs."}
        rr_out["master_lease"] = {**b["master_lease"], **meta.get("master_lease_sheet", {})}
        rr_out["note"] = "Sheet 1 is the master lease (the owner's income). Sheet 2 is the operator's sub-tenancy schedule, for look-through."
    true_metrics = {
        "gross_yield_in_place_on_price": round((b["master_lease"]["annual_rent_aed"] if b["master_lease"] else b["in_place_rent_aed"]) / om["asking_price_aed"], 4),
        "price_psf_nsa": round(om["asking_price_aed"] / b["nsa_sqft"]), "price_psf_bua": round(om["asking_price_aed"] / b["bua_sqft"]),
        "over_rent": analysis.over_rent(b["units"], tolerance=mandate["buy_box"]["soft"].get("over_rent_threshold", 0.0)),
        "rera_allowed_uplift_next_renewal": analysis.rera_allowed_uplift(b["units"], mandate["underwriting"]["rera"]["increase_bands"]),
        "expiry": analysis.expiry_profile(b["units"], b["rent_roll_date"]),
        "expiry_by_3m_window_from_roll_date": quarter_shares([{"status": u["status"], "annual_rent_aed": u["annual_rent_aed"],
                                                       "lease_end": u["lease_end"].isoformat() if u["lease_end"] else None}
                                                      for u in b["units"]], b["rent_roll_date"]),
        "opex_true_12m_aed": sum(b["opex_items"].values()),
        "opex_true_by_category_aed": cats,
        "opex_true_psf_nsa": round(sum(b["opex_items"].values()) / b["nsa_sqft"], 2),
        "deposits_held_aed": sum(u["deposit_aed"] or 0 for u in b["units"] if u["status"] != "vacant"),
    }
    t12 = b["t12"]
    true_stmt = {"period_start": t12["months"][0].isoformat(), "months": 12,
                 "rental_income_aed": sum(t12["rental_income"]), "other_income_aed": sum(t12["other_income"]),
                 "opex_items_aed": {k: sum(v) for k, v in t12["opex"].items()},
                 "item_categories": {k: ITEM_CATEGORY[k] for k in t12["opex"]}}
    tb = {k: v for k, v in b.items() if k not in ("units", "opex_items", "t12")}
    tb["rent_roll_date"] = b["rent_roll_date"].isoformat()
    tb.update(asset_type=asset_v, asking_price_aed=om["asking_price_aed"], units=units_out, operating_statement_true_12m=true_stmt,
              metrics=true_metrics, engine_inputs=ei, deal_facts=deal_facts)
    notes = [spec["describe"],
             "engine_inputs are built from TRUE facts (true 12-month costs, true unit areas and statuses), not from the documents.",
             "Opex amounts are as paid, inclusive of non-recoverable VAT (opex_includes_vat: true). A stated management fee is "
             "included in opex_aed.property_management for completeness; the engine applies its own fee on EGI.",
             "Occupancy counts occupied, notice-served, under-renewal and legal-case units as let.",
             "Market reference rent per unit = area 1BR psf x unit-type factor x unit area (areas.yaml), as in the engine."]
    if b["master_lease"]:
        notes.append("Master-lease deal: units are the operator's sub-tenancies (look-through, used after reversion). opex_aed holds only "
                     "the landlord's costs under the lease; operator-borne categories are absent and would be defaulted by the engine.")
    if spec["deal_id"].startswith("d05"):
        notes.append("True 12-month opex includes Q4 items (lift AMC, fire systems, facade/BMU, second insurance instalment) that the "
                     "Jan-Sep annualised statement misses.")
    if spec["deal_id"].startswith("d04"):
        notes.append("True opex includes Empower district cooling paid by the landlord (chiller-free), absent from the P&L.")
    truth = {
        "deal_id": spec["deal_id"], "set": spec.get("set", "dev"), "generator": {"version": GENERATOR_VERSION, "seed": spec["seed"], "om_date": om_date.isoformat()},
        "package": sorted(p.name for p in pkg.iterdir()),
        "true_building": tb, "om_fields": om_fields, "om_pages": n_pages, "rent_roll": rr_out, "opex": stmt_truth,
        "planted_discrepancies": planted,
        "rule_checks_not_planted": {CATALOGUE[i]: r["values"] for i, r in rules.items() if i not in spec["plant"]},
        "expected_hard_filter_result": hard_res, "expected_verdict": None,
        "expected_verdict_note": "To be computed by running the engine and mandate_fit on true_building.engine_inputs and deal_facts.",
        "notes": notes,
    }
    (deal_dir / "truth.json").write_text(json.dumps(truth, indent=1, default=iso, ensure_ascii=False))
    return {
        "deal_id": spec["deal_id"], "set": spec.get("set", "dev"), "building_name": b["name"], "area": b["area"], "sub_community": b["sub_community"],
        "units": b["unit_count"], "asking_price_aed": om["asking_price_aed"], "broker": fields["broker"]["value"],
        "planted_discrepancies": [CATALOGUE[i] for i in sorted(spec["plant"])],
        "expected_hard_filter_result": hard_res["result"], "tests": spec["describe"],
        "documents": sorted(p.name for p in pkg.iterdir()), "scanned_om": bool(spec.get("scanned_om")),
    }, est, rules


def check_unique_names(out):
    """No tenant name may appear in more than one building (dev and held-out together)."""
    where = {}
    for p in sorted(out.glob("*/truth.json")):
        t = json.loads(p.read_text())
        for u in t["true_building"]["units"]:
            if u.get("tenant"):
                where.setdefault(u["tenant"], set()).add(t["deal_id"])
    dup = {k: sorted(v) for k, v in where.items() if len(v) > 1}
    if dup:
        raise AssertionError(f"tenant names recur across buildings: {dup}")
    print(f"name check: {len(where)} distinct tenant names, none shared between buildings")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "data" / "deals"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-check", action="store_true", help="skip the planted-vs-detected rule assertion")
    args = ap.parse_args()
    mandate, market = load_refs()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in DEALS + HELDOUT:
        if args.only and spec["deal_id"] not in args.only:
            continue
        row, est, rules = generate(dict(spec), out, mandate, market, check=not args.no_check)
        rows.append(row)
        print(f"{row['deal_id']:24s} {row['units']:4d}u AED {row['asking_price_aed'] / 1e6:6.1f}M  planted={row['planted_discrepancies']}")
    if not args.only:
        check_unique_names(out)
        index = {"generated_by": "tools/generate_deals.py", "generator_version": GENERATOR_VERSION,
                 "sets": {"dev": "12 deals used to build and tune the pipeline",
                          "heldout": "8 deals with unseen brokers, layouts and phrasings; for measuring generalisation only"},
                 "note": "Synthetic documents for demonstration. All properties, brokers, people and companies are fictional.",
                 "discrepancy_catalogue": CATALOGUE, "deals": rows}
        (out / "index.json").write_text(json.dumps(index, indent=1, default=iso))


if __name__ == "__main__":
    main()
