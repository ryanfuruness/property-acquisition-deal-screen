"""Recomputing an OM's stated yield on its own basis and on a buyer's basis."""

import pytest

from engine import recompute_stated_yield, underwrite
from engine.finance import annuity_payment
from engine.yields import normalise_basis


def test_gross_on_price_reproduced_and_corrected(mandate):
    # OM: AED 4.0m rent on AED 50m = 8.0% "net". Buyer NOI 3.0m. The loan is sized as the
    # engine sizes it: 3.0m / (1.40 x 0.1084117) = 19.77m (below 45% LTV = 22.5m), so
    # acquisition costs = 3,054,780 transfer costs + 0.25% x loan + 290.
    out = recompute_stated_yield(4_000_000, 50_000_000, {"measure": "net", "on": "asking_price"},
                                 stated_yield=0.08, noi_year1=3_000_000, mandate=mandate)
    loan = 3_000_000 / (1.40 * annuity_payment(1.0, 0.068, 15))
    costs = 3_054_780 + 0.0025 * loan + 290
    assert out["reproduced_on_om_basis"] == pytest.approx(0.08)
    assert out["reproduces_stated"] is True
    assert out["acquisition_costs_aed"] == pytest.approx(costs)
    assert out["buyer_net_on_total_cost"] == pytest.approx(3_000_000 / (50_000_000 + costs))
    assert out["buyer_net_on_price"] == pytest.approx(0.06)
    assert out["gap_vs_stated"] == pytest.approx(3_000_000 / (50_000_000 + costs) - 0.08)
    assert out["summary"].startswith("The OM says 8.00% (net on asking price)")
    assert f"{3_000_000 / (50_000_000 + costs):.2%}" in out["summary"]


def test_om_figure_that_does_not_reproduce(mandate):
    out = recompute_stated_yield(4_000_000, 50_000_000, "gross on price", stated_yield=0.09,
                                 mandate=mandate)
    assert out["reproduces_stated"] is False


def test_total_cost_basis(mandate):
    out = recompute_stated_yield(4_000_000, 50_000_000, {"measure": "gross", "on": "total_cost"},
                                 acquisition_costs_aed=3_000_000)
    assert out["reproduced_on_om_basis"] == pytest.approx(4_000_000 / 53_000_000)


def test_unstated_denominator_assumed_asking_price():
    b = normalise_basis({"measure": "unstated", "on": "unstated"})
    assert b["on"] == "asking_price" and b["assumed"] is True


def test_underwrite_includes_om_check(jvc_deal, mandate, market):
    r = underwrite(jvc_deal, mandate, market)
    chk = r["om_yield_check"]
    assert chk["stated_income_on_price"]["value"] == pytest.approx(4_300_000 / 47_000_000)
    assert chk["buyer_net_on_total_cost"]["value"] == pytest.approx(
        r["metrics"]["going_in_net_yield_on_cost"]["value"])
    assert chk["reproduces_stated"] is False    # 4.3m / 47m = 9.15%, the OM prints 8.27%
