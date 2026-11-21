import engine
import pytest

from helpers import FULL_OPEX, make_om, make_opex, make_rr, rr_unit, standard_units, verified
from pipeline.underwriting import CannotUnderwrite, build_deal_inputs, deal_facts, underwrite

MARKET = engine.load_market()


def build(om=None, rr=None, opex=None, **kw):
    rr = rr or make_rr(standard_units())
    return build_deal_inputs("t", om or make_om(), rr, opex, MARKET, **kw)


def test_unverified_price_cannot_feed_the_engine():
    om = make_om(asking_price_aed=verified(32e6, "x") | {"status": "unverified"})
    with pytest.raises(CannotUnderwrite, match="asking price"):
        build(om=om)


def test_unverified_area_cannot_feed_the_engine():
    with pytest.raises(CannotUnderwrite, match="market area"):
        build(om=make_om(market_area=None))
    with pytest.raises(CannotUnderwrite, match="outside the market"):
        build(om=make_om(market_area=verified("none_of_these", "Dubai Marina")))


def test_rent_roll_drives_units_not_the_om():
    units = standard_units(vacant=1) + [rr_unit("999", status="vacant", asking=99_000, row=99)]
    om = make_om(annual_rent_stated=verified(9_999_999.0, "Rent", basis="potential"))
    di, prov, _ = build(om=om, rr=make_rr(units))
    assert len(di["units"]) == 41
    vac = next(u for u in di["units"] if u["unit"] == "999")
    assert vac["status"] == "vacant" and vac["annual_rent_aed"] is None      # asking rent never becomes income
    assert prov["units"]["from"] == "rent_roll"
    assert di["om_stated"]["annual_rent_aed"] == 9_999_999.0                 # only used for the OM yield check


def test_unrecognised_units_are_excluded_and_reported():
    units = standard_units()
    units[0]["unit_type"], units[0]["unit_type_text"] = "other", "Penthouse"
    units[1]["area_sqft"] = None
    di, prov, notes = build(rr=make_rr(units))
    assert len(di["units"]) == 38 and len(prov["units"]["excluded"]) == 2 and notes


def test_nsa_from_rent_roll_areas_with_om_noted():
    di, prov, _ = build(om=make_om(nsa_sqft=verified(31_000.0, "NSA 31,000 sq ft")))
    assert di["nsa_sqft"] == 30_000 and "OM states 31,000" in prov["nsa_sqft"]["note"]


def test_opex_only_stated_categories_and_engine_defaults_the_rest():
    rr = make_rr(standard_units())
    opex = make_opex({"maintenance_repairs": 120_000.0, "district_cooling": 0.0}, rental_income=1.0)
    di, prov, _ = build(rr=rr, opex=opex)
    assert di["opex_aed"] == {"maintenance_repairs": 120_000.0}
    uw = underwrite(di, engine.load_mandate(), MARKET)
    assert uw["inputs"]["deal.opex_aed.insurance"]["provenance"] == "default"
    assert uw["inputs"]["deal.opex_aed.maintenance_repairs"]["provenance"] == "document"


def test_chiller_from_om_then_rent_roll():
    di, prov, _ = build()
    assert di["chiller_landlord_pays"] is False and prov["chiller_landlord_pays"]["from"] == "om.chiller_arrangement"
    units = standard_units()
    for u in units:
        u["chiller"] = "Chiller free"
    di, prov, _ = build(om=make_om(chiller_arrangement=None), rr=make_rr(units))
    assert di["chiller_landlord_pays"] is True and prov["chiller_landlord_pays"]["from"] == "rent_roll.chiller"
    di, _, _ = build(om=make_om(chiller_arrangement=None))
    assert di["chiller_landlord_pays"] is None


def test_rent_roll_date_and_other_income_passed():
    rr = make_rr(standard_units())
    di, _, _ = build(rr=rr, opex=make_opex(FULL_OPEX | {"other_income": 50_000.0}, rental_income=1.0))
    assert di["rent_roll_date"] == "2026-10-31" and di["other_income_aed"] == 50_000.0
    underwrite(di, engine.load_mandate(), MARKET)   # the engine accepts what we build


def test_master_lease_input():
    ml = {"tenant": "Op LLC", "annual_rent_aed": 3_400_000.0, "lease_end": "2029-06-30", "cheques": 4,
          "source": {"range": "M!A2:C2", "cells": {"annual_rent": "M!B2"}}}
    di, prov, _ = build(rr=make_rr(standard_units(), master_lease=ml), related_party=True)
    assert di["master_lease"]["related_party"] is True and di["master_lease"]["annual_rent_aed"] == 3_400_000.0
    fit = engine.mandate_fit({"lease_structure": "master_lease", "master_lease_related_party": True},
                             underwrite(di, engine.load_mandate(), MARKET), engine.load_mandate())
    assert fit["verdict"] == "Pass"


def test_deal_facts_from_verified_fields_only():
    om = make_om(completion_year=verified(2015, "x") | {"status": "unverified"})
    facts, _ = deal_facts(om, make_rr(standard_units()), related_party=False, lease_structure="direct_leases")
    assert facts["title_type"] == "freehold_single_title" and facts["unit_count"] == 40
    assert "completion_year" not in facts and facts["master_lease_related_party"] is False
    mixed = make_om(asset_type=verified("mixed_use_residential_retail", "with retail"),
                    title_type=verified({"tenure": "freehold", "ownership": "unstated"}, "Freehold"))
    facts, _ = deal_facts(mixed, None, None, None)
    assert facts["asset_type"] == "residential_building" and "title_type" not in facts
