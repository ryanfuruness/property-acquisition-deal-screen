"""Unit-level lease model.

Each unit is simulated month by month over the hold plus one forward year (the exit
year's NOI). Results are summed into annual periods by the caller, so a lease that
expires mid-year is prorated by month.

Renewal versus turnover is an *expected-value blend*, not a random draw: at each
expiry the next lease earns ``p x renewal rent + (1 - p) x turnover rent``, and the
turnover share also bears the downtime and the leasing fee. This is the usual
"market leasing assumption" treatment in institutional cash-flow software, and it
keeps the engine deterministic. The blended rent then becomes the unit's current rent
for the next expiry. Every lease after an expiry runs 12 months from that expiry.

Rent rules at expiry (data/mandate.yaml ``underwriting.rera`` and docs/DESIGN.md):

* Under-rented (current < market): rent rises by the RERA band for the gap
  ``(market - current) / market``, capped at market. No increase is allowed for an
  expiry inside the notice window after the analysis starts, because the 90-day notice
  could not have been served.
* Over-rented (current > market): rent resets to market (landlords cut to retain
  tenants in a falling market).
* Turnover: re-let at market after the downtime, with a leasing fee of
  ``leasing_fee_months`` of the new rent, charged in the month of re-letting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

OCCUPIED_STATUSES = ("occupied", "under_renewal", "notice_served")
NON_INCOME_STATUSES = ("vacant", "legal_case")
UNIT_STATUSES = OCCUPIED_STATUSES + NON_INCOME_STATUSES
# Physically let, for rent-roll statistics: a legal-case tenant is in the unit under a
# contract even though the cash flow assumes its rent is not collected.
PHYSICALLY_LET_STATUSES = OCCUPIED_STATUSES + ("legal_case",)


@dataclass(frozen=True)
class LeaseAssumptions:
    """Leasing assumptions, all taken from the mandate."""

    renewal_probability: float
    downtime_months: float
    leasing_fee_months: float
    rera_bands: tuple[tuple[float, float], ...]   # (below_index_up_to, max_increase), ascending
    notice_months: float                          # no increase on expiries before this month
    months: int                                   # length of the simulation

    def __post_init__(self) -> None:
        if not 0.0 <= self.renewal_probability <= 1.0:
            raise ValueError("renewal_probability must be between 0 and 1")
        if not 0.0 <= self.downtime_months < 12.0:
            raise ValueError("downtime_months must be in [0, 12)")
        if self.leasing_fee_months < 0:
            raise ValueError("leasing_fee_months must be non-negative")


@dataclass(frozen=True)
class UnitLease:
    """One rent-roll unit after normalisation."""

    unit: str
    unit_type: str
    area_sqft: float
    status: str
    annual_rent_aed: float | None
    expiry_month: int | None          # analysis month in which the lease rolls; None = no lease
    available_month: int = 0          # vacant units: first month the unit can be let


@dataclass
class UnitSchedule:
    """Monthly results for one unit."""

    rent: list[float]                 # expected rent earned each month
    potential_rent: list[float]       # expected rent if there were no downtime
    leasing_fees: list[float]         # expected leasing fee each month
    events: list[dict] = field(default_factory=list)


def rera_max_increase(current_rent: float, market_rent: float,
                      bands: Sequence[tuple[float, float]]) -> float:
    """Maximum permitted increase (a fraction of current rent) at renewal.

    ``bands`` is a list of ``(below_index_up_to, max_increase)`` pairs in ascending
    order. The gap below the index is ``(market - current) / market``. Each upper bound
    is inclusive, so a rent exactly 10% below the index falls in the first band.
    A rent at or above the index gets no increase.
    """
    if market_rent <= 0 or current_rent >= market_rent:
        return 0.0
    gap = (market_rent - current_rent) / market_rent
    for upper, max_increase in bands:
        if gap <= upper + 1e-12:
            return max_increase
    return bands[-1][1]


def renewal_rent(current_rent: float, market_rent: float,
                 bands: Sequence[tuple[float, float]],
                 increase_allowed: bool = True) -> tuple[float, str]:
    """Rent on renewal and the rule that set it.

    Rules: ``over_rented_reset_to_market``, ``at_market``, ``notice_window_no_increase``
    or ``rera_band_<n>pct`` (n = the permitted increase in percent).
    """
    if current_rent > market_rent:
        return market_rent, "over_rented_reset_to_market"
    if current_rent == market_rent:
        return current_rent, "at_market"
    if not increase_allowed:
        return current_rent, "notice_window_no_increase"
    increase = rera_max_increase(current_rent, market_rent, bands)
    new_rent = min(market_rent, current_rent * (1.0 + increase))
    return new_rent, f"rera_band_{round(increase * 100)}pct"


def _occupied_fraction(month_offset: int, downtime: float) -> float:
    """Share of month ``month_offset`` (0 = expiry month) let after a re-let with downtime."""
    return min(1.0, max(0.0, month_offset + 1 - downtime))


def model_unit(unit: UnitLease, market_rent_by_year: Sequence[float],
               a: LeaseAssumptions) -> UnitSchedule:
    """Simulate one unit's expected rent month by month.

    ``market_rent_by_year[y]`` is the unit's annual market rent for leases that start
    in analysis year ``y`` (0-based). It already includes the house-view growth path
    and any sensitivity shift.
    """
    n = a.months
    rent = [0.0] * n
    potential = [0.0] * n
    fees = [0.0] * n
    events: list[dict] = []

    def market_at(month: int) -> float:
        return market_rent_by_year[min(month // 12, len(market_rent_by_year) - 1)]

    def let_new(start: int, new_rent: float, share: float) -> None:
        """Add a re-let at market for ``share`` of the unit, from month ``start``."""
        for k in range(12):
            m = start + k
            if m >= n:
                break
            rent[m] += share * new_rent / 12.0 * _occupied_fraction(k, a.downtime_months)
            potential[m] += share * new_rent / 12.0
        fee_month = start + int(math.floor(a.downtime_months))
        if fee_month < n:
            fees[fee_month] += share * a.leasing_fee_months * new_rent / 12.0

    if unit.status in NON_INCOME_STATUSES:
        # Vacant (from the start, or from a master-lease reversion): lease up at market
        # after the downtime, then roll like any other lease.
        start = unit.available_month
        next_expiry: int | None = None
        current = 0.0
        if start < n:
            current = market_at(start)
            let_new(start, current, 1.0)
            events.append({"month": start, "type": "lease_up", "market_rent": current,
                           "new_rent": current})
            next_expiry = start + 12
        first_renewal_probability = a.renewal_probability
    else:
        current = float(unit.annual_rent_aed or 0.0)
        next_expiry = unit.expiry_month
        stop = n if next_expiry is None else min(next_expiry, n)
        for m in range(stop):
            rent[m] = current / 12.0
            potential[m] = current / 12.0
        first_renewal_probability = 0.0 if unit.status == "notice_served" else a.renewal_probability

    probability = first_renewal_probability
    while next_expiry is not None and next_expiry < n:
        e = next_expiry
        market = market_at(e)
        increase_allowed = e >= a.notice_months
        r_renew, rule = renewal_rent(current, market, a.rera_bands, increase_allowed)
        # Renewal share: earns the renewal rent from the expiry month with no downtime.
        for k in range(12):
            m = e + k
            if m >= n:
                break
            rent[m] += probability * r_renew / 12.0
            potential[m] += probability * r_renew / 12.0
        # Turnover share: re-lets at market after the downtime.
        let_new(e, market, 1.0 - probability)
        blended = probability * r_renew + (1.0 - probability) * market
        events.append({
            "month": e, "type": "expiry", "current_rent": current, "market_rent": market,
            "renewal_rent": r_renew, "renewal_rule": rule, "renewal_probability": probability,
            "turnover_rent": market, "blended_rent": blended,
        })
        current = blended
        next_expiry = e + 12
        probability = a.renewal_probability
    return UnitSchedule(rent=rent, potential_rent=potential, leasing_fees=fees, events=events)
