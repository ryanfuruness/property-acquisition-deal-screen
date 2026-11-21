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
    assert s["blocked_on"] == [{"test": "title", "statement": TITLE_BLOCK}]
    assert "blocked on title" in s["headline"] and "_" not in s["plain_reason"]


def test_known_title_is_not_blocking():
    s = summarise_fit(fit_for(make_om()))
    assert s["blocked_on"] == [] and "_" not in s["headline"]


def test_plain_reason_keeps_capitals():
    s = summarise_fit(fit_for(make_om(title_type=None)))
    assert "IRR" in s["plain_reason"] or "Meets" in s["plain_reason"]
    assert "irr" not in s["plain_reason"]
