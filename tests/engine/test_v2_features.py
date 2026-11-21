"""Engine v2 features, hand calculated on Testville units (1BR reference AED 100/sqft).

Mixed-use VAT recovery, leasing cost without double counting, the over-rent threshold,
collection-loss override, security deposits, the age-scaled sinking fund and area names.
"""

import copy

import pytest

from engine import MarketDataError, underwrite
from engine_test_helpers import single_unit_deal


def v(result, name):
    return result["metrics"][name]["value"]


def line(result, name, year=0):
    return result["cash_flow"]["lines"][name]["values"][year]


def two_units(second_type="retail", second_rent=130_000.0, first_rent=100_000.0):
    d = single_unit_deal(rent=first_rent, lease_end="2032-12-31")
    d["nsa_sqft"] = 2000
    d["units"].append({"unit": "S1", "unit_type": second_type, "area_sqft": 1000, "status": "occupied",
                       "annual_rent_aed": second_rent, "lease_end": "2032-12-31"})
    return d


class TestMixedUseVat:
    def test_input_vat_recoverable_on_commercial_share(self, test_mandate, test_market):
        # 1BR at 100,000 and a 1,000 sqft shop at 130,000 (retail factor 1.30), no expiries.
        r = underwrite(two_units(), test_mandate, test_market)
        gross = 230_000
        egi = (gross - 0.05 * gross) * 0.99                     # 216,315.00
        mgmt = 0.05 * egi                                       # 10,815.75
        vat_gross = 0.05 * (mgmt + 5_000)                       # 790.79 (maintenance 5,000 stated)
        share = 130_000 / 230_000
        assert line(r, "commercial_income_share") == pytest.approx(share)
        assert line(r, "input_vat_gross") == pytest.approx(vat_gross)
        assert line(r, "input_vat_recovered") == pytest.approx(vat_gross * share)
        assert line(r, "input_vat") == pytest.approx(vat_gross * (1 - share))
        assert v(r, "noi_year1") == pytest.approx(egi - mgmt - 5_000 - vat_gross * (1 - share))

    def test_all_residential_recovers_nothing(self, test_mandate, test_market):
        r = underwrite(two_units(second_type="1br", second_rent=100_000.0), test_mandate, test_market)
        assert line(r, "input_vat_recovered") == 0.0
        assert v(r, "commercial_income_share_year1") == 0.0


class TestLeasingCosts:
    def _run(self, test_mandate, test_market, marketing_leasing):
        m = copy.deepcopy(test_mandate)
        m["underwriting"]["operations"]["renewal_probability"] = 0.0      # turnover every year
        deal = single_unit_deal(rent=90_000)
        if marketing_leasing is None:
            del deal["opex_aed"]["marketing_leasing"]
        else:
            deal["opex_aed"]["marketing_leasing"] = marketing_leasing
        return underwrite(deal, m, test_market)

    def test_stated_line_covers_modelled_fees_up_to_its_amount(self, test_mandate, test_market):
        fee = 100_000 / 12 * 0.5                                # 4,166.67 on each turnover
        r = self._run(test_mandate, test_market, 3_000.0)
        assert line(r, "leasing_fees_modelled") == pytest.approx(fee)
        assert line(r, "leasing_fees") == pytest.approx(fee - 3_000)
        assert line(r, "leasing_fees", 1) == pytest.approx(fee - 3_000 * 1.025)    # stated line grows
        # Total leasing cost = the larger of the two.
        stated = r["cash_flow"]["opex_by_category"]["marketing_leasing"]["values"][0]
        assert stated + line(r, "leasing_fees") == pytest.approx(max(stated, fee))

    def test_large_stated_line_means_no_modelled_fees(self, test_mandate, test_market):
        r = self._run(test_mandate, test_market, 10_000.0)
        assert line(r, "leasing_fees") == 0.0

    def test_without_a_stated_line_modelled_fees_apply_in_full(self, test_mandate, test_market):
        r = self._run(test_mandate, test_market, None)
        assert line(r, "leasing_fees") == pytest.approx(100_000 / 12 * 0.5)


