import engine

from helpers import make_om, make_rr, standard_units
from pipeline.underwriting import build_deal_inputs, deal_facts, underwrite
from pipeline.verdict import TITLE_BLOCK, summarise_fit


def fit_for(om):
    mandate, market = engine.load_mandate(), engine.load_market()
    rr = make_rr(standard_units())
    di, _, _ = build_deal_inputs("t", om, rr, None, market)
    facts, _ = deal_facts(om, rr, False, "direct_leases")
    return engine.mandate_fit(facts, underwrite(di, mandate, market), mandate)


def test_unknown_title_blocks_the_deal_in_plain_words():
    s = summarise_fit(fit_for(make_om(title_type=None)))
    assert s["blocked_on_statements"] == [{"test": "title", "statement": TITLE_BLOCK}]
    assert s["headline"].startswith("Needs work, blocked on freehold single title: Title not stated")
    assert "_" not in s["plain_reason"]


def test_known_title_is_not_blocking():
    s = summarise_fit(fit_for(make_om()))
    assert s["blocked_on_statements"] == [] and "_" not in s["headline"]


def test_plain_reason_keeps_capitals():
    s = summarise_fit(fit_for(make_om(title_type=None)))
    assert "irr" not in s["plain_reason"] and "irr" not in s["headline"]


def test_decline_states_the_hard_fail_only():
    import engine
    fit = engine.mandate_fit({"area": "Al Barsha 1", "asset_type": "residential_building", "title_type":
                              "freehold_single_title", "unit_count": 40, "price_aed": 32e6, "completion_year": 2015,
                              "lease_structure": "direct_leases"}, None, engine.load_mandate())
    s = summarise_fit(fit)
    assert fit["verdict"] == "Decline" and s["headline"] == ("Decline: Declined on the mandate's hard filters: "
                                                             "location in a mandate area.")
    assert "not decisive" in s["plain_reason"]
