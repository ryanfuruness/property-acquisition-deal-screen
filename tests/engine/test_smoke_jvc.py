"""Smoke test: a realistic 60-unit JVC building at AED 47m, late-2026 market.

Fixture: 20 studios (420 sqft), 30 1BR (720 sqft), 10 2BR (1,100 sqft); NSA 41,000 sqft,
BUA 52,000 sqft; completed 2016; 57 of 60 let; in-place rents between 18% below and
4% above the screen reference rent; leases rolling across 2027; T-12 missing admin and
sinking fund; tenants pay chiller. Asking AED 47m = AED 1,146/sqft NSA, AED 904/sqft BUA.

Expected for Dubai in late 2026: going-in net yields of roughly 5.5-7.5%. Debt is sized
to cover: the loan is the lower of 45% LTV and what Year-1 NOI supports at 1.40x over a
15-year amortisation at 6.80% (loan constant 10.84%), so DSCR is at least 1.40x.

The exit yield is never below the entry yield, so at this price the deal earns little
more than its income: the unlevered IRR is about 5%, below the 7.5% target, and the
walk-away price is well below asking.
"""

import pytest

from engine import mandate_fit, underwrite
from engine.finance import annuity_payment


@pytest.fixture
def result(jvc_deal, mandate, market):
    return underwrite(jvc_deal, mandate, market)


def v(result, name):
    return result["metrics"][name]["value"]


def test_going_in_yields_in_expected_band(result):
    assert 0.055 <= v(result, "going_in_net_yield_on_price") <= 0.075
    assert 0.055 <= v(result, "going_in_net_yield_on_cost") <= 0.075
    assert v(result, "going_in_net_yield_on_cost") < v(result, "entry_yield_on_price")


def test_operating_profile_is_plausible(result):
    assert 0.15 <= v(result, "opex_ratio_year1") <= 0.35
    assert 0.06 <= v(result, "acquisition_costs_pct_of_price") <= 0.065   # 4% DLD + 2.1% broker + fees
    assert 500 <= v(result, "price_per_sqft_bua") <= 1500
    assert v(result, "gross_yield_in_place_on_price") > v(result, "going_in_net_yield_on_price")
    assert 0.25 <= v(result, "max_expiry_share_quarter") <= 0.40


def test_debt_sized_to_cover(result, mandate):
    debt = mandate["underwriting"]["debt"]
    constant = annuity_payment(1.0, debt["base_rate_3m_eibor"] + debt["margin"], debt["amortisation_years"])
    assert constant == pytest.approx(0.10841, abs=1e-5)
    noi, price = v(result, "noi_year1"), v(result, "price_aed")
    expected_loan = min(debt["max_ltv"] * price, noi / (debt["sizing_dscr"] * constant))
    assert v(result, "loan_aed") == pytest.approx(expected_loan)
    assert v(result, "dscr_year1") >= debt["sizing_dscr"] - 1e-9
    assert 1.2 <= v(result, "dscr_year1") <= 1.8
    assert result["debt"]["sizing_constraint"] in ("ltv", "dscr")


def test_exit_never_below_entry(result):
    assert v(result, "exit_yield") >= v(result, "entry_yield_on_price") + 0.0025 - 1e-12
    assert result["exit"]["age_premium_bps"] == 0                 # 16 years old at exit
    assert result["exit"]["summary"].startswith("Buy at ")


def test_returns_and_walk_away(result, mandate):
    target = mandate["buy_box"]["soft"]["target_unlevered_irr"]
    assert 0.0 < v(result, "unlevered_irr_pre_tax") < target
    assert v(result, "unlevered_irr_post_tax") < v(result, "unlevered_irr_pre_tax")
    assert result["metrics"]["unlevered_irr_post_tax"]["indicative"] is True
    wa = v(result, "walk_away_price_aed")
    assert 25_000_000 < wa < 47_000_000
    assert result["walk_away"]["binding_constraint"] == "unlevered_irr"
    assert result["walk_away"]["most_sensitive_assumption"] in ("exit_yield", "reference_rent_path")
    assert result["headline"][0] == "unlevered_irr_pre_tax"


def test_mandate_fit_verdict(result, mandate):
    facts = {"asset_type": "residential_building", "area": "JVC", "title_type": "freehold_single_title",
             "unit_count": 60, "price_aed": 47_000_000, "completion_year": 2016,
             "lease_structure": "direct_leases"}
    fit = mandate_fit(facts, result, mandate)
    assert fit["verdict"] == "Needs work"
    assert fit["hard_fails"] == 0 and fit["unknown"] == 0 and fit["blocked_on"] == []
    fails = {t["name"] for t in fit["tests"] if t["status"] == "fail"}
    assert {"target_unlevered_irr", "target_unlevered_equity_multiple"} <= fails
