"""End-to-end underwriting: hand-calculated NOI, opex defaults, provenance, walk-away, determinism."""

import copy
import json
import math
import os
import subprocess
import sys

import pytest

from engine import DealInputError, MarketDataError, underwrite
from engine.costs import acquisition_costs, mandate_acquisition_rates
from engine.finance import annuity_payment

from engine_test_helpers import REPO_ROOT, single_unit_deal


def v(result, name):
    return result["metrics"][name]["value"]


class TestSingleUnitNoi:
    def test_year_one_noi_hand_calculated(self, test_mandate, test_market):
        # 85,000 rent to 30 Jun 2027, renews at +5% (15% below the 100,000 index).
        r = underwrite(single_unit_deal(), test_mandate, test_market)
        gross = 85_000 / 2 + 89_250 / 2                       # 87,125.00
        vacancy = gross * 0.05                                # 4,356.25
        collection = (gross - vacancy) * 0.01                 # 827.69
        egi = gross - vacancy - collection                    # 81,941.06
        mgmt = egi * 0.05                                     # 4,097.05
        opex = 5_000.0                                        # stated maintenance; all else stated 0
        vat = 0.05 * (mgmt + opex)                            # 454.85
        noi = egi - mgmt - opex - vat                         # 72,389.16
        cf = r["cash_flow"]["lines"]
        assert cf["gross_rental_income"]["values"][0] == pytest.approx(gross)
        assert cf["effective_gross_income"]["values"][0] == pytest.approx(egi)
        assert cf["input_vat"]["values"][0] == pytest.approx(vat)
        assert v(r, "noi_year1") == pytest.approx(noi)
        assert v(r, "noi_year1") == pytest.approx(72_389.15671875)
        assert v(r, "going_in_net_yield_on_price") == pytest.approx(noi / 1_000_000)

    def test_exit_and_returns_consistent(self, test_mandate, test_market):
        r = underwrite(single_unit_deal(), test_mandate, test_market)
        fwd = r["cash_flow"]["lines"]["noi"]["values"][5]
        assert v(r, "forward_noi_aed") == pytest.approx(fwd)
        assert v(r, "exit_yield") == pytest.approx(0.075 + 0.0025)
        assert v(r, "gross_exit_value_aed") == pytest.approx(fwd / 0.0775)
        assert v(r, "net_sale_proceeds_aed") == pytest.approx(fwd / 0.0775 * 0.98)
        lev = r["returns_cash_flows"]["lines"]["levered_pre_tax"]["values"]
        assert lev[0] == pytest.approx(-v(r, "equity_aed"))
        assert lev[-1] == pytest.approx(r["cash_flow"]["lines"]["noi"]["values"][4]
                                        - v(r, "annual_debt_service_aed")
                                        + v(r, "net_sale_proceeds_aed") - v(r, "loan_balance_at_exit_aed"))

    def test_tax_applies_above_threshold_only(self, test_mandate, test_market):
        # A one-unit building earns far below AED 375k: no tax, so post-tax = pre-tax.
        r = underwrite(single_unit_deal(), test_mandate, test_market)
        assert v(r, "levered_irr_post_tax") == pytest.approx(v(r, "levered_irr_pre_tax"))

    def test_tax_hand_calculated_on_large_deal(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        noi1 = v(r, "noi_year1")
        interest1 = r["debt_schedule"]["lines"]["interest"]["values"][0]
        fee_amort = v(r, "arrangement_fee_aed") / 5
        expected = 0.09 * (noi1 - interest1 - fee_amort - 375_000)
        assert r["returns_cash_flows"]["lines"]["tax_levered"]["values"][1] == pytest.approx(expected)
        assert r["returns_cash_flows"]["lines"]["tax_unlevered"]["values"][1] == pytest.approx(
            0.09 * (noi1 - 375_000))


class TestOpex:
    def test_missing_categories_use_mandate_defaults(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["opex_aed"] = {"maintenance_repairs": 5000.0}
        r = underwrite(deal, test_mandate, test_market)
        inputs = r["inputs"]
        assert inputs["deal.opex_aed.maintenance_repairs"]["provenance"] == "document"
        # 1.2 AED/sqft x 1,000 sqft NSA
        assert inputs["deal.opex_aed.insurance"] == {
            "value": 1200.0, "unit": "AED/yr", "provenance": "default",
            "note": "missing from the operating statement; mandate default 1.2 AED/sqft NSA"}
        for cat, rate in (("security_cleaning", 3.0), ("utilities_common", 2.0),
                          ("admin_other", 0.8), ("sinking_fund", 2.0)):
            assert inputs[f"deal.opex_aed.{cat}"]["value"] == pytest.approx(rate * 1000)
            assert inputs[f"deal.opex_aed.{cat}"]["provenance"] == "default"
        # Not chiller-free, so no district cooling default.
        assert "district_cooling" not in r["cash_flow"]["opex_by_category"]

    def test_district_cooling_default_only_if_landlord_pays(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["opex_aed"] = {}
        deal["chiller_landlord_pays"] = True
        r = underwrite(deal, test_mandate, test_market)
        assert r["inputs"]["deal.opex_aed.district_cooling"]["value"] == pytest.approx(9000.0)
        deal["chiller_landlord_pays"] = None              # unstated: conservative default
        r2 = underwrite(deal, test_mandate, test_market)
        assert r2["inputs"]["deal.opex_aed.district_cooling"]["value"] == pytest.approx(9000.0)
        assert any("Chiller" in w for w in r2["warnings"])

    def test_vat_excludes_sinking_fund_and_respects_opex_includes_vat(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["opex_aed"]["sinking_fund"] = 10_000.0
        r = underwrite(deal, test_mandate, test_market)
        mgmt = r["cash_flow"]["lines"]["management_fee"]["values"][0]
        assert r["cash_flow"]["lines"]["input_vat"]["values"][0] == pytest.approx(0.05 * (mgmt + 5000))
        deal["opex_includes_vat"] = True
        r2 = underwrite(deal, test_mandate, test_market)
        assert r2["cash_flow"]["lines"]["input_vat"]["values"][0] == pytest.approx(0.05 * mgmt)

    def test_stated_management_fee_is_replaced_by_mandate_fee(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["opex_aed"]["property_management"] = 1.0
        r = underwrite(deal, test_mandate, test_market)
        assert "not used" in r["inputs"]["deal.opex_aed.property_management"]["note"]
        egi = v(r, "effective_gross_income_year1")
        assert r["cash_flow"]["lines"]["management_fee"]["values"][0] == pytest.approx(0.05 * egi)


class TestValidation:
    def test_unknown_area_is_market_data_error(self, mandate, market):
        deal = single_unit_deal()
        deal["area"] = "Dubai Marina"
        with pytest.raises(MarketDataError):
            underwrite(deal, mandate, market)

    @pytest.mark.parametrize("mutate, message", [
        (lambda d: d.pop("price_aed"), "price_aed"),
        (lambda d: d.update(colour="blue"), "unknown deal_inputs"),
        (lambda d: d["units"][0].update(unit_type="penthouse"), "unit_type"),
        (lambda d: d["units"][0].update(annual_rent_aed=None), "annual_rent_aed"),
        (lambda d: d["opex_aed"].update(parking=1), "unknown categories"),
    ])
    def test_schema_errors(self, test_mandate, test_market, mutate, message):
        deal = single_unit_deal()
        mutate(deal)
        with pytest.raises(DealInputError, match=message):
            underwrite(deal, test_mandate, test_market)

    def test_unit_type_and_area_are_normalised(self, test_mandate, test_market):
        deal = single_unit_deal()
        deal["units"][0]["unit_type"] = "1 BR"
        deal["area"] = "testville"
        r = underwrite(deal, test_mandate, test_market)
        assert r["inputs"]["deal.area"]["value"] == "Testville"


def _walk(node, path=""):
    if isinstance(node, dict):
        yield path, node
        for k, val in node.items():
            yield from _walk(val, f"{path}.{k}")
    elif isinstance(node, list):
        for i, val in enumerate(node):
            yield from _walk(val, f"{path}[{i}]")


class TestProvenance:
    def test_every_depends_on_refers_to_a_registered_input(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        inputs = r["inputs"]
        count = 0
        for path, node in _walk(r):
            if "depends_on" in node:
                count += 1
                assert node["depends_on"], f"{path} has an empty depends_on"
                for dep in node["depends_on"]:
                    assert dep["input"] in inputs, f"{path}: {dep['input']} not in inputs"
                    assert dep["provenance"] == inputs[dep["input"]]["provenance"]
                    assert dep["provenance"] in ("document", "default", "mandate", "market")
        assert count > 60

    def test_every_metric_has_value_unit_and_depends_on(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        for name, m in r["metrics"].items():
            assert set(m) >= {"value", "unit", "depends_on"}, name

    def test_headline_metrics_trace_to_all_four_sources(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        tags = {d["provenance"] for d in r["metrics"]["noi_year1"]["depends_on"]}
        assert tags == {"document", "default", "mandate", "market"}   # fixture lacks two opex lines
        dscr_inputs = {d["input"] for d in r["metrics"]["dscr_year1"]["depends_on"]}
        assert {"deal.price_aed", "mandate.underwriting.debt.ltv",
                "mandate.underwriting.debt.margin"} <= dscr_inputs

    def test_result_is_json_serialisable(self, jvc_deal, mandate, market):
        json.dumps(underwrite(jvc_deal, mandate, market), allow_nan=False)


class TestWalkAway:
    def _check_boundary(self, deal, mandate, market):
        r = underwrite(deal, mandate, market)
        price = v(r, "walk_away_price_aed")
        assert price is not None and price % 10_000 == 0
        target = mandate["buy_box"]["soft"]["target_levered_irr"]
        floor = mandate["buy_box"]["hard"]["min_dscr_year1"]
        at = underwrite({**deal, "price_aed": price}, mandate, market)
        above = underwrite({**deal, "price_aed": price + 10_000}, mandate, market)
        assert v(at, "levered_irr_pre_tax") >= target
        assert v(at, "dscr_year1") >= floor
        assert v(above, "levered_irr_pre_tax") < target or v(above, "dscr_year1") < floor
        return r, price

    def test_irr_binds_on_jvc_deal(self, jvc_deal, mandate, market):
        r, price = self._check_boundary(jvc_deal, mandate, market)
        assert r["walk_away"]["binding_constraint"] == "levered_irr"
        target = mandate["buy_box"]["soft"]["target_levered_irr"]
        assert r["walk_away"]["levered_irr_at_price"]["value"] == pytest.approx(target, abs=2e-4)

    def test_dscr_binds_when_irr_target_is_low(self, jvc_deal, mandate, market):
        m = copy.deepcopy(mandate)
        m["buy_box"]["soft"]["target_levered_irr"] = -0.50
        r, price = self._check_boundary(jvc_deal, m, market)
        assert r["walk_away"]["binding_constraint"] == "dscr_year1"
        # Analytic: DSCR = NOI / (LTV x P x loan constant) = 1.30 at the limit.
        constant = annuity_payment(1.0, 0.068, 20)
        p_max = v(r, "noi_year1") / (1.30 * 0.45 * constant)
        assert price == math.floor(p_max / 10_000) * 10_000

    def test_walk_away_does_not_depend_on_asking_price(self, jvc_deal, mandate, market):
        a = v(underwrite(jvc_deal, mandate, market), "walk_away_price_aed")
        b = v(underwrite({**jvc_deal, "price_aed": 90_000_000}, mandate, market), "walk_away_price_aed")
        assert a == b


class TestSensitivity:
    def test_grid_shape_and_direction(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        cells = {(c["rent_shift"], c["exit_yield_shift_bps"]): c for c in r["sensitivity"]["cells"]}
        assert len(cells) == 9
        base = cells[(0.0, 0)]
        assert base["levered_irr_pre_tax"] == pytest.approx(v(r, "levered_irr_pre_tax"))
        assert cells[(0.0, -50)]["levered_irr_pre_tax"] > base["levered_irr_pre_tax"] > \
            cells[(0.0, 50)]["levered_irr_pre_tax"]
        assert cells[(0.05, 0)]["levered_irr_pre_tax"] > base["levered_irr_pre_tax"] > \
            cells[(-0.05, 0)]["levered_irr_pre_tax"]
        # The exit yield does not change Year 1; the rent path does.
        assert cells[(0.0, 50)]["noi_year1"] == base["noi_year1"]
        assert cells[(-0.05, 0)]["noi_year1"] < base["noi_year1"]


class TestBreakeven:
    def test_breakeven_occupancy_gives_dscr_one(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        o = v(r, "breakeven_occupancy_dscr_1")
        L = r["cash_flow"]["lines"]
        pgi = L["potential_rental_income"]["values"][0] + L["other_income"]["values"][0]
        egi = o * pgi * 0.99
        opex = L["operating_expenses"]["values"][0]
        fees = L["leasing_fees"]["values"][0]
        vatable_opex = opex - r["inputs"]["deal.opex_aed.sinking_fund"]["value"]
        noi = egi - 0.05 * egi * 1.05 - opex - fees * 1.05 - 0.05 * vatable_opex
        assert noi == pytest.approx(v(r, "annual_debt_service_aed"))


class TestDeterminism:
    def test_same_input_same_output(self, jvc_deal, mandate, market):
        a = json.dumps(underwrite(jvc_deal, mandate, market), sort_keys=True)
        b = json.dumps(underwrite(copy.deepcopy(jvc_deal), mandate, market), sort_keys=True)
        assert a == b

    def test_inputs_are_not_mutated(self, jvc_deal, mandate, market):
        before = (json.dumps(jvc_deal, sort_keys=True), json.dumps(mandate, sort_keys=True, default=str))
        underwrite(jvc_deal, mandate, market)
        assert before == (json.dumps(jvc_deal, sort_keys=True), json.dumps(mandate, sort_keys=True, default=str))

    def test_same_output_across_processes_and_hash_seeds(self):
        code = ("import json, engine, hashlib;"
                "d=json.load(open('tests/engine/fixtures/jvc_60_units.json'));"
                "r=engine.underwrite(d, engine.load_mandate(), engine.load_market());"
                "print(hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest())")
        digests = set()
        for seed in ("0", "1", "12345"):
            out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                                 text=True, check=True, env={**os.environ, "PYTHONHASHSEED": seed})
            digests.add(out.stdout.strip())
        assert len(digests) == 1


def test_acquisition_costs_and_debt_in_result_match_hand_calc(test_mandate, test_market):
    # Price 50m at 45% LTV: loan 22.5m; mortgage registration 0.25% x 22.5m + 290 = 56,540;
    # transfer costs 3,054,780 (see test_finance); total 3,111,320.
    r = underwrite(single_unit_deal(price=50_000_000.0), test_mandate, test_market)
    assert r["acquisition_costs"]["total"]["value"] == pytest.approx(3_111_320.0)
    assert v(r, "loan_aed") == pytest.approx(22_500_000.0)
    # 1.068^20 = 3.7275635287; payment = L r f / (f - 1) = 2,090,940.19 (20-year amortisation).
    assert v(r, "annual_debt_service_aed") == pytest.approx(2_090_940.19, abs=0.01)
    assert v(r, "arrangement_fee_aed") == pytest.approx(168_750.0)      # 0.75% of the loan
    assert v(r, "equity_aed") == pytest.approx(50_000_000 + 3_111_320 + 168_750 - 22_500_000)
    expected = acquisition_costs(50_000_000.0, 22_500_000.0, mandate_acquisition_rates(test_mandate))
    assert r["acquisition_costs"]["dld_transfer_fee"]["value"] == expected["dld_transfer_fee"]


def test_legal_case_counts_as_let_but_earns_nothing_at_start(test_mandate, test_market):
    deal = single_unit_deal()
    deal["units"][0]["status"] = "legal_case"
    r = underwrite(deal, test_mandate, test_market)
    assert v(r, "occupancy_by_units") == 1.0
    assert v(r, "in_place_rent_aed") == 85_000
    # Cash flow: vacant at the start, leases up at the 100,000 market after 1.5 months.
    assert v(r, "gross_rental_income_year1") == pytest.approx(100_000 - 12_500)


class TestVacancyAllowance:
    """Structural vacancy is an allowance that includes modelled downtime: only the top-up is deducted."""

    def _run(self, test_mandate, test_market, p, rent):
        m = copy.deepcopy(test_mandate)
        m["underwriting"]["operations"]["renewal_probability"] = p
        return underwrite(single_unit_deal(rent=rent), m, test_market)["cash_flow"]["lines"]

    def test_no_downtime_takes_full_allowance(self, test_mandate, test_market):
        L = self._run(test_mandate, test_market, 1.0, 85_000)
        assert L["downtime_loss"]["values"][0] == 0.0
        assert L["structural_vacancy"]["values"][0] == pytest.approx(0.05 * 87_125)

    def test_downtime_above_allowance_means_no_top_up(self, test_mandate, test_market):
        # Turnover at month 6: 1.5 months lost = 12,500 > 5% of 82,500 = 4,125.
        L = self._run(test_mandate, test_market, 0.0, 90_000)
        assert L["downtime_loss"]["values"][0] == pytest.approx(12_500)
        assert L["vacancy_allowance"]["values"][0] == pytest.approx(4_125)
        assert L["structural_vacancy"]["values"][0] == 0.0

    def test_partial_top_up(self, test_mandate, test_market):
        # p = 0.7: gross 84,987.50, downtime 0.3 x 12,500 = 3,750, allowance 4,249.375.
        L = self._run(test_mandate, test_market, 0.7, 85_000)
        assert L["downtime_loss"]["values"][0] == pytest.approx(3_750)
        assert L["structural_vacancy"]["values"][0] == pytest.approx(4_249.375 - 3_750)
        assert L["collection_loss"]["values"][0] == pytest.approx(0.01 * (84_987.5 - 499.375))

    def test_rule_holds_every_year(self, jvc_deal, mandate, market):
        L = underwrite(jvc_deal, mandate, market)["cash_flow"]["lines"]
        for a, d, s in zip(L["vacancy_allowance"]["values"], L["downtime_loss"]["values"],
                           L["structural_vacancy"]["values"]):
            assert s == pytest.approx(max(0.0, a - d))