class TestOverRent:
    def test_threshold_and_excess(self, test_mandate, test_market):
        # 1BR at 111,000 (11% above the 100,000 reference) is over-rented; at 109,000 it is not.
        r = underwrite(two_units(second_type="1br", first_rent=111_000, second_rent=109_000),
                       test_mandate, test_market)
        assert v(r, "over_rent_share_of_income") == pytest.approx(111_000 / 220_000)
        assert v(r, "over_rent_excess_at_expiry_aed") == pytest.approx(11_000)
        assert "renewal or expiry" in r["metrics"]["over_rent_excess_at_expiry_aed"]["note"]
        assert v(r, "screen_reference_rent_aed") == pytest.approx(200_000)
        row = r["unit_schedule"]["units"][0]
        assert row["screen_reference_rent_aed"] == 100_000
        assert row["rent_vs_reference"] == pytest.approx(0.11)


class TestOptionalInputs:
    def test_collection_loss_override(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["collection_loss_override"] = 0.05
        r = underwrite(deal, test_mandate, test_market)
        gross = 85_000 / 2 + 89_250 / 2
        assert line(r, "collection_loss") == pytest.approx(0.05 * gross * 0.95)
        assert r["inputs"]["deal.collection_loss_override"]["provenance"] == "document"

    def test_security_deposits_are_reported_not_in_noi(self, test_mandate, test_market):
        base = underwrite(single_unit_deal(), test_mandate, test_market)
        deal = single_unit_deal()
        deal["security_deposits_aed"] = 4_250.0
        r = underwrite(deal, test_mandate, test_market)
        assert v(r, "security_deposits_aed") == 4_250.0
        assert r["closing_adjustments"]["security_deposits_aed"]["value"] == 4_250.0
        assert v(r, "noi_year1") == v(base, "noi_year1")
        assert v(r, "unlevered_irr_pre_tax") == v(base, "unlevered_irr_pre_tax")

    @pytest.mark.parametrize("year, multiplier", [(2020, 1.0), (2018, 1.0), (2017, 1.5), (2008, 1.5),
                                                  (2007, 2.0), (None, 2.0)])
    def test_sinking_fund_default_scales_with_age(self, test_mandate, test_market, year, multiplier):
        # Age at the 2027 start: 2018 -> 9 years (x1.0), 2017 -> 10 (x1.5), 2007 -> 20 (x2.0).
        deal = single_unit_deal()
        del deal["opex_aed"]["sinking_fund"]
        if year is None:
            del deal["completion_year"]
        else:
            deal["completion_year"] = year
        r = underwrite(deal, test_mandate, test_market)
        assert r["inputs"]["deal.opex_aed.sinking_fund"]["value"] == pytest.approx(2.0 * multiplier * 1000)
        assert r["inputs"]["deal.opex_aed.sinking_fund"]["provenance"] == "default"

    def test_stated_sinking_fund_is_not_scaled(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["completion_year"] = 2000
        deal["opex_aed"]["sinking_fund"] = 1_234.0
        r = underwrite(deal, test_mandate, test_market)
        assert r["inputs"]["deal.opex_aed.sinking_fund"]["value"] == 1_234.0


class TestAreas:
    def test_al_barsha_renamed(self, mandate, market):
        deal = single_unit_deal()
        deal["area"] = "Al Barsha"
        with pytest.raises(MarketDataError):
            underwrite(deal, mandate, market)
        deal["area"] = "Al Barsha South"
        r = underwrite(deal, mandate, market)
        assert r["inputs"]["deal.area"]["value"] == "Al Barsha South"
        assert any("Screen reference rent for Al Barsha South is marked UNVERIFIED" in w for w in r["warnings"])
