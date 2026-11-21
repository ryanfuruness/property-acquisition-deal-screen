"""Mandate fit: one case per verdict rule, unknowns, and the record shape."""

import copy

import pytest

from engine import mandate_fit, underwrite

GOOD_FACTS = {
    "asset_type": "residential_building", "area": "JVC", "title_type": "freehold_single_title",
    "unit_count": 60, "price_aed": 40_000_000, "completion_year": 2016,
    "master_lease_related_party": False,
}
GOOD_METRICS = {
    "dscr_year1": 1.45, "going_in_net_yield_on_cost": 0.07, "levered_irr_pre_tax": 0.14,
    "levered_equity_multiple_pre_tax": 1.7, "occupancy_by_units": 0.95,
    "max_expiry_share_quarter": 0.30, "over_rent_share_of_income": 0.10,
}


def uw(**overrides):
    metrics = {**GOOD_METRICS, **overrides}
    return {"metrics": {k: {"value": val, "unit": "", "depends_on": []} for k, val in metrics.items()}}


def by_name(fit):
    return {t["name"]: t for t in fit["tests"]}


def test_pursue_when_everything_passes(mandate):
    fit = mandate_fit(GOOD_FACTS, uw(), mandate)
    assert fit["verdict"] == "Pursue"
    assert fit["hard_fails"] == fit["soft_fails"] == fit["unknown"] == 0
    assert len(fit["tests"]) == 16


def test_needs_work_on_one_soft_fail(mandate):
    target = mandate["buy_box"]["soft"]["target_levered_irr"]
    fit = mandate_fit(GOOD_FACTS, uw(levered_irr_pre_tax=target - 0.02), mandate)
    assert fit["verdict"] == "Needs work"
    t = by_name(fit)["target_levered_irr"]
    assert t == {"name": "target_levered_irr", "kind": "soft", "threshold": target, "actual": target - 0.02,
                 "passed": False, "status": "fail",
                 "reason": f"Levered IRR (pre-tax) {target - 0.02:.2%} misses the at least {target:.2%} requirement.",
                 "source": "engine"}


@pytest.mark.parametrize("facts, metrics, failed", [
    ({"area": "Dubai Marina"}, {}, "areas"),
    ({"title_type": "freehold_strata"}, {}, "title"),
    ({"unit_count": 20}, {}, "min_units"),
    ({"unit_count": 300}, {}, "max_units"),
    ({"price_aed": 25_000_000}, {}, "min_price_aed"),
    ({"price_aed": 250_000_000}, {}, "max_price_aed"),
    ({"completion_year": 2005}, {}, "min_completion_year"),
    ({"master_lease_related_party": True}, {}, "no_master_lease_to_related_party"),
    ({}, {"dscr_year1": 1.10}, "min_dscr_year1"),
    ({"asset_type": "hotel"}, {}, "asset_type"),
])
def test_pass_on_any_hard_fail(mandate, facts, metrics, failed):
    fit = mandate_fit({**GOOD_FACTS, **facts}, uw(**metrics), mandate)
    assert fit["verdict"] == "Pass"
    assert by_name(fit)[failed]["status"] == "fail"
    assert fit["hard_fails"] == 1


def test_unknown_fact_is_a_soft_fail_never_a_pass(mandate):
    facts = {**GOOD_FACTS, "completion_year": None}
    fit = mandate_fit(facts, uw(), mandate)
    t = by_name(fit)["min_completion_year"]
    assert t["status"] == "unknown" and t["passed"] is None and t["kind"] == "hard"
    assert fit["verdict"] == "Needs work"
    assert fit["soft_fails"] == 1 and fit["hard_fails"] == 0


def test_unknown_engine_metric_is_a_soft_fail(mandate):
    fit = mandate_fit(GOOD_FACTS, uw(levered_irr_pre_tax=None), mandate)
    assert by_name(fit)["target_levered_irr"]["status"] == "unknown"
    assert fit["verdict"] == "Needs work"


def test_no_underwriting_result_makes_engine_tests_unknown(mandate):
    fit = mandate_fit(GOOD_FACTS, None, mandate)
    unknown = {t["name"] for t in fit["tests"] if t["status"] == "unknown"}
    assert "min_dscr_year1" in unknown and "target_levered_irr" in unknown
    assert fit["verdict"] == "Needs work"
    # An out-of-area deal that cannot be underwritten still gets a clear Pass.
    assert mandate_fit({**GOOD_FACTS, "area": "Dubai Marina"}, None, mandate)["verdict"] == "Pass"


def test_hard_fail_beats_soft_fails(mandate):
    fit = mandate_fit({**GOOD_FACTS, "area": "Dubai Marina"}, uw(levered_irr_pre_tax=0.05), mandate)
    assert fit["verdict"] == "Pass"


def test_boundary_values_pass(mandate):
    hard, soft = mandate["buy_box"]["hard"], mandate["buy_box"]["soft"]
    fit = mandate_fit({**GOOD_FACTS, "unit_count": hard["min_units"], "price_aed": hard["min_price_aed"],
                       "completion_year": hard["min_completion_year"]},
                      uw(dscr_year1=hard["min_dscr_year1"],
                         max_expiry_share_quarter=soft["max_lease_expiry_share_in_any_quarter"],
                         levered_irr_pre_tax=soft["target_levered_irr"],
                         levered_equity_multiple_pre_tax=soft["target_equity_multiple"],
                         going_in_net_yield_on_cost=soft["min_going_in_net_yield_on_cost"],
                         occupancy_by_units=soft["min_occupancy"],
                         over_rent_share_of_income=soft["max_over_rent_share_of_income"]), mandate)
    assert fit["verdict"] == "Pursue"


def test_verdict_rules_come_from_the_mandate(mandate):
    m = copy.deepcopy(mandate)
    m["verdict_rules"]["pursue_if_soft_fails_at_most"] = 1
    one_soft_fail = uw(levered_irr_pre_tax=m["buy_box"]["soft"]["target_levered_irr"] - 0.02)
    assert mandate_fit(GOOD_FACTS, one_soft_fail, mandate)["verdict"] == "Needs work"
    assert mandate_fit(GOOD_FACTS, one_soft_fail, m)["verdict"] == "Pursue"


def test_unimplemented_mandate_filter_is_an_error(mandate):
    m = copy.deepcopy(mandate)
    m["buy_box"]["soft"]["max_service_charge_psf"] = 15
    with pytest.raises(ValueError, match="max_service_charge_psf"):
        mandate_fit(GOOD_FACTS, uw(), m)


def test_with_real_underwriting_and_fallback_facts(jvc_deal, mandate, market):
    r = underwrite(jvc_deal, mandate, market)
    fit = mandate_fit({"area": "JVC"}, r, mandate)
    t = by_name(fit)
    assert t["min_units"]["actual"] == 60 and t["min_units"]["source"] == "engine"
    assert t["min_price_aed"]["actual"] == 47_000_000
