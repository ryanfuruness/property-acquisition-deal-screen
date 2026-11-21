"""Recomputing an OM's stated yield on its own basis and on a buyer's basis."""

import pytest

from engine import recompute_stated_yield, underwrite
from engine.yields import normalise_basis


def test_gross_on_price_reproduced_and_corrected(mandate):
    # OM: AED 4.0m rent on AED 50m = 8.0% "net". Buyer NOI 3.0m on 53,111,320 total cost
    # (acquisition costs at the mandate's 45% LTV: loan 22.5m, mortgage registration 56,540).
    out = recompute_stated_yield(4_000_000, 50_000_000, {"measure": "net", "on": "asking_price"},
                                 stated_yield=0.08, noi_year1=3_000_000, mandate=mandate)
    assert out["reproduced_on_om_basis"] == pytest.approx(0.08)
    assert out["reproduces_stated"] is True
    assert out["acquisition_costs_aed"] == pytest.approx(3_111_320.0)
    assert out["buyer_net_on_total_cost"] == pytest.approx(3_000_000 / 53_111_320)
    assert out["buyer_net_on_price"] == pytest.approx(0.06)
    assert out["gap_vs_stated"] == pytest.approx(3_000_000 / 53_111_320 - 0.08)
    assert out["summary"].startswith("The OM says 8.00% (net on asking price)")
    assert "5.65%" in out["summary"]


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
