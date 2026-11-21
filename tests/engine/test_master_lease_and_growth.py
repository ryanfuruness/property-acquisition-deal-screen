"""Master lease, opex and other-income growth, exit-gain tax, quarterly expiry concentration.

Single-unit cases use Testville: a 1,000 sqft 1BR with a flat AED 100,000 market rent.
"""

import copy

import pytest

from engine import DealInputError, mandate_fit, underwrite
from engine_test_helpers import single_unit_deal


def v(result, name):
    return result["metrics"][name]["value"]


def line(result, name):
    return result["cash_flow"]["lines"][name]["values"]


def with_master(deal, **ml):
    d = copy.deepcopy(deal)
    d["master_lease"] = {"tenant": "Operator LLC", "related_party": False, "annual_rent_aed": 90_000,
                         "lease_end": "2027-06-30", **ml}
    return d


class TestGrowth:
    def test_opex_grows_from_year_two(self, test_mandate, test_market):
        r = underwrite(single_unit_deal(), test_mandate, test_market)
        maint = r["cash_flow"]["opex_by_category"]["maintenance_repairs"]["values"]
        assert maint[0] == pytest.approx(5_000.0)                 # year 1 = stated budget
        assert maint[1] == pytest.approx(5_000.0 * 1.025)
        assert maint[5] == pytest.approx(5_000.0 * 1.025 ** 5)

    def test_other_income_growth(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["other_income_aed"] = 10_000.0
        assert line(underwrite(deal, test_mandate, test_market), "other_income") == [10_000.0] * 6
        m = copy.deepcopy(test_mandate)
        m["underwriting"]["operations"]["other_income_growth"] = 0.10
        other = line(underwrite(deal, m, test_market), "other_income")
        assert other[0] == pytest.approx(10_000.0) and other[2] == pytest.approx(12_100.0)


class TestExitGainTax:
    def test_gain_taxed_in_sale_year(self, test_mandate, test_market):
        # Bought at AED 500k, the unit sells for about AED 0.9m: a taxable gain.
        r = underwrite(single_unit_deal(price=500_000.0), test_mandate, test_market)
        net_sale = v(r, "net_sale_proceeds_aed")
        gain = net_sale - (500_000 + r["acquisition_costs"]["total"]["value"])
        assert v(r, "exit_gain_levered_aed") == pytest.approx(gain)
        assert gain > 0
        noi5 = line(r, "noi")[4]
        interest5 = r["debt_schedule"]["lines"]["interest"]["values"][4]
        taxable = noi5 - interest5 - v(r, "arrangement_fee_aed") / 5 + gain
        expected = 0.09 * max(0.0, taxable - 375_000)
        rc = r["returns_cash_flows"]["lines"]
        assert expected > 0
        assert rc["tax_levered"]["values"][5] == pytest.approx(expected)
        assert rc["levered_pre_tax"]["values"][5] - rc["levered_post_tax"]["values"][5] == pytest.approx(expected)
        # Years 1-4: NOI is below the threshold, so no tax.
        assert rc["tax_levered"]["values"][1:5] == [0.0] * 4
        # Unlevered gain is measured against price + transfer costs (no mortgage registration).
        transfer = r["acquisition_costs"]["transfer_costs"]["value"]
        expected_u = 0.09 * max(0.0, noi5 + net_sale - (500_000 + transfer) - 375_000)
        assert rc["tax_unlevered"]["values"][5] == pytest.approx(expected_u)

    def test_loss_on_sale_offsets_income(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        assert v(r, "exit_gain_levered_aed") < 0
        tax = r["returns_cash_flows"]["lines"]["tax_levered"]["values"]
        assert tax[5] < tax[4]


class TestExpiryWindows:
    """Four 3-month windows from the rent roll date, on stated lease-end dates."""

    def _deal(self, ends, rent_roll_date="2026-10-31"):
        d = single_unit_deal()
        d["units"] = [{"unit": f"U{i}", "unit_type": "1br", "area_sqft": 500, "status": "occupied",
                       "annual_rent_aed": 50_000, "lease_end": e} for i, e in enumerate(ends)]
        if rent_roll_date:
            d["rent_roll_date"] = rent_roll_date
        return d

    def shares(self, r):
        return [w["share"] for w in r["expiry_windows"]["windows"]]

    def test_windows_start_at_rent_roll_date(self, test_mandate, test_market):
        # Windows: 31 Oct-30 Jan, 31 Jan-30 Apr, 30 Apr-30 Jul, 31 Jul-30 Oct.
        r = underwrite(self._deal(["2026-12-31", "2027-01-31", "2027-06-30", "2027-10-31"]),
                       test_mandate, test_market)
        w = r["expiry_windows"]["windows"]
        assert [x["start"] for x in w] == ["2026-10-31", "2027-01-31", "2027-04-30", "2027-07-31"]
        assert w[0]["end"] == "2027-01-30"
        # 31 Oct 2027 is 12 months after the rent roll date: in no window.
        assert self.shares(r) == [0.25, 0.25, 0.25, 0.0]
        assert v(r, "max_expiry_share_quarter") == 0.25
        assert r["expiry_windows"]["basis_date"] == "2026-10-31"

    def test_already_expired_count_in_first_window(self, test_mandate, test_market):
        r = underwrite(self._deal(["2026-08-31", "2026-10-30", "2026-11-30", "2027-05-31"]),
                       test_mandate, test_market)
        assert self.shares(r) == [0.75, 0.0, 0.25, 0.0]
        assert "window 1: 2026-10-31 to 2027-01-30" in r["metrics"]["max_expiry_share_quarter"]["note"]

    def test_falls_back_to_analysis_start_with_warning(self, test_mandate, test_market):
        r = underwrite(self._deal(["2026-12-31", "2027-02-28", "2027-03-31", "2027-04-30"], rent_roll_date=None),
                       test_mandate, test_market)
        assert r["expiry_windows"]["basis_date"] == "2027-01-01"
        assert self.shares(r) == [0.75, 0.25, 0.0, 0.0]
        assert any("Rent roll date not given" in w for w in r["warnings"])
        assert r["inputs"]["deal.rent_roll_date"]["provenance"] == "default"


class TestMasterLease:
    def test_income_until_reversion_then_units_turn_over(self, test_mandate, test_market):
        r = underwrite(with_master(single_unit_deal()), test_mandate, test_market)
        master_income = 90_000 / 2                                # Jan-Jun
        unit_rent = 100_000 / 12 * (6 - 1.5)                      # re-let from July after 1.5 months
        assert line(r, "master_lease_income")[0] == pytest.approx(master_income)
        assert line(r, "gross_rental_income")[0] == pytest.approx(unit_rent)
        # Vacancy allowance on unit rent only (5% = 1,875) is less than the 12,500 of
        # lease-up downtime already modelled, so no top-up. Collection loss on everything.
        assert line(r, "vacancy_allowance")[0] == pytest.approx(0.05 * unit_rent)
        assert line(r, "downtime_loss")[0] == pytest.approx(100_000 / 12 * 1.5)
        assert line(r, "structural_vacancy")[0] == 0.0
        assert line(r, "collection_loss")[0] == pytest.approx(0.01 * (master_income + unit_rent))
        assert line(r, "leasing_fees")[0] == pytest.approx(100_000 / 12 * 0.5)
        assert line(r, "master_lease_income")[1] == 0.0
        assert r["master_lease"]["reversion_date"] == "2027-07-01"

    def test_long_master_lease_has_no_structural_vacancy(self, test_mandate, test_market):
        r = underwrite(with_master(single_unit_deal(), lease_end="2035-12-31"), test_mandate, test_market)
        assert line(r, "master_lease_income") == [90_000.0] * 6
        assert line(r, "structural_vacancy") == [0.0] * 6
        assert v(r, "noi_year1") == pytest.approx(
            90_000 * 0.99 * (1 - 0.05 * 1.05) - 5_000 * 1.05)       # mgmt + VAT, stated opex + VAT

    def test_rent_roll_statistics_follow_the_master_lease(self, test_mandate, test_market):
        r = underwrite(with_master(single_unit_deal(status="vacant"), annual_rent_aed=110_000),
                       test_mandate, test_market)
        assert v(r, "occupancy_by_units") == 1.0
        assert v(r, "in_place_rent_aed") == 110_000
        assert v(r, "over_rent_share_of_income") == 1.0          # above the 100,000 market reference
        assert v(r, "max_expiry_share_quarter") == 1.0           # all income rolls in 2027-Q3

    def test_default_opex_applies_only_after_reversion(self, test_mandate, test_market):
        deal = with_master(single_unit_deal())
        deal["opex_aed"] = {"insurance": 900.0}                    # owner's statement under the lease
        r = underwrite(deal, test_mandate, test_market)
        opex = r["cash_flow"]["opex_by_category"]
        assert opex["insurance"]["values"][0] == pytest.approx(900.0)          # stated: all year
        assert opex["maintenance_repairs"]["values"][0] == pytest.approx(4_000.0 * 0.5)   # from July
        assert opex["maintenance_repairs"]["values"][1] == pytest.approx(4_000.0 * 1.025)

    def test_units_are_optional(self, test_mandate, test_market):
        deal = with_master(single_unit_deal(), lease_end="2029-06-30")
        del deal["units"]
        r = underwrite(deal, test_mandate, test_market)
        assert v(r, "unit_count") is None
        assert any("1BR-equivalent" in w for w in r["warnings"])
        assert line(r, "master_lease_income")[2] == pytest.approx(45_000.0)
        assert line(r, "gross_rental_income")[2] > 0

    def test_units_need_no_rent_under_master_lease(self, test_mandate, test_market):
        deal = with_master(single_unit_deal())
        deal["units"][0].update(annual_rent_aed=None, lease_end=None)
        underwrite(deal, test_mandate, test_market)

    def test_lease_end_required(self, test_mandate, test_market):
        with pytest.raises(DealInputError, match="lease_end"):
            underwrite(with_master(single_unit_deal(), lease_end=None), test_mandate, test_market)

    def test_provenance_of_master_lease_inputs(self, test_mandate, test_market):
        r = underwrite(with_master(single_unit_deal()), test_mandate, test_market)
        names = {d["input"] for d in r["metrics"]["noi_year1"]["depends_on"]}
        assert "deal.master_lease.annual_rent_aed" in names


class TestRelatedPartyFlag:
    FACTS = {"asset_type": "residential_building", "area": "JVC", "title_type": "freehold_single_title",
             "unit_count": 60, "price_aed": 40_000_000, "completion_year": 2016}

    def _test(self, mandate, uw_result, **facts):
        fit = mandate_fit({**self.FACTS, **facts}, uw_result, mandate)
        return next(t for t in fit["tests"] if t["name"] == "no_master_lease_to_related_party")

    @pytest.mark.parametrize("related, status", [(True, "fail"), (False, "pass"), (None, "unknown")])
    def test_flag_taken_from_master_lease(self, mandate, test_mandate, test_market, related, status):
        r = underwrite(with_master(single_unit_deal(), related_party=related), test_mandate, test_market)
        t = self._test(mandate, r)
        assert t["status"] == status and t["source"] == "engine"

    def test_direct_leases_pass(self, mandate):
        assert self._test(mandate, {"metrics": {}, "master_lease": None},
                          lease_structure="direct_leases")["status"] == "pass"

    def test_any_evidence_of_related_party_wins(self, mandate, test_mandate, test_market):
        r = underwrite(with_master(single_unit_deal(), related_party=True), test_mandate, test_market)
        assert self._test(mandate, r, master_lease_related_party=False)["status"] == "fail"


@pytest.mark.parametrize("drop_units", [False, True])
def test_master_lease_result_traces_every_number(test_mandate, test_market, drop_units):
    import json
    deal = with_master(single_unit_deal(), lease_end="2028-03-31")
    if drop_units:
        del deal["units"]
    r = underwrite(deal, test_mandate, test_market)
    json.dumps(r, allow_nan=False)

    def walk(node):
        if isinstance(node, dict):
            if "depends_on" in node:
                assert node["depends_on"]
                for dep in node["depends_on"]:
                    assert r["inputs"][dep["input"]]["provenance"] == dep["provenance"]
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)
    walk(r)
