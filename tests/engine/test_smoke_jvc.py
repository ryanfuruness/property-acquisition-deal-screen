"""Smoke test: a realistic 60-unit JVC building at AED 47m, late-2026 market.

Fixture: 20 studios (420 sqft), 30 1BR (720 sqft), 10 2BR (1,100 sqft); NSA 41,000 sqft,
BUA 52,000 sqft; 57 of 60 let; in-place rents between 18% below and 4% above the
area reference; leases rolling across 2027; T-12 missing admin and sinking fund;
tenants pay chiller. Asking AED 47m = AED 1,146/sqft NSA, AED 904/sqft BUA.

Expected for Dubai in late 2026: going-in net yields of roughly 5.5-7.5% and Year-1
DSCR of 1.2-1.8 at mandate leverage. With the mandate's 45% LTV, 20-year amortisation
and 6.80% rate, the loan constant is 9.29%, so DSCR = net yield on price / (0.45 x 9.29%):
a 6.24% yield gives about 1.49x.

Returns are low: debt at 6.80% costs more than the 6.24% the building yields (negative
leverage), and the house view exits at 6.75%, above the entry yield on price. The
walk-away price, where levered IRR reaches 10%, is therefore well below asking.
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
    assert v(result, "going_in_net_yield_on_cost") < v(result, "going_in_net_yield_on_price")


def test_operating_profile_is_plausible(result):
    assert 0.15 <= v(result, "opex_ratio_year1") <= 0.35
    assert 0.06 <= v(result, "acquisition_costs_pct_of_price") <= 0.065   # 4% DLD + 2.1% broker + fees
    assert 500 <= v(result, "price_per_sqft_bua") <= 1500
    assert v(result, "gross_yield_in_place_on_price") > v(result, "going_in_net_yield_on_price")
    # Annual leases spread over the year: no quarter carries much more than a quarter of income.
    assert 0.25 <= v(result, "max_expiry_share_quarter") <= 0.40


def test_dscr_in_expected_band_and_explained_by_loan_constant(result):
    constant = annuity_payment(1.0, 0.068, 20)
    assert constant == pytest.approx(0.09293, abs=1e-5)
    expected = v(result, "going_in_net_yield_on_price") / (0.45 * constant)
    assert v(result, "dscr_year1") == pytest.approx(expected)
    assert 1.2 <= v(result, "dscr_year1") <= 1.8
    assert v(result, "dscr_year1") >= 1.30          # clears the mandate floor


def test_returns_and_walk_away(result):
    assert v(result, "levered_irr_pre_tax") < v(result, "unlevered_irr_pre_tax") < 0.06
    assert v(result, "levered_irr_post_tax") < v(result, "levered_irr_pre_tax")
    wa = v(result, "walk_away_price_aed")
    assert 30_000_000 < wa < 47_000_000
    assert result["walk_away"]["binding_constraint"] == "levered_irr"


def test_mandate_fit_verdict(result, mandate):
    facts = {"asset_type": "residential_building", "area": "JVC", "title_type": "freehold_single_title",
             "unit_count": 60, "price_aed": 47_000_000, "completion_year": 2016,
             "lease_structure": "direct_leases"}
    fit = mandate_fit(facts, result, mandate)
    assert fit["verdict"] == "Needs work"
    assert fit["hard_fails"] == 0 and fit["unknown"] == 0
    assert sorted(t["name"] for t in fit["tests"] if t["status"] == "fail") == [
        "min_going_in_net_yield_on_cost", "target_equity_multiple", "target_levered_irr"]
