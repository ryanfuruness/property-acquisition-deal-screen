"""Every rule-detected catalogue item: one case that fires, one that does not (thresholds from config)."""

import pytest

from helpers import (FULL_OPEX, make_context, make_om, make_opex, make_rr, rr_unit, standard_units, verified)
from pipeline.reconcile import (Context, annualised_partial_period, area_basis_confusion, collections_gap,
                                contradicted_by_code, expired_lease_counted_occupied, expiry_concentration,
                                gross_yield_as_net, master_lease, merge, missing_opex_items, occupancy_mismatch,
                                over_rented_vs_market, potential_rent_as_income, related_party_flag,
                                rent_roll_does_not_foot, run_rules, SOURCE_UNITS, title_check, unit_mix_mismatch,
                                upside_exceeds_rera_cap, yield_excludes_acquisition_costs)

REQUIRED_KEYS = {"id", "severity", "title", "sources", "relied_on", "why", "impact", "analyst_action", "detected_by"}


@pytest.fixture(scope="module")
def clean():
    return make_context()


def test_clean_deal_raises_nothing(clean):
    findings, errors = run_rules(clean)
    assert findings == [] and errors == []


def check(d, id_):
    assert d is not None and d["id"] == id_ and REQUIRED_KEYS <= set(d)
    assert d["severity"] in ("high", "medium", "low") and d["detected_by"] == "rule"
    assert all(src.get("unit") in SOURCE_UNITS for src in d["sources"]), d["sources"]
    return d


def test_occupancy_mismatch():
    ctx = make_context(om=make_om(occupancy_stated=verified(0.97, "Occupancy 97%")))   # roll: 38/40 = 95%
    assert occupancy_mismatch(ctx) is None                                               # 2 points: within threshold
    ctx = make_context(om=make_om(occupancy_stated=verified(0.99, "Occupancy 99%")),
                       rr=make_rr(standard_units(vacant=4)))                             # roll 90%
    d = check(occupancy_mismatch(ctx), "occupancy_mismatch")
    assert d["relied_on"] == "rent_roll" and d["severity"] == "high" and d["impact"]["delta_aed"] < 0


def test_potential_rent_as_income():
    units = standard_units(vacant=0)[:38] + [rr_unit("901", status="vacant", asking=80_000, row=90),
                                             rr_unit("902", status="vacant", asking=80_000, row=91)]
    rr = make_rr(units)
    in_place, potential = rr["summary"]["in_place_rent_aed"], rr["summary"]["potential_rent_aed"]
    ctx = make_context(om=make_om(annual_rent_stated=verified(in_place, "Rent", basis="unstated")), rr=rr)
    assert potential_rent_as_income(ctx) is None
    ctx = make_context(om=make_om(annual_rent_stated=verified(potential, "Rent", basis="unstated")), rr=rr)
    d = check(potential_rent_as_income(ctx), "potential_rent_as_income")
    assert "asking rent on 2 vacant units" in d["why"] and d["impact"]["delta_aed"] == -160_000


def test_gross_yield_as_net(clean):
    rent = clean.rr["summary"]["in_place_rent_aed"]
    gross = rent / 32_000_000
    ctx = make_context(om=make_om(annual_rent_stated=verified(rent, "Rent", basis="in_place"),
                                  yield_stated=verified(round(gross, 4), "Net yield", basis={"measure": "net", "on": "asking_price"})))
    d = check(gross_yield_as_net(ctx), "gross_yield_as_net")
    assert "equals the gross yield" in d["why"] and d["impact"]["delta_aed"] < 0
    noi = ctx.uw["metrics"]["noi_year1"]["value"]
    honest = make_context(om=make_om(annual_rent_stated=verified(rent, "Rent", basis="in_place"),
                                     net_income_stated_aed=verified(noi, "NOI"),
                                     yield_stated=verified(round(noi / 32_000_000, 4), "Net yield",
                                                           basis={"measure": "net", "on": "asking_price"})))
    assert gross_yield_as_net(honest) is None


