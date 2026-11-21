"""Recompute an offering memorandum's stated yield on its own basis and on a buyer's basis.

Brokers usually quote "ROI" or "yield" as annual rent divided by asking price, with no
costs deducted, sometimes calling it "net". The screen shows both what the OM's number
means and what the same building yields to a buyer: Year-1 NOI on price plus
acquisition costs ("the OM says X; on a buyer's basis it is Y").
"""

from __future__ import annotations

from typing import Any

from .costs import acquisition_costs, mandate_acquisition_rates

MEASURES = ("gross", "net", "unstated")
DENOMINATORS = ("asking_price", "total_cost", "unstated")
# The OM's figure is taken as reproduced if our recomputation is within this many
# percentage points (OMs usually round yields to one decimal place).
DEFAULT_TOLERANCE = 0.0005


def normalise_basis(basis: Any) -> dict[str, Any]:
    """Accept ``{"measure", "on"}`` or a string such as ``"gross_on_price"``.

    Returns ``{"measure", "on", "assumed"}``. An unstated denominator is assumed to be
    the asking price (the broker convention) and ``assumed`` is set.
    """
    if isinstance(basis, dict):
        measure = str(basis.get("measure") or "unstated").lower()
        on = str(basis.get("on") or "unstated").lower()
    elif isinstance(basis, str):
        text = basis.lower().replace("-", "_").replace(" ", "_")
        measure = "gross" if "gross" in text else "net" if "net" in text else "unstated"
        on = "total_cost" if ("cost" in text) else "asking_price" if "price" in text else "unstated"
    elif basis is None:
        measure, on = "unstated", "unstated"
    else:
        raise ValueError(f"yield basis must be a dict or string, got {basis!r}")
    if on in ("price", "asking"):
        on = "asking_price"
    if measure not in MEASURES or on not in DENOMINATORS:
        raise ValueError(f"unrecognised yield basis {basis!r}")
    assumed = on == "unstated"
    return {"measure": measure, "on": "asking_price" if assumed else on,
            "stated_on": on, "assumed": assumed}


def recompute_stated_yield(stated_income: float | None, price: float, basis: Any, *,
                           stated_yield: float | None = None,
                           noi_year1: float | None = None,
                           acquisition_costs_aed: float | None = None,
                           mandate: dict | None = None,
                           tolerance: float = DEFAULT_TOLERANCE) -> dict[str, Any]:
    """Reproduce an OM yield on the OM's own basis and give the buyer's-basis figure.

    Parameters
    ----------
    stated_income:
        The income the OM divides by (its "annual rental income", or its net income
        if the OM states one for a net yield). ``None`` if the OM gives none.
    price:
        Asking price in AED.
    basis:
        The OM's basis, ``{"measure": gross|net|unstated, "on": asking_price|total_cost|unstated}``
        or an equivalent string such as ``"gross_on_price"``.
    stated_yield:
        The yield printed in the OM, as a ratio (0.08 for 8%), if any.
    noi_year1:
        The engine's Year-1 NOI. Needed for the buyer's net yields.
    acquisition_costs_aed:
        Buyer's acquisition costs. If omitted and ``mandate`` is given they are
        computed from the mandate at its LTV.

    Returns a dict of plain values (ratios and AED) with a one-line ``summary``.
    """
    b = normalise_basis(basis)
    if acquisition_costs_aed is None and mandate is not None:
        loan = float(mandate["underwriting"]["debt"]["ltv"]) * price
        acquisition_costs_aed = acquisition_costs(price, loan, mandate_acquisition_rates(mandate))["total"]
    total_cost = price + acquisition_costs_aed if acquisition_costs_aed is not None else None

    def ratio(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return num / den

    om_denominator = price if b["on"] == "asking_price" else total_cost
    reproduced = ratio(stated_income, om_denominator)
    reproduces = (None if reproduced is None or stated_yield is None
                  else abs(reproduced - stated_yield) <= tolerance)
    out: dict[str, Any] = {
        "stated_yield": stated_yield,
        "om_basis": b,
        "stated_income_aed": stated_income,
        "price_aed": price,
        "acquisition_costs_aed": acquisition_costs_aed,
        "total_cost_aed": total_cost,
        "reproduced_on_om_basis": reproduced,
        "reproduces_stated": reproduces,
        "gross_on_price": ratio(stated_income, price),
        "gross_on_total_cost": ratio(stated_income, total_cost),
        "buyer_net_on_price": ratio(noi_year1, price),
        "buyer_net_on_total_cost": ratio(noi_year1, total_cost),
    }
    shown = stated_yield if stated_yield is not None else reproduced
    buyer = out["buyer_net_on_total_cost"]
    out["gap_vs_stated"] = None if shown is None or buyer is None else buyer - shown
    basis_text = f"{b['measure']} on {'asking price' if b['on'] == 'asking_price' else 'total cost'}"
    if b["assumed"]:
        basis_text += ", denominator assumed"
    if shown is None:
        out["summary"] = "The OM states no yield or income to recompute."
    elif buyer is None:
        out["summary"] = f"The OM says {shown:.2%} ({basis_text}); buyer's basis needs Year-1 NOI."
    else:
        out["summary"] = (f"The OM says {shown:.2%} ({basis_text}); on a buyer's basis "
                          f"(Year-1 NOI on price plus acquisition costs) it is {buyer:.2%}.")
    return out
