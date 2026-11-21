"""Unit-level lease model.

Each unit is simulated month by month over the hold plus one forward year (the exit
year's NOI). Results are summed into annual periods by the caller, so a lease that
expires mid-year is prorated by month.

**Reference rent.** Rents are compared with the *screen reference rent*: the area rent
per sq ft from ``data/market/areas.yaml`` x the unit-type factor x the unit area,
grown by the house-view path. It is a proxy for the RERA Smart Rental Index, which has
no bulk download; it is not the index, and nothing here claims a RERA figure for a
specific building.

**Renewal versus turnover** is an expected-value calculation, not a random draw. At each
expiry the unit's possible states (tenants paying different rents, with probability
weights) each either renew with probability ``p`` or turn over with ``1 - p``:

* A renewing tenant's new rent is set from *its own* rent: if it is below the reference,
  the RERA band for its own gap ``(reference - rent) / reference`` caps the increase (and
  the increase never takes it above the reference); no increase is allowed for an expiry
  inside the notice window after the analysis starts, because the 90-day notice could not
  have been served. If it is above the reference, it resets to the reference at renewal.
* A turnover re-lets at the reference rent, uncapped, after the downtime, with a leasing
  fee of ``leasing_fee_months`` of the new rent in the month of re-letting.

Expected rent each month is the probability-weighted sum over states. States with the
same rent are merged, so a unit carries at most one state per past expiry. Every lease
after an expiry runs 12 months from that expiry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

OCCUPIED_STATUSES = ("occupied", "under_renewal", "notice_served")
NON_INCOME_STATUSES = ("vacant", "legal_case")
UNIT_STATUSES = OCCUPIED_STATUSES + NON_INCOME_STATUSES


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
    """One unit as the lease model runs it."""

    unit: str
    unit_type: str
    area_sqft: float
    status: str
    annual_rent_aed: float | None
    expiry_month: int | None          # analysis month in which the lease rolls; None = no lease
    available_month: int = 0          # vacant / legal-case units: first month the unit can be let
    lease_end: str | None = None      # stated lease end (ISO date), for expiry concentration
    income_from_month: int = 0        # let units: first month the owner receives the rent
    lease_up_downtime: float | None = None   # months empty before the first let (None = mandate downtime)


@dataclass
class UnitSchedule:
    """Monthly results for one unit."""

    rent: list[float]                 # expected rent earned each month
    potential_rent: list[float]       # expected rent if there were no downtime
    leasing_fees: list[float]         # expected leasing fee each month
    events: list[dict] = field(default_factory=list)


def rera_max_increase(current_rent: float, reference_rent: float,
                      bands: Sequence[tuple[float, float]]) -> float:
    """Maximum permitted increase (a fraction of current rent) at renewal.

    ``bands`` is a list of ``(below_index_up_to, max_increase)`` pairs in ascending
    order. The gap below the reference is ``(reference - current) / reference``. Each
    upper bound is inclusive, so a rent exactly 10% below falls in the first band.
    A rent at or above the reference gets no increase.
    """
    if reference_rent <= 0 or current_rent >= reference_rent:
        return 0.0
    gap = (reference_rent - current_rent) / reference_rent
    for upper, max_increase in bands:
        if gap <= upper + 1e-12:
            return max_increase
    return bands[-1][1]


def renewal_rent(current_rent: float, reference_rent: float,
                 bands: Sequence[tuple[float, float]],
                 increase_allowed: bool = True) -> tuple[float, str]:
    """Rent on renewal for a tenant paying ``current_rent``, and the rule that set it.

    Rules: ``over_rented_reset_to_reference``, ``at_reference``,
    ``notice_window_no_increase`` or ``rera_band_<n>pct`` (n = the permitted increase in
    percent).
    """
    if current_rent > reference_rent:
        return reference_rent, "over_rented_reset_to_reference"
    if current_rent == reference_rent:
        return current_rent, "at_reference"
    if not increase_allowed:
        return current_rent, "notice_window_no_increase"
    increase = rera_max_increase(current_rent, reference_rent, bands)
    new_rent = min(reference_rent, current_rent * (1.0 + increase))
    return new_rent, f"rera_band_{round(increase * 100)}pct"


def _occupied_fraction(month_offset: int, downtime: float) -> float:
    """Share of month ``month_offset`` (0 = first month) let after a re-let with downtime."""
    return min(1.0, max(0.0, month_offset + 1 - downtime))


def _merge(states: list[list[float]]) -> list[list[float]]:
    """Merge ``[weight, rent]`` states with the same rent, keeping first-seen order."""
    out: list[list[float]] = []
    for w, r in states:
        if w <= 0:
            continue
        for s in out:
            if abs(s[1] - r) < 1e-6:
                s[0] += w
                break
        else:
            out.append([w, r])
    return out


def model_unit(unit: UnitLease, reference_rent_by_year: Sequence[float],
               a: LeaseAssumptions) -> UnitSchedule:
    """Simulate one unit's expected rent month by month.

    ``reference_rent_by_year[y]`` is the unit's annual screen reference rent for leases
    that start in analysis year ``y`` (0-based), including the house-view growth path and
    any sensitivity shift.
    """
    n = a.months
    rent = [0.0] * n
    potential = [0.0] * n
    fees = [0.0] * n
    events: list[dict] = []

    def ref_at(month: int) -> float:
        return reference_rent_by_year[min(month // 12, len(reference_rent_by_year) - 1)]

    def let_new(start: int, new_rent: float, share: float, downtime: float) -> None:
        """Add a re-let at ``new_rent`` for ``share`` of the unit from month ``start``."""
        for k in range(12):
            m = start + k
            if m >= n:
                break
            rent[m] += share * new_rent / 12.0 * _occupied_fraction(k, downtime)
            potential[m] += share * new_rent / 12.0
        fee_month = start + int(math.floor(downtime))
        if fee_month < n:
            fees[fee_month] += share * a.leasing_fee_months * new_rent / 12.0

    states: list[list[float]] = []          # [weight, annual rent] of the tenant(s) in place
    next_expiry: int | None = None
    if unit.status in NON_INCOME_STATUSES:
        # Vacant or legal case (from the start, or from a master-lease reversion): let at the
        # reference after the downtime, then roll like any other lease.
        start = unit.available_month
        downtime = a.downtime_months if unit.lease_up_downtime is None else unit.lease_up_downtime
        if start < n:
            first = ref_at(start)
            let_new(start, first, 1.0, downtime)
            events.append({"month": start, "type": "lease_up", "reference_rent": first,
                           "new_rent": first, "downtime_months": downtime})
            states = [[1.0, first]]
            next_expiry = start + 12
        probability = a.renewal_probability
    else:
        current = float(unit.annual_rent_aed or 0.0)
        next_expiry = unit.expiry_month
        stop = n if next_expiry is None else min(next_expiry, n)
        for m in range(unit.income_from_month, stop):
            rent[m] = current / 12.0
            potential[m] = current / 12.0
        states = [[1.0, current]]
        probability = 0.0 if unit.status == "notice_served" else a.renewal_probability

    while next_expiry is not None and next_expiry < n:
        e = next_expiry
        ref = ref_at(e)
        increase_allowed = e >= a.notice_months
        renewed: list[list[float]] = []
        detail = []
        for w, r in states:
            r_renew, rule = renewal_rent(r, ref, a.rera_bands, increase_allowed)
            detail.append({"weight": w, "current_rent": r, "renewal_rent": r_renew, "renewal_rule": rule})
            share = w * probability
            for k in range(12):
                m = e + k
                if m >= n:
                    break
                rent[m] += share * r_renew / 12.0
                potential[m] += share * r_renew / 12.0
            renewed.append([share, r_renew])
        # Turnover: every state's departing tenant is replaced at the (uncapped) reference.
        let_new(e, ref, 1.0 - probability, a.downtime_months)
        new_states = _merge(renewed + [[1.0 - probability, ref]])
        before = sum(w * r for w, r in states)
        events.append({
            "month": e, "type": "expiry", "reference_rent": ref, "renewal_probability": probability,
            "current_rent": before,
            "renewal_rent": sum(d["weight"] * d["renewal_rent"] for d in detail),
            "renewal_rule": detail[0]["renewal_rule"] if len(detail) == 1 else None,
            "tenant_states": detail,
            "turnover_rent": ref,
            "expected_rent_after": sum(w * r for w, r in new_states),
        })
        states = new_states
        next_expiry = e + 12
        probability = a.renewal_probability
    return UnitSchedule(rent=rent, potential_rent=potential, leasing_fees=fees, events=events)
