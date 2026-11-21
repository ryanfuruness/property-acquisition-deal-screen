"""Deterministic underwriting of a Dubai residential building.

``underwrite(deal_inputs, mandate, market)`` is a pure function: the same inputs give
the same result, with no randomness, I/O or network. The calculation has two halves:

* **Operations** (price-independent): the unit-level lease model, losses, opex and
  NOI for each year of the hold plus one forward year for the exit.
* **Capital** (price-dependent): acquisition costs, debt, exit and returns.

Keeping them separate lets the walk-away price search and the exit-yield sensitivity
re-run only the capital half. See engine/README.md for the input and result schemas.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .costs import acquisition_costs
from .finance import add_months, equity_multiple, irr, loan_schedule
from .inputs import Context, build_context
from .leases import PHYSICALLY_LET_STATUSES, UnitSchedule, model_unit
from .provenance import metric, series
from .yields import recompute_stated_yield

ENGINE_VERSION = "1.1.0"

# Analysis settings that are not market assumptions (DESIGN.md "Engine interface").
SENSITIVITY_EXIT_YIELD_SHIFTS_BPS = (-50, 0, 50)
SENSITIVITY_RENT_SHIFTS = (-0.05, 0.0, 0.05)
WALK_AWAY_STEP_AED = 10_000
EXPIRY_WINDOWS = 4              # expiry concentration: four 3-month windows from the rent roll date


# --------------------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------------------

@dataclass
class Operations:
    """Annual operating lines for years 1..hold+1, and the unit schedules behind them."""

    lines: dict[str, list[float]]
    opex_lines: dict[str, list[float]]
    unit_schedules: list[UnitSchedule]
    unit_market_rent_by_year: list[list[float]]


def run_operations(ctx: Context, rent_shift: float = 0.0) -> Operations:
    """Run the lease model and the operating statement.

    ``rent_shift`` scales every year's market rent level (0.05 = +5%); it is the rent
    axis of the sensitivity grid. In-place rents are not shifted.
    """
    n_years = ctx.hold_years + 1
    schedules: list[UnitSchedule] = []
    market_by_year: list[list[float]] = []
    potential = [0.0] * n_years
    gross_rent = [0.0] * n_years
    fees = [0.0] * n_years
    for unit, ref in zip(ctx.units, ctx.unit_market_rent_ref):
        mkt = [ref * idx * (1.0 + rent_shift) for idx in ctx.growth_index]
        sched = model_unit(unit, mkt, ctx.lease)
        schedules.append(sched)
        market_by_year.append(mkt)
        for month in range(n_years * 12):
            y = month // 12
            gross_rent[y] += sched.rent[month]
            potential[y] += sched.potential_rent[month]
            fees[y] += sched.leasing_fees[month]

    # Master lease: fixed rent until the reversion month, prorated by month.
    master = [0.0] * n_years
    reversion_share = [1.0] * n_years      # share of each year after the master lease reverts
    if ctx.master_lease is not None:
        r_month = ctx.master_lease.reversion_month
        for y in range(n_years):
            months_under = max(0, min(12, r_month - 12 * y))
            master[y] = ctx.master_lease.annual_rent_aed * months_under / 12.0
            reversion_share[y] = 1.0 - months_under / 12.0
            potential[y] += master[y]

    other = [ctx.other_income * (1.0 + ctx.other_income_growth) ** y for y in range(n_years)]
    gross_income = [r + mr + o for r, mr, o in zip(gross_rent, master, other)]
    downtime = [p - g - mr for p, g, mr in zip(potential, gross_rent, master)]
    # Structural vacancy is a general allowance that already includes the modelled
    # turnover and lease-up downtime: the deduction tops downtime up to the allowance
    # rather than stacking on it. The allowance is on unit-level rent and other income,
    # not on a master lease (one tenant pays for the whole building).
    allowance = [(r + o) * ctx.structural_vacancy for r, o in zip(gross_rent, other)]
    vacancy = [max(0.0, a - d) for a, d in zip(allowance, downtime)]
    collection = [(g - v) * ctx.collection_loss for g, v in zip(gross_income, vacancy)]
    egi = [g - v - c for g, v, c in zip(gross_income, vacancy, collection)]
    mgmt = [e * ctx.management_pct for e in egi]
    opex_lines: dict[str, list[float]] = {}
    for line in ctx.opex:
        opex_lines[line.category] = [
            line.amount * (1.0 + ctx.opex_growth) ** y * (reversion_share[y] if line.from_reversion else 1.0)
            for y in range(n_years)]
    vat_base = [m + f for m, f in zip(mgmt, fees)]
    if not ctx.opex_includes_vat:
        for line in ctx.opex:
            if line.vatable:
                vat_base = [b + a for b, a in zip(vat_base, opex_lines[line.category])]
    vat = [b * ctx.vat_on_opex for b in vat_base]
    fixed_opex = [sum(v[y] for v in opex_lines.values()) for y in range(n_years)]
    total_opex = [m + f + fo + t for m, f, fo, t in zip(mgmt, fees, fixed_opex, vat)]
    noi = [e - t for e, t in zip(egi, total_opex)]
    lines = {
        "potential_rental_income": potential,       # includes any master lease rent
        "downtime_loss": downtime,
        "gross_rental_income": gross_rent,
        "master_lease_income": master,
        "other_income": other,
        "gross_income": gross_income,
        "vacancy_allowance": allowance,
        "structural_vacancy": vacancy,         # top-up: max(0, allowance - downtime)
        "collection_loss": collection,
        "effective_gross_income": egi,
        "management_fee": mgmt,
        "operating_expenses": fixed_opex,
        "leasing_fees": fees,
        "input_vat": vat,
        "total_operating_costs": total_opex,
        "noi": noi,
    }
    return Operations(lines=lines, opex_lines=opex_lines, unit_schedules=schedules,
                      unit_market_rent_by_year=market_by_year)


# --------------------------------------------------------------------------------------
# Capital
# --------------------------------------------------------------------------------------

def run_capital(ctx: Context, ops: Operations, price: float,
                exit_yield_shift_bps: float = 0.0) -> dict[str, Any]:
    """Acquisition costs, debt, exit and returns at ``price``. Plain numbers only."""
    hold = ctx.hold_years
    loan = ctx.ltv * price
    acq = acquisition_costs(price, loan, ctx.acq)
    arrangement_fee = ctx.arrangement_fee_pct * loan
    schedule = loan_schedule(loan, ctx.interest_rate, ctx.amortisation_years, hold)
    debt_service = [row["debt_service"] for row in schedule]
    interest = [row["interest"] for row in schedule]
    noi = ops.lines["noi"][:hold]
    forward_noi = ops.lines["noi"][hold]

    exit_yield = ctx.exit_yield + exit_yield_shift_bps / 10_000.0
    if exit_yield <= 0:
        raise ValueError("exit yield must be positive")
    gross_exit = forward_noi / exit_yield
    selling_costs = gross_exit * ctx.selling_costs_pct
    net_sale = gross_exit - selling_costs
    balance_at_exit = schedule[-1]["closing_balance"] if schedule else loan

    unlevered_outlay = price + acq["transfer_costs"]
    equity = price + acq["total"] + arrangement_fee - loan
    unlev = [-unlevered_outlay] + list(noi)
    unlev[-1] += net_sale
    lev = [-equity] + [n - d for n, d in zip(noi, debt_service)]
    lev[-1] += net_sale - balance_at_exit

    # Simplified tax (mandate underwriting.tax): each year's taxable income is NOI (less
    # interest and arrangement-fee amortisation if levered); the exit gain, net sale
    # proceeds less total acquisition cost, is added in the sale year, so a loss on sale
    # offsets that year's income. The threshold applies once per year; no carry-forward.
    fee_amortisation = arrangement_fee / hold
    gain_unlev = net_sale - unlevered_outlay
    gain_lev = net_sale - (price + acq["total"])
    taxable_unlev = list(noi)
    taxable_unlev[-1] += gain_unlev
    taxable_lev = [n - i - fee_amortisation for n, i in zip(noi, interest)]
    taxable_lev[-1] += gain_lev
    tax_unlev = [ctx.tax_rate * max(0.0, t - ctx.tax_threshold) for t in taxable_unlev]
    tax_lev = [ctx.tax_rate * max(0.0, t - ctx.tax_threshold) for t in taxable_lev]
    unlev_post = [unlev[0]] + [cf - t for cf, t in zip(unlev[1:], tax_unlev)]
    lev_post = [lev[0]] + [cf - t for cf, t in zip(lev[1:], tax_lev)]

    ds1 = debt_service[0] if debt_service else 0.0
    return {
        "price": price,
        "loan": loan,
        "acquisition_costs": acq,
        "arrangement_fee": arrangement_fee,
        "equity": equity,
        "unlevered_outlay": unlevered_outlay,
        "schedule": schedule,
        "debt_service_year1": ds1,
        "interest_year1": interest[0] if interest else 0.0,
        "dscr_year1": noi[0] / ds1 if ds1 > 0 else None,
        "icr_year1": noi[0] / interest[0] if interest and interest[0] > 0 else None,
        "debt_yield_year1": noi[0] / loan if loan > 0 else None,
        "exit_yield": exit_yield,
        "forward_noi": forward_noi,
        "gross_exit_value": gross_exit,
        "selling_costs": selling_costs,
        "net_sale_proceeds": net_sale,
        "loan_balance_at_exit": balance_at_exit,
        "exit_gain_unlevered": gain_unlev,
        "exit_gain_levered": gain_lev,
        "taxable_income_unlevered": taxable_unlev,
        "taxable_income_levered": taxable_lev,
        "tax_unlevered": tax_unlev,
        "tax_levered": tax_lev,
        "cash_flows": {
            "unlevered_pre_tax": unlev, "unlevered_post_tax": unlev_post,
            "levered_pre_tax": lev, "levered_post_tax": lev_post,
        },
        "unlevered_irr_pre_tax": irr(unlev),
        "unlevered_irr_post_tax": irr(unlev_post),
        "levered_irr_pre_tax": irr(lev),
        "levered_irr_post_tax": irr(lev_post),
        "unlevered_equity_multiple_pre_tax": equity_multiple(unlev),
        "unlevered_equity_multiple_post_tax": equity_multiple(unlev_post),
        "levered_equity_multiple_pre_tax": equity_multiple(lev),
        "levered_equity_multiple_post_tax": equity_multiple(lev_post),
    }


def meets_return_and_cover(ctx: Context, cap: dict[str, Any]) -> bool:
    """True if a capital result meets the target levered IRR and the DSCR floor."""
    irr_ok = cap["levered_irr_pre_tax"] is not None and cap["levered_irr_pre_tax"] >= ctx.target_levered_irr
    dscr = cap["dscr_year1"]
    dscr_ok = dscr is None or dscr >= ctx.dscr_floor     # None means no debt service
    return irr_ok and dscr_ok


def solve_walk_away_price(ctx: Context, ops: Operations,
                          step: int = WALK_AWAY_STEP_AED) -> dict[str, Any]:
    """Highest price, on a grid of ``step`` AED, meeting the target levered IRR and DSCR floor.

    The loan scales with price (LTV is fixed), so DSCR and levered IRR both fall as the
    price rises. The search brackets the boundary by doubling, then bisects on whole
    multiples of ``step``. Returns the price, the metrics there and one step above, and
    which constraint binds.
    """
    def check(k: int) -> tuple[bool, dict[str, Any]]:
        cap = run_capital(ctx, ops, k * step)
        return meets_return_and_cover(ctx, cap), cap

    ok_lo, cap_lo = check(1)
    if not ok_lo:
        return {"price": None, "reason": "no price meets both constraints (NOI too low)"}
    lo = 1
    hi = max(2, int(ctx.price // step) + 1)
    while check(hi)[0]:
        lo, hi = hi, hi * 2
        if hi > 10**9:
            return {"price": None, "reason": "no upper bound found"}
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if check(mid)[0]:
            lo = mid
        else:
            hi = mid
    _, at = check(lo)
    _, above = check(lo + 1)
    irr_fails = not (above["levered_irr_pre_tax"] is not None
                     and above["levered_irr_pre_tax"] >= ctx.target_levered_irr)
    dscr_fails = not (above["dscr_year1"] is None or above["dscr_year1"] >= ctx.dscr_floor)
    binding = "both" if irr_fails and dscr_fails else "levered_irr" if irr_fails else "dscr_year1"
    return {"price": lo * step, "at": at, "above": above, "binding": binding, "step": step}


# --------------------------------------------------------------------------------------
# Rent-roll statistics
# --------------------------------------------------------------------------------------

def rent_roll_stats(ctx: Context) -> dict[str, Any]:
    """Occupancy, in-place rent, over-rent share and expiry concentration.

    Expiry concentration uses lease-end dates against windows from the rent roll date
    (``deal_inputs.rent_roll_date``, else the analysis start).

    Under a master lease the building is let in full to one tenant: occupancy is 100%,
    in-place rent is the master rent, the whole income expires on the master lease end,
    and it counts as over-rented if the master rent exceeds the market reference rent of
    all units.
    """
    total_ref = sum(ctx.unit_market_rent_ref)
    roll = ctx.rent_roll
    if ctx.master_lease is not None:
        ml = ctx.master_lease
        in_place = ml.annual_rent_aed
        lets = [(dt.date.fromisoformat(ml.lease_end), in_place)]
        over = in_place if in_place > total_ref else 0.0
        occ_units = occ_area = 1.0
        occupied_count = len(roll)
    else:
        occupied = [u for u in roll if u.status in PHYSICALLY_LET_STATUSES]
        in_place = sum(u.annual_rent_aed or 0.0 for u in occupied)
        lets = [(dt.date.fromisoformat(u.lease_end) if u.lease_end else dt.date.min, u.annual_rent_aed or 0.0)
                for u in occupied]
        over = sum(u.annual_rent_aed or 0.0 for u, ref in zip(roll, ctx.unit_market_rent_ref)
                   if u.status in PHYSICALLY_LET_STATUSES and (u.annual_rent_aed or 0.0) > ref)
        occ_units = len(occupied) / len(roll)
        occ_area = sum(u.area_sqft for u in occupied) / sum(u.area_sqft for u in roll)
        occupied_count = len(occupied)

    # Four consecutive 3-month windows from the rent roll date. A lease counts in the
    # window containing its lease end; one already expired (or with no end) counts in
    # the first window; one ending 12 months or more out counts in none.
    basis = ctx.expiry_basis_date
    edges = [add_months(basis, 3 * k) for k in range(EXPIRY_WINDOWS + 1)]
    windows: list[dict[str, Any]] = []
    for k in range(EXPIRY_WINDOWS):
        lo, hi = edges[k], edges[k + 1]
        rent = 0.0
        for end_date, r in lets:
            in_window = (lo <= end_date < hi) or (k == 0 and end_date < lo)
            rent += r if in_window else 0.0
        windows.append({"window": k + 1, "start": lo.isoformat(),
                         "end": (hi - dt.timedelta(days=1)).isoformat(),
                         "expiring_rent_aed": rent, "share": rent / in_place if in_place > 0 else None})
    best = max(windows, key=lambda w: w["share"] or 0.0) if in_place > 0 else None
    return {
        "unit_count": len(roll) if roll else None,
        "occupied_units": occupied_count,
        "occupancy_by_units": occ_units,
        "occupancy_by_area": occ_area,
        "in_place_rent": in_place,
        "market_rent_reference_total": total_ref,
        "over_rent_income": over,
        "over_rent_share_of_income": over / in_place if in_place > 0 else None,
        "expiry_windows": windows,
        "max_expiry_share_quarter": best["share"] if best else None,
        "max_expiry_window": best if best else None,
    }


# --------------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------------

def underwrite(deal_inputs: dict, mandate: dict, market: dict) -> dict[str, Any]:
    """Underwrite one deal. Pure and deterministic; see engine/README.md for the shapes."""
    ctx = build_context(deal_inputs, mandate, market)
    reg = ctx.registry
    d = ctx.deps

    def refs(*groups: str, extra: tuple[str, ...] = ()) -> list[dict[str, str]]:
        names: list[str] = []
        for g in groups:
            names += d[g]
        return reg.refs(names + list(extra))

    ops = run_operations(ctx)
    cap = run_capital(ctx, ops, ctx.price)
    rr = rent_roll_stats(ctx)
    hold = ctx.hold_years
    L = ops.lines

    # dependency lists reused below
    dep_noi = refs("noi")
    dep_price = refs("price")
    dep_acq = refs("acquisition", "mortgage_registration")
    dep_debt = refs("debt_service")
    dep_exit = refs("noi", "exit")
    dep_unlev = refs("noi", "exit", "acquisition")
    dep_lev = refs("noi", "exit", "acquisition", "mortgage_registration", "debt_service",
                   "arrangement_fee")
    dep_tax = refs("tax")

    noi1 = L["noi"][0]
    total_cost = ctx.price + cap["acquisition_costs"]["total"]
    M: dict[str, dict[str, Any]] = {}

    # ---- rent roll -----------------------------------------------------------------
    rr_deps = refs("master_lease", extra=("deal.units",))
    rr_market = refs("rent_roll", "master_lease")
    ml_note = " (master lease: let in full to one tenant)" if ctx.master_lease else ""
    M["unit_count"] = metric(rr["unit_count"], "units", refs(extra=("deal.units",)),
                             None if rr["unit_count"] is not None else "no rent roll supplied")
    M["occupancy_by_units"] = metric(rr["occupancy_by_units"], "ratio", rr_deps,
                                     "occupied, under renewal, notice served or legal case / all units" + ml_note)
    M["occupancy_by_area"] = metric(rr["occupancy_by_area"], "ratio", rr_deps, ml_note.strip() or None)
    M["in_place_rent_aed"] = metric(rr["in_place_rent"], "AED/yr", rr_deps,
                                    "master lease rent" if ctx.master_lease else
                                    "contract rent of physically let units (incl. legal case); vacant units carry none")
    M["market_rent_reference_aed"] = metric(rr["market_rent_reference_total"], "AED/yr",
                                            refs("rent_roll"), "all units at as-of market reference rent")
    M["over_rent_share_of_income"] = metric(rr["over_rent_share_of_income"], "ratio", rr_market,
                                            "in-place rent of leases above as-of market reference / in-place rent")
    M["max_expiry_share_quarter"] = metric(rr["max_expiry_share_quarter"], "ratio",
                                           rr_deps + refs(extra=("deal.rent_roll_date",
                                                                 "mandate.underwriting.analysis_start")),
                                           _expiry_note(rr["max_expiry_window"]))

    # ---- operations ----------------------------------------------------------------------
    M["potential_rental_income_year1"] = metric(L["potential_rental_income"][0], "AED/yr", refs("rent_model"))
    M["gross_rental_income_year1"] = metric(L["gross_rental_income"][0], "AED/yr", refs("rent_model"),
                                            "unit-level rent (excludes any master lease rent)")
    M["master_lease_income_year1"] = metric(L["master_lease_income"][0], "AED/yr", refs("rent_model"))
    M["effective_gross_income_year1"] = metric(L["effective_gross_income"][0], "AED/yr", refs("egi"))
    M["operating_costs_year1"] = metric(L["total_operating_costs"][0], "AED/yr", dep_noi)
    M["noi_year1"] = metric(noi1, "AED/yr", dep_noi)
    M["opex_ratio_year1"] = metric(L["total_operating_costs"][0] / L["effective_gross_income"][0]
                                   if L["effective_gross_income"][0] else None, "ratio", dep_noi,
                                   "operating costs / EGI")

    # ---- pricing -------------------------------------------------------------------------
    M["price_aed"] = metric(ctx.price, "AED", dep_price)
    M["price_per_sqft_nsa"] = metric(ctx.price / ctx.nsa_sqft, "AED/sqft", refs(extra=("deal.price_aed", "deal.nsa_sqft")))
    M["price_per_sqft_bua"] = metric(ctx.price / ctx.bua_sqft if ctx.bua_sqft else None, "AED/sqft",
                                     refs(extra=("deal.price_aed", "deal.bua_sqft")))
    M["acquisition_costs_aed"] = metric(cap["acquisition_costs"]["total"], "AED", dep_acq)
    M["acquisition_costs_pct_of_price"] = metric(cap["acquisition_costs"]["total"] / ctx.price, "ratio", dep_acq)
    M["total_cost_aed"] = metric(total_cost, "AED", dep_acq, "price + acquisition costs")
    M["gross_yield_in_place_on_price"] = metric(rr["in_place_rent"] / ctx.price, "ratio",
                                                refs(extra=("deal.units", "deal.price_aed")),
                                                "broker convention: in-place rent / price, no costs")
    M["going_in_net_yield_on_price"] = metric(noi1 / ctx.price, "ratio", refs("noi", "price"))
    M["going_in_net_yield_on_cost"] = metric(noi1 / total_cost, "ratio", refs("noi", "acquisition", "mortgage_registration"),
                                             "Year-1 NOI / (price + acquisition costs)")

    # ---- debt ------------------------------------------------------------------------------
    M["loan_aed"] = metric(cap["loan"], "AED", refs("loan"))
    M["interest_rate"] = metric(ctx.interest_rate, "ratio/yr", refs("interest_rate"),
                                "3M EIBOR + margin, held flat")
    M["annual_debt_service_aed"] = metric(cap["debt_service_year1"], "AED/yr", dep_debt,
                                          "level annual payment, amortising")
    M["arrangement_fee_aed"] = metric(cap["arrangement_fee"], "AED", refs("arrangement_fee"))
    M["equity_aed"] = metric(cap["equity"], "AED", refs("acquisition", "mortgage_registration", "arrangement_fee"),
                             "price + acquisition costs + arrangement fee - loan")
    M["dscr_year1"] = metric(cap["dscr_year1"], "x", refs("noi", "debt_service"),
                             "Year-1 NOI / Year-1 debt service (interest + principal)")
    M["icr_year1"] = metric(cap["icr_year1"], "x", refs("noi", "debt_service"),
                            "Year-1 NOI / Year-1 interest (shown for context; the mandate tests DSCR)")
    M["debt_yield_year1"] = metric(cap["debt_yield_year1"], "ratio", refs("noi", "loan"))

    # breakeven occupancy for DSCR 1.0 (Year 1)
    pgi = L["potential_rental_income"][0] + L["other_income"][0]
    vat = ctx.vat_on_opex
    fixed = L["operating_expenses"][0] + L["leasing_fees"][0] * (1 + vat)
    if not ctx.opex_includes_vat:
        fixed += vat * sum(ops.opex_lines[line.category][0] for line in ctx.opex if line.vatable)
    variable_margin = (1 - ctx.collection_loss) * (1 - ctx.management_pct * (1 + vat))
    breakeven = (fixed + cap["debt_service_year1"]) / (pgi * variable_margin) if pgi > 0 else None
    M["breakeven_occupancy_dscr_1"] = metric(
        breakeven, "ratio", refs("noi", "debt_service"),
        "economic occupancy of Year-1 potential income at which NOI equals debt service")
    M["economic_occupancy_year1"] = metric(
        (L["gross_income"][0] - L["structural_vacancy"][0]) / pgi if pgi > 0 else None, "ratio",
        refs("egi"), "income after downtime and structural vacancy / potential income")

    # ---- exit and returns --------------------------------------------------------------------
    M["exit_yield"] = metric(cap["exit_yield"], "ratio", refs("exit"), "area exit yield + expansion")
    M["forward_noi_aed"] = metric(cap["forward_noi"], "AED/yr", dep_noi, f"NOI of year {hold + 1}")
    M["gross_exit_value_aed"] = metric(cap["gross_exit_value"], "AED", dep_exit)
    M["net_sale_proceeds_aed"] = metric(cap["net_sale_proceeds"], "AED", dep_exit, "after selling costs")
    M["loan_balance_at_exit_aed"] = metric(cap["loan_balance_at_exit"], "AED", dep_debt)
    M["exit_gain_levered_aed"] = metric(cap["exit_gain_levered"], "AED", dep_lev + dep_tax,
                                        "net sale proceeds - (price + acquisition costs); taxed in the sale year")
    for key, deps in (("unlevered", dep_unlev), ("levered", dep_lev)):
        for t in ("pre_tax", "post_tax"):
            dd = deps if t == "pre_tax" else deps + [r for r in dep_tax if r not in deps]
            M[f"{key}_irr_{t}"] = metric(cap[f"{key}_irr_{t}"], "ratio", dd)
            M[f"{key}_equity_multiple_{t}"] = metric(cap[f"{key}_equity_multiple_{t}"], "x", dd)

    # ---- walk-away price -------------------------------------------------------------------------
    wa = solve_walk_away_price(ctx, ops)
    dep_wa = refs("noi", "exit", "acquisition", "mortgage_registration", "debt_service",
                  "arrangement_fee", "dscr_floor", "target_irr")
    walk_away: dict[str, Any] = {
        "price_aed": metric(wa["price"], "AED", dep_wa,
                            f"highest price on a AED {WALK_AWAY_STEP_AED:,} grid meeting target levered IRR "
                            f"(pre-tax) and the Year-1 DSCR floor; loan scales with price"),
    }
    if wa["price"] is not None:
        at, above = wa["at"], wa["above"]
        walk_away.update({
            "binding_constraint": wa["binding"],
            "target_levered_irr": metric(ctx.target_levered_irr, "ratio", refs("target_irr")),
            "dscr_floor": metric(ctx.dscr_floor, "x", refs("dscr_floor")),
            "levered_irr_at_price": metric(at["levered_irr_pre_tax"], "ratio", dep_wa),
            "dscr_at_price": metric(at["dscr_year1"], "x", dep_wa),
            "levered_irr_one_step_above": metric(above["levered_irr_pre_tax"], "ratio", dep_wa),
            "dscr_one_step_above": metric(above["dscr_year1"], "x", dep_wa),
            "discount_to_asking": metric(1 - wa["price"] / ctx.price, "ratio", dep_wa + dep_price),
            "going_in_net_yield_on_cost_at_price": metric(
                noi1 / (wa["price"] + at["acquisition_costs"]["total"]), "ratio", dep_wa),
        })
    else:
        walk_away["reason"] = wa["reason"]
    M["walk_away_price_aed"] = walk_away["price_aed"]

    # ---- sensitivity -----------------------------------------------------------------------------
    cells = []
    for rent_shift in SENSITIVITY_RENT_SHIFTS:
        ops_s = ops if rent_shift == 0 else run_operations(ctx, rent_shift)
        for bps in SENSITIVITY_EXIT_YIELD_SHIFTS_BPS:
            c = run_capital(ctx, ops_s, ctx.price, bps)
            cells.append({
                "rent_shift": rent_shift, "exit_yield_shift_bps": bps,
                "exit_yield": c["exit_yield"], "noi_year1": ops_s.lines["noi"][0],
                "dscr_year1": c["dscr_year1"],
                "levered_irr_pre_tax": c["levered_irr_pre_tax"],
                "unlevered_irr_pre_tax": c["unlevered_irr_pre_tax"],
                "levered_equity_multiple_pre_tax": c["levered_equity_multiple_pre_tax"],
            })
    sensitivity = {
        "rent_shifts": list(SENSITIVITY_RENT_SHIFTS),
        "exit_yield_shifts_bps": list(SENSITIVITY_EXIT_YIELD_SHIFTS_BPS),
        "note": "rent shift scales every year's market rent level; in-place rents are unchanged until they roll",
        "units": {"rent_shift": "ratio", "exit_yield": "ratio", "noi_year1": "AED/yr", "dscr_year1": "x",
                  "levered_irr_pre_tax": "ratio", "unlevered_irr_pre_tax": "ratio",
                  "levered_equity_multiple_pre_tax": "x"},
        "depends_on": dep_lev,
        "cells": cells,
    }

    # ---- acquisition cost breakdown ---------------------------------------------------------------
    a = cap["acquisition_costs"]
    dep_tr = refs("acquisition")
    dep_mr = refs("mortgage_registration")
    acq_out = {k: metric(a[k], "AED", dep_mr if k == "mortgage_registration" else dep_tr)
               for k in ("dld_transfer_fee", "dld_admin", "trustee_fee", "broker_fee", "broker_fee_vat",
                         "mortgage_registration", "transfer_costs")}
    acq_out["total"] = metric(a["total"], "AED", dep_acq)

    # ---- tables ------------------------------------------------------------------------------------
    years = list(range(1, hold + 2))
    starts = [add_months(ctx.analysis_start, 12 * (y - 1)) for y in years]
    ends = [add_months(s, 12) - dt.timedelta(days=1) for s in starts]
    line_deps = {
        "potential_rental_income": refs("rent_model"), "downtime_loss": refs("rent_model"),
        "gross_rental_income": refs("rent_model"), "master_lease_income": refs("rent_model"),
        "other_income": refs("other_income"),
        "gross_income": refs("rent_model", "other_income"), "vacancy_allowance": refs("egi"),
        "structural_vacancy": refs("egi"),
        "collection_loss": refs("egi"), "effective_gross_income": refs("egi"),
        "management_fee": refs("egi", "management"), "operating_expenses": refs("opex"),
        "leasing_fees": refs("rent_model"), "input_vat": dep_noi,
        "total_operating_costs": dep_noi, "noi": dep_noi,
    }
    cash_flow = {
        "unit": "AED",
        "years": years,
        "period_start": [s.isoformat() for s in starts],
        "period_end": [e.isoformat() for e in ends],
        "in_hold": [y <= hold for y in years],
        "lines": {k: series(v, line_deps[k]) for k, v in L.items()},
        "opex_by_category": {
            line.category: series(ops.opex_lines[line.category],
                                  reg.refs([f"deal.opex_aed.{line.category}"]), line.note)
            for line in ctx.opex
        },
    }
    debt_rows = cap["schedule"]
    debt_table = {
        "unit": "AED",
        "years": list(range(1, hold + 1)),
        "lines": {k: series([r[k] for r in debt_rows], dep_debt)
                  for k in ("opening_balance", "interest", "principal", "debt_service", "closing_balance")},
    }
    returns_table = {
        "unit": "AED",
        "years": list(range(0, hold + 1)),
        "lines": {
            "unlevered_pre_tax": series(cap["cash_flows"]["unlevered_pre_tax"], dep_unlev,
                                        "year 0: price + transfer costs; final year includes net sale"),
            "unlevered_post_tax": series(cap["cash_flows"]["unlevered_post_tax"], dep_unlev + dep_tax),
            "levered_pre_tax": series(cap["cash_flows"]["levered_pre_tax"], dep_lev,
                                      "year 0: equity; final year includes net sale less loan repayment"),
            "levered_post_tax": series(cap["cash_flows"]["levered_post_tax"], dep_lev + dep_tax),
            "tax_unlevered": series([0.0] + cap["tax_unlevered"], dep_noi + dep_tax),
            "tax_levered": series([0.0] + cap["tax_levered"], dep_lev + dep_tax,
                                  "taxable income = NOI - interest - arrangement fee amortisation; "
                                  "final year adds the exit gain"),
        },
    }

    unit_rows = []
    for u, ref, sched, mkt in zip(ctx.units, ctx.unit_market_rent_ref, ops.unit_schedules,
                                  ops.unit_market_rent_by_year):
        unit_rows.append({
            "unit": u.unit, "unit_type": u.unit_type, "area_sqft": u.area_sqft, "status": u.status,
            "in_place_rent_aed": u.annual_rent_aed if u.status in PHYSICALLY_LET_STATUSES else None,
            "market_rent_reference_aed": ref,
            "rent_vs_market": ((u.annual_rent_aed / ref - 1)
                               if u.status in PHYSICALLY_LET_STATUSES and u.annual_rent_aed and ref else None),
            "expiry_month": u.expiry_month,
            "market_rent_by_year": mkt,
            "expected_rent_by_year": [sum(sched.rent[12 * y: 12 * y + 12]) for y in range(hold + 1)],
            "events": sched.events,
        })
    unit_schedule = {"depends_on": refs("rent_model"), "units": unit_rows,
                     "note": "expected-value blend of renewal and turnover; months counted from the analysis start"}

    # The OM check registers its own inputs, so it runs before the registry is copied out.
    om_check = _om_yield_check(ctx, noi1, cap, refs) if ctx.om_stated else None

    result: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "deal_id": ctx.deal_id,
        "analysis_start": ctx.analysis_start.isoformat(),
        "hold_years": hold,
        "inputs": reg.as_dict(),
        "metrics": M,
        "acquisition_costs": acq_out,
        "cash_flow": cash_flow,
        "debt_schedule": debt_table,
        "returns_cash_flows": returns_table,
        "sensitivity": sensitivity,
        "walk_away": walk_away,
        "unit_schedule": unit_schedule,
        "om_yield_check": om_check,
        "master_lease": _master_lease_summary(ctx, refs),
        "expiry_windows": {"depends_on": rr_deps + refs(extra=("deal.rent_roll_date",)), "unit": "AED/yr",
                           "basis_date": ctx.expiry_basis_date.isoformat(), "windows": rr["expiry_windows"]},
        "warnings": list(ctx.warnings),
    }
    return result


def _om_yield_check(ctx: Context, noi1: float, cap: dict[str, Any], refs) -> dict[str, Any]:
    """Wrap :func:`recompute_stated_yield` output as metrics with provenance."""
    om = ctx.om_stated or {}
    reg = ctx.registry
    basis = om.get("yield_basis")
    measure = (basis or {}).get("measure") if isinstance(basis, dict) else basis
    income = om.get("net_income_aed") if (measure == "net" and om.get("net_income_aed") is not None) \
        else om.get("annual_rent_aed")
    reg.add("deal.om_stated.income_aed", income, "AED/yr", "document")
    reg.add("deal.om_stated.yield", om.get("yield"), "ratio", "document")
    reg.add("deal.om_stated.yield_basis", basis, "text", "document")
    raw = recompute_stated_yield(income, ctx.price, basis, stated_yield=om.get("yield"),
                                 noi_year1=noi1, acquisition_costs_aed=cap["acquisition_costs"]["total"])
    om_deps = refs(extra=("deal.om_stated.income_aed", "deal.price_aed", "deal.om_stated.yield_basis"))
    cost_deps = refs("acquisition", "mortgage_registration")
    buyer_deps = refs("noi", "acquisition", "mortgage_registration")
    return {
        "om_basis": raw["om_basis"],
        "summary": raw["summary"],
        "reproduces_stated": raw["reproduces_stated"],
        "stated_yield": metric(raw["stated_yield"], "ratio", refs(extra=("deal.om_stated.yield",))),
        "reproduced_on_om_basis": metric(raw["reproduced_on_om_basis"], "ratio", om_deps + cost_deps),
        "stated_income_on_price": metric(raw["stated_income_on_price"], "ratio", om_deps),
        "stated_income_on_total_cost": metric(raw["stated_income_on_total_cost"], "ratio", om_deps + cost_deps),
        "buyer_net_on_price": metric(raw["buyer_net_on_price"], "ratio", refs("noi", "price")),
        "buyer_net_on_total_cost": metric(raw["buyer_net_on_total_cost"], "ratio", buyer_deps),
        "gap_vs_stated": metric(raw["gap_vs_stated"], "ratio", buyer_deps + om_deps),
    }


def _expiry_note(window: dict[str, Any] | None) -> str:
    text = (f"largest share of in-place rent expiring in one of the {EXPIRY_WINDOWS} consecutive "
            f"3-month windows from the rent roll date")
    if window:
        text += f" (window {window['window']}: {window['start']} to {window['end']})"
    return text


def _master_lease_summary(ctx: Context, refs) -> dict[str, Any] | None:
    """The master lease as the engine read it, or ``None`` for direct leases."""
    ml = ctx.master_lease
    if ml is None:
        return None
    reversion = add_months(ctx.analysis_start, ml.reversion_month)
    return {
        "tenant": ml.tenant,
        "related_party": ml.related_party,
        "annual_rent_aed": metric(ml.annual_rent_aed, "AED/yr", refs("master_lease")),
        "lease_end": ml.lease_end,
        "cheques": ml.cheques,
        "reversion_month": ml.reversion_month,
        "reversion_date": reversion.isoformat(),
        "note": "income is the master rent until reversion; then every unit turns over and lets at market "
                "after the downtime",
    }
