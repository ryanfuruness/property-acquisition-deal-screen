import engine

from helpers import make_context, make_om, make_opex, make_rr, standard_units, verified
from pipeline.notices import build_notices, diligence_items, tenant_key

MANDATE = engine.load_mandate()      # as_of 2026-11-21 is the screen date


def ids(notices):
    return [n["id"] for n in notices]


def test_stale_and_inferred_rent_roll_date():
    rr = make_rr(standard_units(), as_of="2026-09-30")
    rr["as_of_source"] = {"how": "file name; month only, read as month end"}
    n = build_notices(rr, None, None, MANDATE)
    assert "stale_rent_roll" in ids(n) and "rent_roll_date_inferred" in ids(n)
    fresh = make_rr(standard_units(), as_of="2026-11-15")
    fresh["as_of_source"] = {"how": "dated line in the document"}
    assert not {"stale_rent_roll", "rent_roll_date_inferred"} & set(ids(build_notices(fresh, None, None, MANDATE)))


def test_tenant_concentration_groups_normalised_names():
    assert tenant_key("Northstar Engineering Consultants L.L.C.") == tenant_key("NORTHSTAR ENGINEERING CONSULTANTS LLC")
    units = standard_units(vacant=0)
    for i, u in enumerate(units[:6]):
        u["tenant"] = "Acme Staff Housing L.L.C" if i % 2 else "ACME STAFF HOUSING LLC"
    n = [x for x in build_notices(make_rr(units), None, None, MANDATE) if x["id"] == "tenant_concentration"]
    assert n and n[0]["values"]["units"] == 6


def test_deposits_cheques_and_statement_trend():
    units = standard_units()
    for u in units:
        u["deposit_aed"] = 3000.0
    opex = make_opex({"insurance": 1.0}, rental_income=1_000_000.0)
    opex["prior_period"] = {"label": "FY2025", "noi_aed": opex["noi_aed"] / 0.8}
    n = {x["id"]: x for x in build_notices(make_rr(units), opex, None, MANDATE)}
    assert n["security_deposits"]["values"]["deposits_aed"] == 120_000
    assert "cheque_profile" in n
    assert n["statement_trend"]["severity"] == "warn" and n["statement_trend"]["values"]["change"] < -0.05


def test_diligence_items_follow_the_deal():
    old = make_om(completion_year=verified(2009, "Completed 2009"))
    got = {it["id"] for it in diligence_items(old, make_rr(standard_units()), MANDATE)}
    assert {"title_eligibility", "civil_defence_cladding", "condition_capex", "ejari_export"} <= got
    assert "service_charge_status" not in got and "master_lease_documents" not in got
    strata = make_om(title_type=verified({"tenure": "freehold", "ownership": "strata"}, "strata"),
                     completion_year=verified(2022, "2022"))
    got = {it["id"] for it in diligence_items(strata, make_rr(standard_units()), MANDATE)}
    assert "service_charge_status" in got and "condition_capex" not in got


def test_notices_reach_the_run_context():
    ctx = make_context()
    assert isinstance(build_notices(ctx.rr, ctx.opex, ctx.uw, MANDATE), list)
