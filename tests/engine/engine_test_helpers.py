"""Builders for small hand-calculable deals, shared by the engine tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def all_opex_stated(amount_for_maintenance: float = 5000.0) -> dict:
    """An operating statement that states every category, so no defaults apply."""
    cats = ["service_charge", "district_cooling", "utilities_common", "maintenance_repairs",
            "insurance", "security_cleaning", "marketing_leasing", "admin_other", "sinking_fund"]
    opex = {c: 0.0 for c in cats}
    opex["maintenance_repairs"] = amount_for_maintenance
    return opex


def single_unit_deal(rent: float = 85000.0, lease_end: str = "2027-06-30",
                     status: str = "occupied", price: float = 1_000_000.0) -> dict:
    """One 1,000 sqft 1BR in Testville (market rent AED 100,000 a year)."""
    return {
        "price_aed": price, "area": "Testville", "nsa_sqft": 1000, "bua_sqft": 1250,
        "units": [{"unit": "A1", "unit_type": "1br", "area_sqft": 1000, "status": status,
                   "annual_rent_aed": rent if status != "vacant" else None,
                   "lease_end": lease_end if status != "vacant" else None}],
        "opex_aed": all_opex_stated(),
        "other_income_aed": 0.0,
        "chiller_landlord_pays": False,
        "completion_year": 2020,          # 7 years old at the start: no exit age premium, sinking fund x1.0
    }