def test_yield_excludes_acquisition_costs(clean):
    rent = clean.rr["summary"]["in_place_rent_aed"]
    on_price = make_context(om=make_om(annual_rent_stated=verified(rent, "Rent", basis="in_place"),
                                       yield_stated=verified(round(rent / 32_000_000, 4), "ROI",
                                                             basis={"measure": "gross", "on": "asking_price"})))
    d = check(yield_excludes_acquisition_costs(on_price), "yield_excludes_acquisition_costs")
    assert d["impact"]["delta"] < 0
    on_cost = make_context(om=make_om(yield_stated=verified(0.06, "NIY after purchaser's costs",
                                                            basis={"measure": "net", "on": "total_cost"})))
    assert yield_excludes_acquisition_costs(on_cost) is None


def test_over_rented_vs_market():
    # reference rent for a 750 sq ft JVC 1BR is 105 x 750 = 78,750; 30 of 40 units let at 95,000
    units = standard_units(rent=95_000)[:30] + standard_units(rent=70_000, vacant=0, start=30)[:10]
    for i, u in enumerate(units):
        u["unit"], u["source"]["range"] = str(500 + i), f"RR!A{5 + i}:K{5 + i}"
    d = check(over_rented_vs_market(make_context(rr=make_rr(units))), "over_rented_vs_market")
    assert d["impact"]["metric"] == "noi_year1" and d["impact"]["delta_aed"] < 0   # engine-priced reset to market
    assert over_rented_vs_market(make_context()) is None


def test_upside_exceeds_rera_cap():
    units = standard_units(rent=60_000, vacant=0)       # ~24% below the 78,750 reference
    claim = lambda x: {"quote": f"{x:.0%} reversion", "source": {"doc": "om.pdf", "page": 1, "bbox": []},
                       "claimed_uplift": x, "status": "verified", "reason": None}
    ok = make_context(om=make_om(upside_claims=[claim(0.05)]), rr=make_rr(units))
    assert upside_exceeds_rera_cap(ok) is None
    bad = make_context(om=make_om(upside_claims=[claim(0.25)]), rr=make_rr(units))
    d = check(upside_exceeds_rera_cap(bad), "upside_exceeds_rera_cap")
    assert d["sources"][1]["value"] < 0.25
    unverified = make_context(om=make_om(upside_claims=[claim(0.25) | {"status": "unverified"}]), rr=make_rr(units))
    assert upside_exceeds_rera_cap(unverified) is None


def test_missing_opex_items():
    rr = make_rr(standard_units())
    partial = {k: v for k, v in FULL_OPEX.items() if k not in ("insurance", "sinking_fund")}
    ctx = make_context(rr=rr, opex=make_opex(partial, absent=["insurance", "sinking_fund"],
                                             rental_income=rr["summary"]["in_place_rent_aed"]))
    d = check(missing_opex_items(ctx), "missing_opex_items")
    assert d["impact"]["delta_aed"] > 0          # the statement overstates NOI by the defaults
    assert d["relied_on"] == "mandate_defaults"
    assert missing_opex_items(make_context()) is None


def test_area_basis_confusion():
    rr = make_rr(standard_units())
    area = rr["summary"]["area_sqft_total"]                     # 30,000 sq ft
    sqm_as_sqft = verified(round(area / 10.7639), "NSA 2,787 sq ft", stated={"value": 2787, "unit": "sqft"})
    d = check(area_basis_confusion(make_context(om=make_om(nsa_sqft=sqm_as_sqft), rr=rr)), "area_basis_confusion")
    assert "sq m labelled sq ft" in d["title"]
    psf_bua = make_om(bua_sqft=verified(40_000.0, "BUA 40,000 sq ft"),
                      price_psf_stated=verified(800.0, "AED 800 per sq ft", basis="unstated"))
    d = check(area_basis_confusion(make_context(om=psf_bua, rr=rr)), "area_basis_confusion")
    assert "on BUA without saying so" in d["title"]
    labelled = make_om(bua_sqft=verified(40_000.0, "BUA"), price_psf_stated=verified(800.0, "AED 800 psf BUA", basis="bua"))
    assert area_basis_confusion(make_context(om=labelled, rr=rr)) is None


def test_rent_roll_does_not_foot():
    units = standard_units()
    in_place = sum(u["annual_rent_aed"] or 0 for u in units)
    good = make_rr(units, stated_totals=[{"measure": "annual_rent", "label": "Total", "value": in_place, "cell": "RR!H50"}])
    assert rent_roll_does_not_foot(make_context(rr=good)) is None
    stale = make_rr(units, stated_totals=[{"measure": "annual_rent", "label": "Total", "value": in_place + 233_000,
                                           "cell": "RR!H50"}])
    d = check(rent_roll_does_not_foot(make_context(rr=stale)), "rent_roll_does_not_foot")
    assert d["impact"]["delta_aed"] == -233_000 and d["relied_on"] == "rent_roll_rows"


