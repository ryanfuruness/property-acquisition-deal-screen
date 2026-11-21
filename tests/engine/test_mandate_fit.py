"""Mandate fit: one case per verdict rule, blocked hard tests, stop reason and the record shape.

Thresholds are read from the mandate, so the tests follow the mandate as it is re-tuned.
"""

import copy

import pytest

from engine import mandate_fit, underwrite

GOOD_FACTS = {
    "asset_type": "residential_building", "area": "JVC", "title_type": "freehold_single_title",
    "unit_count": 60, "price_aed": 40_000_000, "completion_year": 2016,
    "master_lease_related_party": False,
}
GOOD_METRICS = {
    "going_in_net_yield_on_cost": 0.07, "unlevered_irr_pre_tax": 0.09,
    "unlevered_equity_multiple_pre_tax": 1.5, "occupancy_by_units": 0.95,
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
    assert fit["blocked_on"] == [] and fit["stop_reason"] is None
    hard, soft = mandate["buy_box"]["hard"], mandate["buy_box"]["soft"]
    # One test per filter; over_rent_threshold is a parameter of the over-rent test.
    assert len(fit["tests"]) == len(hard) + len(soft) - 1
    assert all(t["decisive"] for t in fit["tests"])


def test_needs_work_on_one_soft_fail(mandate):
    target = mandate["buy_box"]["soft"]["target_unlevered_irr"]
    fit = mandate_fit(GOOD_FACTS, uw(unlevered_irr_pre_tax=target - 0.02), mandate)
    assert fit["verdict"] == "Needs work"
    t = by_name(fit)["target_unlevered_irr"]
    assert t == {"name": "target_unlevered_irr", "kind": "soft", "threshold": target, "actual": target - 0.02,
                 "passed": False, "status": "fail",
                 "reason": f"Unlevered IRR (pre-tax) {target - 0.02:.2%} misses the at least {target:.2%} requirement.",
                 "source": "engine", "decisive": True}


@pytest.mark.parametrize("facts, failed", [
    ({"area": "Dubai Marina"}, "areas"),
    ({"area": "Al Barsha"}, "areas"),                    # only Al Barsha South is in the mandate
    ({"title_type": "freehold_strata"}, "title"),
    ({"unit_count": 20}, "min_units"),
    ({"unit_count": 300}, "max_units"),
    ({"price_aed": 25_000_000}, "min_price_aed"),
    ({"price_aed": 250_000_000}, "max_price_aed"),
    ({"completion_year": 2005}, "min_completion_year"),
    ({"master_lease_related_party": True}, "no_master_lease_to_related_party"),
    ({"asset_type": "hotel"}, "asset_type"),
])
def test_decline_on_any_hard_fail(mandate, facts, failed):
    fit = mandate_fit({**GOOD_FACTS, **facts}, uw(), mandate)
    assert fit["verdict"] == "Decline"
    assert by_name(fit)[failed]["status"] == "fail"
    assert fit["hard_fails"] == 1
    assert failed in fit["stop_reason"] and "not decisive" in fit["stop_reason"]
    assert all(not t["decisive"] for t in fit["tests"] if t["kind"] == "soft")
    assert all(t["decisive"] for t in fit["tests"] if t["kind"] == "hard")


def test_mixed_use_and_al_barsha_south_are_in_mandate(mandate):
    fit = mandate_fit({**GOOD_FACTS, "asset_type": "mixed_use_residential", "area": "Al Barsha South"},
                      uw(), mandate)
    assert fit["verdict"] == "Pursue"


def test_unknown_hard_fact_blocks_rather_than_counting_as_a_soft_miss(mandate):
    fit = mandate_fit({**GOOD_FACTS, "title_type": None}, uw(), mandate)
    t = by_name(fit)["title"]
    assert t["status"] == "unknown" and t["passed"] is None and t["kind"] == "hard"
    assert "blocks the verdict" in t["reason"]
    assert fit["verdict"] == "Needs work"
    assert fit["blocked_on"] == ["title"]
    assert fit["soft_fails"] == 0 and fit["hard_fails"] == 0 and fit["unknown"] == 1
    assert fit["stop_reason"] is None


def test_hard_fail_beats_blocked_and_soft_misses(mandate):
    fit = mandate_fit({**GOOD_FACTS, "area": "Dubai Marina", "title_type": None},
                      uw(unlevered_irr_pre_tax=0.01), mandate)
    assert fit["verdict"] == "Decline"
    assert fit["blocked_on"] == ["title"]          # still reported
    assert by_name(fit)["target_unlevered_irr"]["decisive"] is False


def test_unknown_engine_metric_is_a_soft_miss(mandate):
    fit = mandate_fit(GOOD_FACTS, uw(unlevered_irr_pre_tax=None), mandate)
    assert by_name(fit)["target_unlevered_irr"]["status"] == "unknown"
    assert fit["verdict"] == "Needs work" and fit["soft_fails"] == 1 and fit["blocked_on"] == []


def test_no_underwriting_result_makes_engine_tests_unknown(mandate):
    fit = mandate_fit(GOOD_FACTS, None, mandate)
    unknown = {t["name"] for t in fit["tests"] if t["status"] == "unknown"}
    assert {"target_unlevered_irr", "target_unlevered_equity_multiple"} <= unknown
    assert fit["verdict"] == "Needs work"
    # An out-of-area deal that cannot be underwritten still gets a clear Decline.
    assert mandate_fit({**GOOD_FACTS, "area": "Dubai Marina"}, None, mandate)["verdict"] == "Decline"


def test_boundary_values_pass(mandate):
    hard, soft = mandate["buy_box"]["hard"], mandate["buy_box"]["soft"]
    fit = mandate_fit({**GOOD_FACTS, "unit_count": hard["min_units"], "price_aed": hard["min_price_aed"],
                       "completion_year": hard["min_completion_year"]},
                      uw(max_expiry_share_quarter=soft["max_lease_expiry_share_in_any_quarter"],
                         unlevered_irr_pre_tax=soft["target_unlevered_irr"],
                         unlevered_equity_multiple_pre_tax=soft["target_unlevered_equity_multiple"],
                         going_in_net_yield_on_cost=soft["min_going_in_net_yield_on_cost"],
                         occupancy_by_units=soft["min_occupancy"],
                         over_rent_share_of_income=soft["max_over_rent_share_of_income"]), mandate)
    assert fit["verdict"] == "Pursue"


def test_verdict_rules_come_from_the_mandate(mandate):
    m = copy.deepcopy(mandate)
    m["verdict_rules"]["pursue_if_soft_fails_at_most"] = 1
    one_soft_miss = uw(unlevered_irr_pre_tax=m["buy_box"]["soft"]["target_unlevered_irr"] - 0.02)
    assert mandate_fit(GOOD_FACTS, one_soft_miss, mandate)["verdict"] == "Needs work"
    assert mandate_fit(GOOD_FACTS, one_soft_miss, m)["verdict"] == "Pursue"


def test_optional_dscr_filter_still_supported(mandate):
    m = copy.deepcopy(mandate)
    m["buy_box"]["hard"]["min_dscr_year1"] = 1.30
    fit = mandate_fit(GOOD_FACTS, uw(dscr_year1=1.10), m)
    assert fit["verdict"] == "Decline" and by_name(fit)["min_dscr_year1"]["status"] == "fail"


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
    assert set(fit["blocked_on"]) == {"asset_type", "title", "min_completion_year",
                                      "no_master_lease_to_related_party"}
