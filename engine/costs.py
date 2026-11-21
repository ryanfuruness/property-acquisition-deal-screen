"""Acquisition cost arithmetic (rates come from ``mandate.underwriting.acquisition_costs``)."""

from __future__ import annotations


def acquisition_costs(price: float, loan: float, rates: dict[str, float]) -> dict[str, float]:
    """Buyer's acquisition costs on a purchase at ``price`` financed with ``loan``.

    ``rates`` uses the mandate's keys. Returns each line plus two subtotals:
    ``transfer_costs`` (what any buyer pays, used for unlevered returns) and
    ``total`` (adds mortgage registration on the loan; the mandate lists it with
    the acquisition costs, so yield on total cost uses this figure).
    """
    dld = rates["dld_transfer_fee_pct"] * price
    broker = rates["broker_fee_pct"] * price
    broker_vat = broker * rates["broker_fee_vat_pct"]
    mortgage = (rates["mortgage_registration_pct"] * loan
                + (rates["mortgage_registration_admin_aed"] if loan > 0 else 0.0))
    transfer = dld + rates["dld_admin_aed"] + rates["trustee_fee_aed"] + broker + broker_vat
    return {
        "dld_transfer_fee": dld,
        "dld_admin": rates["dld_admin_aed"],
        "trustee_fee": rates["trustee_fee_aed"],
        "broker_fee": broker,
        "broker_fee_vat": broker_vat,
        "mortgage_registration": mortgage,
        "transfer_costs": transfer,
        "total": transfer + mortgage,
    }


def mandate_acquisition_rates(mandate: dict) -> dict[str, float]:
    """The acquisition-cost rates block of a mandate, as floats."""
    block = mandate["underwriting"]["acquisition_costs"]
    return {k: float(v) for k, v in block.items()}