def test_unit_mix_mismatch():
    ctx = make_context(om=make_om(unit_count=verified(40, "40 units"), unit_mix=verified({"1br": 40}, "1BR 40")))
    assert unit_mix_mismatch(ctx) is None
    ctx = make_context(om=make_om(unit_count=verified(42, "42 units"), unit_mix=verified({"1br": 36, "studio": 6}, "x")))
    d = check(unit_mix_mismatch(ctx), "unit_mix_mismatch")
    assert "OM 42 units vs rent roll 40" in d["title"] and "studio: OM 6 vs roll 0" in d["title"]


def test_expired_lease_counted_occupied():
    units = standard_units()
    units[5]["lease_end"] = "2026-08-31"         # before the 31 Oct 2026 roll date, still "occupied"
    units[6]["ejari_no"] = None
    d = check(expired_lease_counted_occupied(make_context(rr=make_rr(units))), "expired_lease_counted_occupied")
    assert units[5]["unit"] in d["title"] and units[6]["unit"] in d["title"]
    assert expired_lease_counted_occupied(make_context()) is None


def test_collections_gap():
    rr = make_rr(standard_units())
    in_place = rr["summary"]["in_place_rent_aed"]
    near = make_context(rr=rr, opex=make_opex(FULL_OPEX, rental_income=in_place * 0.96))
    assert collections_gap(near) is None
    far = make_context(rr=rr, opex=make_opex(FULL_OPEX, rental_income=in_place * 0.85))
    d = check(collections_gap(far), "collections_gap")
    assert d["severity"] == "high" and d["impact"]["delta_aed"] == pytest.approx(-0.15 * in_place, abs=1)


def test_annualised_partial_period():
    rr = make_rr(standard_units())
    nine = make_context(rr=rr, opex=make_opex(FULL_OPEX, months=9, rental_income=rr["summary"]["in_place_rent_aed"]))
    check(annualised_partial_period(nine), "annualised_partial_period")
    honest = make_context(rr=rr, opex=make_opex(FULL_OPEX, months=9, presented=False,
                                                rental_income=rr["summary"]["in_place_rent_aed"]))
    assert annualised_partial_period(honest) is None


def test_master_lease_rule_and_related_party():
    units = standard_units()
    ml = {"tenant": "Op LLC", "annual_rent_aed": 3_400_000.0, "lease_end": "2029-06-30", "cheques": 4,
          "source": {"range": "Master!A2:C2", "cells": {}}}
    d = check(master_lease(make_context(rr=make_rr(units, master_lease=ml))), "master_lease_related_party")
    assert d["impact"]["delta_aed"] < 0       # sub-tenants pay less than the master lease
    assert master_lease(make_context()) is None
    model = dict(d, detected_by="model", related_party=True, sources=[])
    merged = merge([d], [model])
    assert merged[0]["detected_by"] == "rule+model"
    assert related_party_flag(merged, "master_lease_related_party", make_om()) == (True, "master_lease")
    assert related_party_flag([], "unclear", make_om()) == (False, "direct_leases")
    assert related_party_flag([], "unclear", make_om(lease_structure=None)) == (None, None)


def test_expiry_concentration():
    units = standard_units()
    for u in units[2:32]:
        u["lease_end"] = "2027-01-31"            # 30 of 38 leases end in one quarter
    d = check(expiry_concentration(make_context(rr=make_rr(units))), "expiry_concentration")
    assert d["severity"] == "high"
    assert expiry_concentration(make_context()) is None


def test_title_check():
    assert title_check(make_context()) is None
    strata = make_om(title_type=verified({"tenure": "freehold", "ownership": "strata"}, "96 title deeds"))
    assert title_check(make_context(om=strata)) is None          # strata fails the mandate's title test instead
    leasehold = make_om(title_type=verified({"tenure": "non_freehold", "ownership": "unstated"}, "GCC nationals only"))
    assert check(title_check(make_context(om=leasehold)), "title_check")["title"] == "OM indicates a non-freehold plot"
    silent = make_om(title_type=None)
    d = check(title_check(make_context(om=silent)), "title_check")
    assert "does not state tenure" in d["why"] and d["title"].startswith("Title not stated; legal check required")


