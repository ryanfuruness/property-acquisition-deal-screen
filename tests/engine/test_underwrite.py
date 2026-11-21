"""End-to-end underwriting: hand-calculated NOI, opex defaults, provenance, walk-away, determinism."""

import copy
import json
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
        assert {"deal.price_aed", "mandate.underwriting.debt.max_ltv", "mandate.underwriting.debt.sizing_dscr",
                "mandate.underwriting.debt.margin"} <= dscr_inputs
        exit_inputs = {d["input"] for d in r["metrics"]["exit_yield"]["depends_on"]}
        assert {"deal.completion_year", "mandate.underwriting.market_view.exit_age_premium_bps",
                "deal.price_aed"} <= exit_inputs

    def test_result_is_json_serialisable(self, jvc_deal, mandate, market):
        json.dumps(underwrite(jvc_deal, mandate, market), allow_nan=False)


class TestWalkAway:
    def test_boundary_meets_target_unlevered_irr(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        price = v(r, "walk_away_price_aed")
        assert price is not None and price % 10_000 == 0
        target = mandate["buy_box"]["soft"]["target_unlevered_irr"]
        at = underwrite({**jvc_deal, "price_aed": price}, mandate, market)
        above = underwrite({**jvc_deal, "price_aed": price + 10_000}, mandate, market)
        assert v(at, "unlevered_irr_pre_tax") >= target > v(above, "unlevered_irr_pre_tax")
        assert r["walk_away"]["binding_constraint"] == "unlevered_irr"
        assert r["walk_away"]["unlevered_irr_at_price"]["value"] == pytest.approx(target, abs=2e-4)
        # Debt is re-sized at the walk-away price.
        assert r["walk_away"]["loan_at_price"]["value"] == pytest.approx(v(at, "loan_aed"))

    def test_walk_away_does_not_depend_on_asking_price(self, jvc_deal, mandate, market):
        a = v(underwrite(jvc_deal, mandate, market), "walk_away_price_aed")
        b = v(underwrite({**jvc_deal, "price_aed": 90_000_000}, mandate, market), "walk_away_price_aed")
        assert a == b

    def test_names_the_assumption_that_moves_it_most(self, jvc_deal, mandate, market):
        wa = underwrite(jvc_deal, mandate, market)["walk_away"]
        cases = wa["sensitivity"]["cases"]
        assert [(c["assumption"], c["case"]) for c in cases] == [
            ("exit_yield", "-50 bps"), ("exit_yield", "+50 bps"),
            ("reference_rent_path", "-5%"), ("reference_rent_path", "+5%")]
        base = wa["price_aed"]["value"]
        assert cases[0]["price_aed"] > base > cases[1]["price_aed"]
        assert cases[3]["price_aed"] > base > cases[2]["price_aed"]
        swings = {}
        for c in cases:
            assert c["delta_aed"] == c["price_aed"] - base
            swings[c["assumption"]] = max(swings.get(c["assumption"], 0), abs(c["delta_aed"]))
        assert wa["most_sensitive_assumption"] == max(swings, key=swings.get)
        assert wa["largest_swing_aed"]["value"] == max(swings.values())


class TestDebtSizing:
    def test_ltv_binds_hand_calculated(self, test_mandate, test_market):
        # Price 500k: 45% LTV = 225,000; NOI 72,389 would support 476,966 at 1.40x, so LTV binds.
        r = underwrite(single_unit_deal(price=500_000.0), test_mandate, test_market)
        assert r["debt"]["sizing_constraint"] == "ltv"
        assert v(r, "loan_aed") == pytest.approx(225_000.0)
        # 15-year annuity at 6.80%: loan constant 0.1084117; debt service 24,392.64.
        assert v(r, "annual_debt_service_aed") == pytest.approx(225_000 * 0.10841173618856524)
        a = r["acquisition_costs"]
        assert a["transfer_costs"]["value"] == pytest.approx(20_000 + 580 + 4_200 + 10_000 + 500)   # 35,280
        assert a["mortgage_registration"]["value"] == pytest.approx(0.0025 * 225_000 + 290)         # 852.50
        assert v(r, "arrangement_fee_aed") == pytest.approx(1_687.5)                                 # 0.75%
        assert v(r, "equity_aed") == pytest.approx(500_000 + 35_280 + 852.5 + 1_687.5 - 225_000)
        assert v(r, "dscr_year1") > 1.40

    def test_dscr_binds_and_cover_is_exactly_the_sizing_dscr(self, test_mandate, test_market):
        r = underwrite(single_unit_deal(price=2_000_000.0), test_mandate, test_market)
        noi = v(r, "noi_year1")
        constant = annuity_payment(1.0, 0.068, 15)
        assert r["debt"]["sizing_constraint"] == "dscr"
        assert v(r, "loan_aed") == pytest.approx(noi / (1.40 * constant))
        assert v(r, "loan_aed") < 0.45 * 2_000_000
        assert v(r, "dscr_year1") == pytest.approx(1.40)
        assert r["debt"]["loan_at_max_ltv_aed"]["value"] == pytest.approx(900_000)

    def test_amortisation_sensitivity(self, jvc_deal, mandate, market):
        r = underwrite(jvc_deal, mandate, market)
        cases = r["debt"]["amortisation_sensitivity"]["cases"]
        assert [c["amortisation_years"] for c in cases] == [15, 20]
        base, longer = cases
        assert base["loan_aed"] == pytest.approx(v(r, "loan_aed"))
        # A 20-year term has a lower constant, so DSCR-sized debt is larger (or LTV binds).
        assert longer["loan_aed"] >= base["loan_aed"]
        assert longer["dscr_year1"] >= 1.40 - 1e-9
        assert r["debt"]["rate_note"] == mandate["underwriting"]["debt"]["rate_note"]
        assert r["metrics"]["interest_rate"]["note"] == mandate["underwriting"]["debt"]["rate_note"]


class TestExitYieldRule:
    def test_area_view_when_entry_is_lower(self, test_mandate, test_market):
        # Entry 72,389 / 1m = 7.24% < Testville 7.50%: exit = 7.50% + 25 bps, no age premium.
        r = underwrite(single_unit_deal(), test_mandate, test_market)
        ex = r["exit"]
        assert ex["base_source"] == "area_house_view" and ex["age_premium_bps"] == 0
        assert ex["exit_yield"]["value"] == pytest.approx(0.0775)
        assert ex["building_age_at_exit"] == 2032 - 2020

    def test_never_exit_below_entry(self, test_mandate, test_market):
        # At 800k the entry yield is 9.05%: exit = 9.05% + 25 bps.
        r = underwrite(single_unit_deal(price=800_000.0), test_mandate, test_market)
        entry = v(r, "noi_year1") / 800_000
        assert r["exit"]["base_source"] == "entry_yield"
        assert v(r, "exit_yield") == pytest.approx(entry + 0.0025)
        assert v(r, "entry_yield_on_price") == pytest.approx(entry)
        assert r["exit"]["summary"].startswith(f"Buy at {entry:.2%}")

    @pytest.mark.parametrize("year, premium", [(2012, 25), (2013, 0), (None, 25)])
    def test_age_premium_from_20_years_at_exit(self, test_mandate, test_market, year, premium):
        deal = single_unit_deal()
        deal["completion_year"] = year
        if year is None:
            del deal["completion_year"]
        r = underwrite(deal, test_mandate, test_market)
        assert r["exit"]["age_premium_bps"] == premium
        assert v(r, "exit_yield") == pytest.approx(0.075 + (25 + premium) / 10_000)
        assert any("exit age premium" in w for w in r["warnings"]) == (year is None)


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


def test_acquisition_costs_match_cost_function(test_mandate, test_market):
    r = underwrite(single_unit_deal(price=50_000_000.0), test_mandate, test_market)
    loan = v(r, "loan_aed")
    expected = acquisition_costs(50_000_000.0, loan, mandate_acquisition_rates(test_mandate))
    for k in ("dld_transfer_fee", "broker_fee", "mortgage_registration", "transfer_costs", "total"):
        assert r["acquisition_costs"][k]["value"] == pytest.approx(expected[k])
    assert r["acquisition_costs"]["transfer_costs"]["value"] == pytest.approx(3_054_780.0)


def test_legal_case_is_not_occupied_and_relets_after_six_months(test_mandate, test_market):
    deal = single_unit_deal()
    deal["units"][0]["status"] = "legal_case"
    r = underwrite(deal, test_mandate, test_market)
    assert v(r, "occupancy_by_units") == 0.0
    assert v(r, "in_place_rent_aed") == 0.0
    # No rent until resolved: re-let at the 100,000 reference after 6 months.
    assert v(r, "gross_rental_income_year1") == pytest.approx(50_000)


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
