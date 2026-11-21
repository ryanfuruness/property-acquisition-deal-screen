"""Deterministic underwriting engine for the Dubai residential-building deal screen.

No LLM calls, no network, no randomness: the same inputs always give the same result.
Every rule and number comes from ``data/mandate.yaml`` and ``data/market/areas.yaml``,
passed in as dicts. See engine/README.md for the input and result schemas.

Public API::

    from engine import underwrite, mandate_fit, load_mandate, load_market
    mandate, market = load_mandate(), load_market()
    result = underwrite(deal_inputs, mandate, market)
    fit = mandate_fit(deal_facts, result, mandate)
"""

from .inputs import DealInputError, MarketDataError
from .loaders import load_mandate, load_market
from .mandate_fit import mandate_fit
from .underwrite import ENGINE_VERSION, underwrite
from .yields import recompute_stated_yield

__all__ = [
    "underwrite", "mandate_fit", "recompute_stated_yield", "load_mandate", "load_market",
    "DealInputError", "MarketDataError", "ENGINE_VERSION",
]
