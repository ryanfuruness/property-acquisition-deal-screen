"""Shared fixtures for the engine tests."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine import load_mandate, load_market  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def mandate() -> dict:
    return load_mandate()


@pytest.fixture(scope="session")
def market() -> dict:
    return load_market()


@pytest.fixture
def jvc_deal() -> dict:
    with open(FIXTURES / "jvc_60_units.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def test_mandate(mandate) -> dict:
    """The real mandate with a flat market and certain renewal, for hand calculations.

    Adds a "Testville" area so tests can use round numbers (100 AED/sqft market rent).
    """
    m = copy.deepcopy(mandate)
    uw = m["underwriting"]
    uw["market_view"]["rent_growth_by_year"] = {"default": [0.0] * 6}
    uw["market_view"]["exit_net_yield_by_area"]["Testville"] = 0.075
    uw["operations"]["renewal_probability"] = 1.0
    return m


@pytest.fixture
def test_market(market) -> dict:
    k = copy.deepcopy(market)
    k["areas"]["Testville"] = {"market_rent_aed_psf_1br": 100, "sources": ["test"]}
    return k