def test_a_rule_that_raises_is_reported_not_swallowed(clean, monkeypatch):
    import pipeline.reconcile as rc

    def broken(ctx):
        raise KeyError("x")
    monkeypatch.setattr(rc, "RULES", [broken])
    findings, errors = rc.run_rules(clean)
    assert findings == [] and errors[0]["rule"] == "broken"


def test_model_finding_contradicted_by_rent_roll_is_rejected(clean):
    rent = clean.rr["summary"]["in_place_rent_aed"]
    ctx = Context(**{**clean.__dict__, "om": make_om(annual_rent_stated=verified(rent, "Rent", basis="unstated"))})
    assert contradicted_by_code({"id": "potential_rent_as_income"}, ctx)
    assert contradicted_by_code({"id": "other_om_claim"}, ctx) is None


def test_master_lease_rent_is_neither_potential_rent_nor_a_footing_break():
    units = standard_units()
    ml = {"tenant": "Op LLC", "annual_rent_aed": 3_400_000.0, "lease_end": "2029-06-30", "cheques": 4,
          "source": {"range": "Master!B3", "cells": {"annual_rent": "Master!B3"}}}
    rr = make_rr(units, master_lease=ml, stated_totals=[{"measure": "annual_rent", "label": "Master rent",
                                                         "value": 3_400_000.0, "cell": "Master!B9"}])
    ctx = make_context(om=make_om(annual_rent_stated=verified(3_400_000.0, "Master lease rent", basis="in_place")), rr=rr)
    assert potential_rent_as_income(ctx) is None
    assert rent_roll_does_not_foot(ctx) is None


def test_title_doubt_needs_strata_or_tenure_evidence_against_a_verified_single_title(clean):
    weak = {"id": "title_check", "severity": "medium",
            "evidence": [{"quote": "Master community charges 58,059"}, {"quote": "Sinking fund 87,194"}]}
    strata = {"id": "title_check", "severity": "high", "evidence": [{"quote": "96 individual title deeds"}]}
    eligibility = {"id": "title_check", "severity": "high",
                   "evidence": [{"quote": "Purchaser eligibility: UAE and GCC nationals only"}]}
    assert contradicted_by_code(weak, clean) and contradicted_by_code(strata, clean)
    assert contradicted_by_code(eligibility, clean) is None


def test_service_charge_budget_covers_common_services():
    rr = make_rr(standard_units())
    oa = {"service_charge": 600_000.0, "insurance": 36_000.0, "sinking_fund": 60_000.0, "property_management": 1.0}
    ctx = make_context(rr=rr, opex=make_opex(oa, absent=["utilities_common", "security_cleaning", "maintenance_repairs"],
                                             rental_income=rr["summary"]["in_place_rent_aed"]))
    assert missing_opex_items(ctx) is None


def test_missing_opex_is_context_aware():
    rr_units = standard_units()
    ml = {"tenant": "Op", "annual_rent_aed": 3_400_000.0, "lease_end": "2029-06-30", "cheques": 4,
          "source": {"range": "M!B3", "cells": {"annual_rent": "M!B3"}}}
    landlord_lines = {"insurance": 36_000.0, "sinking_fund": 60_000.0}
    rr = make_rr(rr_units, master_lease=ml)
    ctx = make_context(rr=rr, opex=make_opex(landlord_lines, absent=["maintenance_repairs", "utilities_common",
                                                                     "security_cleaning", "property_management"],
                                             rental_income=3_400_000.0))
    assert missing_opex_items(ctx) is None          # operator bears running costs under the master lease
    strata = make_om(title_type=verified({"tenure": "freehold", "ownership": "strata"}, "strata title deeds"))
    rr = make_rr(standard_units())
    ctx = make_context(om=strata, rr=rr, opex=make_opex({"service_charge": 100_000.0, **landlord_lines,
                                                          "property_management": 1.0},
                                                         absent=["utilities_common", "security_cleaning"],
                                                         rental_income=rr["summary"]["in_place_rent_aed"]))
    assert missing_opex_items(ctx) is None          # strata: the OA service charge covers common areas
