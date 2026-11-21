"""Deterministic underwriting of a Dubai residential building.

``underwrite(deal_inputs, mandate, market)`` is a pure function: the same inputs give
the same result, with no randomness, I/O or network. The calculation has two halves:

* **Operations** (price-independent): the unit-level lease model, losses, opex and
  NOI for each year of the hold plus one forward year for the exit.
* **Capital** (price-dependent): acquisition costs, debt sized to cover, the exit and
  returns. The exit yield depends on price through the entry yield, and the loan
  through max LTV, so this half is re-run at every price the walk-away search tries.

The screen decides on unlevered, pre-tax returns. Levered and post-tax returns are
secondary outputs; post-tax figures are indicative only (``mandate.underwriting.tax``).
See engine/README.md for the input and result schemas.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .costs import acquisition_costs
from .finance import add_months, annuity_payment, equity_multiple, irr, loan_schedule
from .inputs import Context, build_context
from .leases import OCCUPIED_STATUSES, UnitSchedule, model_unit
from .provenance import metric, series
from .yields import recompute_stated_yield

ENGINE_VERSION = "2.0.0"

# Analysis settings that are not market assumptions (DESIGN.md "Engine interface").
SENSITIVITY_EXIT_YIELD_SHIFTS_BPS = (-50, 0, 50)
SENSITIVITY_RENT_SHIFTS = (-0.05, 0.0, 0.05)
WALK_AWAY_STEP_AED = 10_000
EXPIRY_WINDOWS = 4              # expiry concentration: four 3-month windows from the rent roll date
RETAIL_UNIT_TYPE = "retail"     # commercial units: their rent carries output VAT, so input VAT is recoverable

# Metrics that lead every summary: the screen decides on unlevered, pre-tax value.
HEADLINE_METRICS = (
    "unlevered_irr_pre_tax", "unlevered_equity_multiple_pre_tax", "entry_yield_on_price",
    "exit_yield", "going_in_net_yield_on_cost", "noi_year1", "walk_away_price_aed",
)


# --------------------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------------------

@dataclass
class Operations:
    """Annual operating lines for years 1..hold+1, and the unit schedules behind them."""

    lines: dict[str, list[float]]
    opex_lines: dict[str, list[float]]
    unit_schedules: list[UnitSchedule]
    unit_reference_rent_by_year: list[list[float]]


def run_operations(ctx: Context, rent_shift: float = 0.0) -> Operations:
    """Run the lease model and the operating statement.

    ``rent_shift`` scales every year's reference rent level (0.05 = +5%); it is the rent
    axis of the sensitivity grid. In-place rents are not shifted.
    """
    n_years = ctx.hold_years + 1
    schedules: list[UnitSchedule] = []
    reference_by_year: list[list[float]] = []
    potential = [0.0] * n_years
    gross_rent = [0.0] * n_years
    retail_rent = [0.0] * n_years
    modelled_fees = [0.0] * n_years
    for unit, ref in zip(ctx.units, ctx.unit_market_rent_ref):
        path = [ref * idx * (1.0 + rent_shift) for idx in ctx.growth_index]
        sched = model_unit(unit, path, ctx.lease)
        schedules.append(sched)
        reference_by_year.append(path)
        for month in range(n_years * 12):
            y = month // 12
            gross_rent[y] += sched.rent[month]
            potential[y] += sched.potential_rent[month]
            modelled_fees[y] += sched.leasing_fees[month]
            if unit.unit_type == RETAIL_UNIT_TYPE:
                retail_rent[y] += sched.rent[month]

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
    # turnover, lease-up and legal-case downtime: the deduction tops downtime up to the
    # allowance rather than stacking on it. The allowance is on unit-level rent and other
    # income, not on a master lease (one tenant pays for the whole building).
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
    # Leasing costs are not double counted: a stated marketing/leasing line covers modelled
    # turnover fees up to its amount; only the excess is added.
    stated_leasing = opex_lines.get("marketing_leasing", [0.0] * n_years) if ctx.marketing_leasing_stated \
        else [0.0] * n_years
    fees = [max(0.0, f - s) for f, s in zip(modelled_fees, stated_leasing)]
    vat_base = [m + f for m, f in zip(mgmt, fees)]
    if not ctx.opex_includes_vat:
        for line in ctx.opex:
            if line.vatable:
                vat_base = [b + a for b, a in zip(vat_base, opex_lines[line.category])]
    vat_gross = [b * ctx.vat_on_opex for b in vat_base]
    # Mixed use: input VAT is recoverable in proportion to commercial (retail) rent in
    # total rent; the residential share (VAT-exempt rent) stays a cost. A master lease is
    # treated as residential.
    commercial_share = [rr / (g + mr) if (g + mr) > 0 else 0.0
                        for rr, g, mr in zip(retail_rent, gross_rent, master)]
    vat_recovered = [v * s for v, s in zip(vat_gross, commercial_share)]
    vat = [v - r for v, r in zip(vat_gross, vat_recovered)]
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
        "leasing_fees_modelled": modelled_fees,
        "leasing_fees": fees,                  # modelled fees beyond a stated marketing/leasing line
        "commercial_income_share": commercial_share,
        "input_vat_gross": vat_gross,
        "input_vat_recovered": vat_recovered,
        "input_vat": vat,                      # the irrecoverable cost in NOI
        "total_operating_costs": total_opex,
        "noi": noi,
    }
    return Operations(lines=lines, opex_lines=opex_lines, unit_schedules=schedules,
                      unit_reference_rent_by_year=reference_by_year)


# --------------------------------------------------------------------------------------
# Capital
# --------------------------------------------------------------------------------------

def size_loan(ctx: Context, noi_year1: float, price: float,
              amortisation_years: int | None = None) -> dict[str, Any]:
    """Loan = lower of max LTV x price and the amount Year-1 NOI covers at the sizing DSCR."""
    years = amortisation_years or ctx.amortisation_years
    constant = annuity_payment(1.0, ctx.interest_rate, years)
    at_ltv = ctx.max_ltv * price
    at_dscr = max(0.0, noi_year1 / (ctx.sizing_dscr * constant)) if constant > 0 else at_ltv
    loan = min(at_ltv, at_dscr)
    return {"loan": loan, "loan_at_max_ltv": at_ltv, "loan_at_sizing_dscr": at_dscr,
            "sizing_constraint": "ltv" if at_ltv <= at_dscr else "dscr",
            "loan_constant": constant, "amortisation_years": years}


def exit_yield_components(ctx: Context, noi_year1: float, price: float,
                          shift_bps: float = 0.0) -> dict[str, Any]:
    """Exit yield = max(area house view, entry yield on price) + expansion + age premium (+ shift)."""
    entry = noi_year1 / price
    base = max(ctx.area_exit_yield, entry)
    value = base + (ctx.exit_expansion_bps + ctx.exit_age_premium_bps + shift_bps) / 10_000.0
    return {"entry_yield_on_price": entry, "area_house_view": ctx.area_exit_yield, "base": base,
            "base_source": "area_house_view" if ctx.area_exit_yield >= entry else "entry_yield",
            "expansion_bps": ctx.exit_expansion_bps, "age_premium_bps": ctx.exit_age_premium_bps,
            "sensitivity_shift_bps": shift_bps, "exit_yield": value}


def run_capital(ctx: Context, ops: Operations, price: float, exit_yield_shift_bps: float = 0.0,
                amortisation_years: int | None = None) -> dict[str, Any]:
    """Acquisition costs, debt, exit and returns at ``price``. Plain numbers only."""
    hold = ctx.hold_years
    noi = ops.lines["noi"][:hold]
    forward_noi = ops.lines["noi"][hold]
    sizing = size_loan(ctx, noi[0], price, amortisation_years)
    loan = sizing["loan"]
    acq = acquisition_costs(price, loan, ctx.acq)
    arrangement_fee = ctx.arrangement_fee_pct * loan
    schedule = loan_schedule(loan, ctx.interest_rate, sizing["amortisation_years"], hold)
    debt_service = [row["debt_service"] for row in schedule]
    interest = [row["interest"] for row in schedule]

    ex = exit_yield_components(ctx, noi[0], price, exit_yield_shift_bps)
    exit_yield = ex["exit_yield"]
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

    # Indicative tax (mandate underwriting.tax.model): each year's taxable income is NOI
    # (less interest and arrangement-fee amortisation if levered); the exit gain, net sale
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
        "sizing": sizing,
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
        "exit": ex,
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


def meets_target(ctx: Context, cap: dict[str, Any]) -> bool:
    """True if a capital result meets the target unlevered (pre-tax) IRR."""
    value = cap["unlevered_irr_pre_tax"]
    return value is not None and value >= ctx.target_unlevered_irr


def solve_walk_away_price(ctx: Context, ops: Operations, exit_yield_shift_bps: float = 0.0,
                          step: int = WALK_AWAY_STEP_AED) -> dict[str, Any]:
    """Highest price, on a grid of ``step`` AED, meeting the target unlevered IRR.

    Unlevered IRR falls as the price rises (the exit yield is never below the entry
    yield, so a lower price also raises the exit yield, but by less than it raises
    the return). Debt is re-sized at each price for the outputs reported there. The search
    brackets the boundary by doubling, then bisects on whole multiples of ``step``.
    """
    def check(k: int) -> tuple[bool, dict[str, Any]]:
        cap = run_capital(ctx, ops, k * step, exit_yield_shift_bps)
        return meets_target(ctx, cap), cap

    if not check(1)[0]:
        return {"price": None, "reason": "no price meets the target unlevered IRR (NOI too low)"}
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
    return {"price": lo * step, "at": at, "above": above, "binding": "unlevered_irr", "step": step}


def walk_away_sensitivity(ctx: Context, ops: Operations, base_price: float | None) -> dict[str, Any]:
    """Walk-away price under exit yield -50/+50 bps and reference rent -5%/+5%.

    Returns each case and the assumption whose two cases move the walk-away the most.
    """
    cases = []
    for bps in (b for b in SENSITIVITY_EXIT_YIELD_SHIFTS_BPS if b != 0):
        wa = solve_walk_away_price(ctx, ops, exit_yield_shift_bps=bps)
        cases.append({"assumption": "exit_yield", "case": f"{bps:+d} bps", "shift": bps,
                      "price_aed": wa["price"]})
    for shift in (s for s in SENSITIVITY_RENT_SHIFTS if s != 0):
        wa = solve_walk_away_price(ctx, run_operations(ctx, shift))
        cases.append({"assumption": "reference_rent_path", "case": f"{shift:+.0%}", "shift": shift,
                      "price_aed": wa["price"]})
    for c in cases:
        c["delta_aed"] = (c["price_aed"] - base_price
                          if c["price_aed"] is not None and base_price is not None else None)
    swings: dict[str, float] = {}
    for c in cases:
        if c["delta_aed"] is not None:
            swings[c["assumption"]] = max(swings.get(c["assumption"], 0.0), abs(c["delta_aed"]))
    most = max(swings, key=lambda k: swings[k]) if swings else None
    labels = {"exit_yield": "exit yield (+/-50 bps)", "reference_rent_path": "reference rent path (+/-5%)"}
    return {"cases": cases,
            "most_sensitive_assumption": most,
            "most_sensitive_label": labels.get(most) if most else None,
            "largest_swing_aed": swings.get(most) if most else None}


# --------------------------------------------------------------------------------------
# Rent-roll statistics
# --------------------------------------------------------------------------------------

def rent_roll_stats(ctx: Context) -> dict[str, Any]:
    """Occupancy, in-place rent, over-rent share and expiry concentration.

    Occupied means occupied, under renewal or notice served; legal-case and vacant units
    are not occupied and carry no in-place rent. A unit is over-rented only if its rent
    exceeds the screen reference rent by more than ``buy_box.soft.over_rent_threshold``.
    Expiry concentration uses lease-end dates against windows from the rent roll date
    (``deal_inputs.rent_roll_date``, else the analysis start).

    Under a master lease the building is let in full to one tenant: occupancy is 100%,
    in-place rent is the master rent, the whole income expires on the master lease end,
    and it counts as over-rented if the master rent exceeds the reference rent of all
    units by more than the threshold.
    """
    total_ref = sum(ctx.unit_market_rent_ref)
    roll = ctx.rent_roll
    threshold = 1.0 + ctx.over_rent_threshold
    if ctx.master_lease is not None:
        ml = ctx.master_lease
        in_place = ml.annual_rent_aed
        lets = [(dt.date.fromisoformat(ml.lease_end), in_place)]
        over_rented = in_place > total_ref * threshold
        over = in_place if over_rented else 0.0
        over_excess = in_place - total_ref if over_rented else 0.0
        occ_units = occ_area = 1.0
        occupied_count = len(roll)
    else:
        # Direct leases: ctx.units is the rent roll, aligned with the reference rents.
        occupied = [u for u in roll if u.status in OCCUPIED_STATUSES]
        in_place = sum(u.annual_rent_aed or 0.0 for u in occupied)
        lets = [(dt.date.fromisoformat(u.lease_end) if u.lease_end else dt.date.min, u.annual_rent_aed or 0.0)
                for u in occupied]
        over = over_excess = 0.0
        for u, ref in zip(roll, ctx.unit_market_rent_ref):
            if u.status in OCCUPIED_STATUSES and (u.annual_rent_aed or 0.0) > ref * threshold:
                over += u.annual_rent_aed
                over_excess += u.annual_rent_aed - ref
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
        "screen_reference_rent_total": total_ref,
        "over_rent_income": over,
        "over_rent_excess_at_expiry": over_excess,
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
    indicative = f"indicative only; {ctx.tax_model}"

    noi1 = L["noi"][0]
    total_cost = ctx.price + cap["acquisition_costs"]["total"]
    M: dict[str, dict[str, Any]] = {}

    # ---- headline: unlevered, pre-tax ----------------------------------------------------
    M["unlevered_irr_pre_tax"] = metric(cap["unlevered_irr_pre_tax"], "ratio", dep_unlev,
                                        "decision metric: unlevered, pre-tax")
    M["unlevered_equity_multiple_pre_tax"] = metric(cap["unlevered_equity_multiple_pre_tax"], "x", dep_unlev,
                                                    "decision metric: unlevered, pre-tax")
    M["entry_yield_on_price"] = metric(cap["exit"]["entry_yield_on_price"], "ratio", refs("noi", "price"),
                                       "Year-1 NOI / price (the buy yield)")
    M["exit_yield"] = metric(cap["exit_yield"], "ratio", dep_exit,
                             "max(area house view, entry yield on price) + expansion + age premium")

    # ---- rent roll -----------------------------------------------------------------
    rr_deps = refs("master_lease", extra=("deal.units",))
    over_deps = refs("over_rent", "master_lease")
    ml_note = " (master lease: let in full to one tenant)" if ctx.master_lease else ""
    M["unit_count"] = metric(rr["unit_count"], "units", refs(extra=("deal.units",)),
                             None if rr["unit_count"] is not None else "no rent roll supplied")
    M["occupancy_by_units"] = metric(rr["occupancy_by_units"], "ratio", rr_deps,
                                     "occupied, under renewal or notice served / all units; legal-case and "
                                     "vacant units are not occupied" + ml_note)
    M["occupancy_by_area"] = metric(rr["occupancy_by_area"], "ratio", rr_deps, ml_note.strip() or None)
    M["in_place_rent_aed"] = metric(rr["in_place_rent"], "AED/yr", rr_deps,
                                    "master lease rent" if ctx.master_lease else
                                    "contract rent of occupied units; vacant and legal-case units carry none")
    M["screen_reference_rent_aed"] = metric(rr["screen_reference_rent_total"], "AED/yr", refs("rent_roll"),
                                            "all units at the as-of screen reference rent (a proxy, not the "
                                            "RERA index)")
    M["over_rent_share_of_income"] = metric(
        rr["over_rent_share_of_income"], "ratio", over_deps,
        f"in-place rent of units let more than {ctx.over_rent_threshold:.0%} above the screen reference rent "
        f"/ in-place rent")
    M["over_rent_excess_at_expiry_aed"] = metric(
        rr["over_rent_excess_at_expiry"], "AED/yr", over_deps,
        "rent above the reference on those units: the cut if each resets to the reference at its next renewal "
        "or expiry (not today)")
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
    M["commercial_income_share_year1"] = metric(L["commercial_income_share"][0], "ratio", refs("rent_model"),
                                                "retail rent / total rent; sets the recoverable share of input VAT")
    M["input_vat_recovered_year1"] = metric(L["input_vat_recovered"][0], "AED/yr", dep_noi)

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
    M["going_in_net_yield_on_price"] = metric(noi1 / ctx.price, "ratio", refs("noi", "price"),
                                              "same as entry_yield_on_price")
    M["going_in_net_yield_on_cost"] = metric(noi1 / total_cost, "ratio", refs("noi", "acquisition", "mortgage_registration"),
                                             "Year-1 NOI / (price + acquisition costs)")
    M["security_deposits_aed"] = metric(ctx.security_deposits, "AED",
                                        refs(extra=("deal.security_deposits_aed",)) if ctx.security_deposits is not None
                                        else refs(extra=("deal.units",)),
                                        "tenant deposits the buyer assumes: credited by the seller at closing; "
                                        "a liability, not income" if ctx.security_deposits is not None
                                        else "not stated")

    # ---- debt (secondary: sized to cover, not to lift returns) ----------------------------
    sz = cap["sizing"]
    M["loan_aed"] = metric(cap["loan"], "AED", refs("loan"),
                           f"lower of max LTV and the loan Year-1 NOI covers at the sizing DSCR; "
                           f"binding: {sz['sizing_constraint']}")
    M["ltv"] = metric(cap["loan"] / ctx.price, "ratio", refs("loan"))
    M["interest_rate"] = metric(ctx.interest_rate, "ratio/yr", refs("interest_rate"),
                                ctx.rate_note or "3M EIBOR + margin, held flat")
    M["annual_debt_service_aed"] = metric(cap["debt_service_year1"], "AED/yr", dep_debt,
                                          "level annual payment, amortising")
    M["arrangement_fee_aed"] = metric(cap["arrangement_fee"], "AED", refs("arrangement_fee"))
    M["equity_aed"] = metric(cap["equity"], "AED", refs("acquisition", "mortgage_registration", "arrangement_fee"),
                             "price + acquisition costs + arrangement fee - loan")
    M["dscr_year1"] = metric(cap["dscr_year1"], "x", refs("noi", "debt_service"),
                             "Year-1 NOI / Year-1 debt service; at least the sizing DSCR by construction")
    M["icr_year1"] = metric(cap["icr_year1"], "x", refs("noi", "debt_service"), "Year-1 NOI / Year-1 interest")
    M["debt_yield_year1"] = metric(cap["debt_yield_year1"], "ratio", refs("noi", "loan"))

    # breakeven occupancy for DSCR 1.0 (Year 1)
    pgi = L["potential_rental_income"][0] + L["other_income"][0]
    vat_cost_rate = ctx.vat_on_opex * (1.0 - L["commercial_income_share"][0])
    fixed = L["operating_expenses"][0] + L["leasing_fees"][0] * (1 + vat_cost_rate)
    if not ctx.opex_includes_vat:
        fixed += vat_cost_rate * sum(ops.opex_lines[line.category][0] for line in ctx.opex if line.vatable)
    variable_margin = (1 - ctx.collection_loss) * (1 - ctx.management_pct * (1 + vat_cost_rate))
    breakeven = (fixed + cap["debt_service_year1"]) / (pgi * variable_margin) if pgi > 0 else None
    M["breakeven_occupancy_dscr_1"] = metric(
        breakeven, "ratio", refs("noi", "debt_service"),
        "economic occupancy of Year-1 potential income at which NOI equals debt service")
    M["economic_occupancy_year1"] = metric(
        (L["gross_income"][0] - L["structural_vacancy"][0]) / pgi if pgi > 0 else None, "ratio",
        refs("egi"), "income after downtime and structural vacancy / potential income")

    # ---- exit and secondary returns --------------------------------------------------------------
    M["forward_noi_aed"] = metric(cap["forward_noi"], "AED/yr", dep_noi, f"NOI of year {hold + 1}")
    M["gross_exit_value_aed"] = metric(cap["gross_exit_value"], "AED", dep_exit)
    M["net_sale_proceeds_aed"] = metric(cap["net_sale_proceeds"], "AED", dep_exit, "after selling costs")
    M["loan_balance_at_exit_aed"] = metric(cap["loan_balance_at_exit"], "AED", dep_debt)
    M["exit_gain_levered_aed"] = metric(cap["exit_gain_levered"], "AED", dep_lev + dep_tax,
                                        "net sale proceeds - (price + acquisition costs); taxed in the sale year")
    M["levered_irr_pre_tax"] = metric(cap["levered_irr_pre_tax"], "ratio", dep_lev, "secondary: levered")
    M["levered_equity_multiple_pre_tax"] = metric(cap["levered_equity_multiple_pre_tax"], "x", dep_lev,
                                                  "secondary: levered")
    for key, deps in (("unlevered", dep_unlev), ("levered", dep_lev)):
        dd = deps + [r for r in dep_tax if r not in deps]
        for name, unit in ((f"{key}_irr_post_tax", "ratio"), (f"{key}_equity_multiple_post_tax", "x")):
            M[name] = metric(cap[name], unit, dd, indicative)
            M[name]["indicative"] = True

    # ---- walk-away price -------------------------------------------------------------------------
    wa = solve_walk_away_price(ctx, ops)
    dep_wa = refs("noi", "exit", "acquisition", "target_irr")
    walk_away: dict[str, Any] = {
        "price_aed": metric(wa["price"], "AED", dep_wa,
                            f"highest price on a AED {WALK_AWAY_STEP_AED:,} grid meeting the target unlevered "
                            f"IRR (pre-tax); the exit yield follows the price through the entry yield"),
    }
    if wa["price"] is not None:
        at, above = wa["at"], wa["above"]
        ws = walk_away_sensitivity(ctx, ops, wa["price"])
        walk_away.update({
            "binding_constraint": wa["binding"],
            "target_unlevered_irr": metric(ctx.target_unlevered_irr, "ratio", refs("target_irr")),
            "unlevered_irr_at_price": metric(at["unlevered_irr_pre_tax"], "ratio", dep_wa),
            "unlevered_irr_one_step_above": metric(above["unlevered_irr_pre_tax"], "ratio", dep_wa),
            "exit_yield_at_price": metric(at["exit_yield"], "ratio", dep_wa),
            "discount_to_asking": metric(1 - wa["price"] / ctx.price, "ratio", dep_wa + dep_price),
            "going_in_net_yield_on_cost_at_price": metric(
                noi1 / (wa["price"] + at["acquisition_costs"]["total"]), "ratio", dep_wa + refs("debt_service")),
            "loan_at_price": metric(at["loan"], "AED", dep_wa + refs("loan")),
            "dscr_at_price": metric(at["dscr_year1"], "x", dep_wa + refs("debt_service")),
            "levered_irr_at_price": metric(at["levered_irr_pre_tax"], "ratio", dep_wa + dep_lev),
            "sensitivity": {
                "depends_on": dep_wa,
                "unit": "AED",
                "cases": ws["cases"],
            },
            "most_sensitive_assumption": ws["most_sensitive_assumption"],
            "most_sensitive_label": ws["most_sensitive_label"],
            "largest_swing_aed": metric(ws["largest_swing_aed"], "AED", dep_wa,
                                        "largest change in the walk-away price across the four cases"),
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
                "unlevered_irr_pre_tax": c["unlevered_irr_pre_tax"],
                "unlevered_equity_multiple_pre_tax": c["unlevered_equity_multiple_pre_tax"],
                "dscr_year1": c["dscr_year1"],
                "levered_irr_pre_tax": c["levered_irr_pre_tax"],
                "levered_equity_multiple_pre_tax": c["levered_equity_multiple_pre_tax"],
            })
    sensitivity = {
        "rent_shifts": list(SENSITIVITY_RENT_SHIFTS),
        "exit_yield_shifts_bps": list(SENSITIVITY_EXIT_YIELD_SHIFTS_BPS),
        "note": "rent shift scales every year's reference rent level; in-place rents are unchanged until they "
                "roll; the exit shift is added on top of the exit yield rule; debt is re-sized in each cell",
        "units": {"rent_shift": "ratio", "exit_yield": "ratio", "noi_year1": "AED/yr",
                  "unlevered_irr_pre_tax": "ratio", "unlevered_equity_multiple_pre_tax": "x",
                  "dscr_year1": "x", "levered_irr_pre_tax": "ratio", "levered_equity_multiple_pre_tax": "x"},
        "depends_on": dep_lev,
        "cells": cells,
    }

    # ---- debt summary and amortisation sensitivity ------------------------------------------------
    debt_cases = []
    for years in [ctx.amortisation_years] + ([ctx.amortisation_years_sensitivity]
                                             if ctx.amortisation_years_sensitivity else []):
        c = cap if years == ctx.amortisation_years else run_capital(ctx, ops, ctx.price, amortisation_years=years)
        debt_cases.append({
            "amortisation_years": years, "base": years == ctx.amortisation_years,
            "loan_aed": c["loan"], "sizing_constraint": c["sizing"]["sizing_constraint"],
            "annual_debt_service_aed": c["debt_service_year1"], "dscr_year1": c["dscr_year1"],
            "levered_irr_pre_tax": c["levered_irr_pre_tax"],
            "levered_equity_multiple_pre_tax": c["levered_equity_multiple_pre_tax"],
        })
    debt_dep_names = list(d["loan"])
    if ctx.amortisation_years_sensitivity:
        debt_dep_names.append("mandate.underwriting.debt.amortisation_years_sensitivity")
    debt = {
        "sizing_constraint": sz["sizing_constraint"],
        "max_ltv": metric(ctx.max_ltv, "ratio", reg.refs(["mandate.underwriting.debt.max_ltv"])),
        "sizing_dscr": metric(ctx.sizing_dscr, "x", reg.refs(["mandate.underwriting.debt.sizing_dscr"])),
        "loan_at_max_ltv_aed": metric(sz["loan_at_max_ltv"], "AED", refs("loan")),
        "loan_at_sizing_dscr_aed": metric(sz["loan_at_sizing_dscr"], "AED", refs("loan")),
        "loan_constant": metric(sz["loan_constant"], "ratio/yr", refs("interest_rate"),
                                f"annual payment per AED of loan over {sz['amortisation_years']} years"),
        "amortisation_years": sz["amortisation_years"],
        "rate_note": ctx.rate_note,
        "amortisation_sensitivity": {"depends_on": reg.refs(debt_dep_names), "cases": debt_cases},
    }

    # ---- exit summary -----------------------------------------------------------------------------
    ex = cap["exit"]
    exit_block = {
        "rule": ctx.exit_yield_rule,
        "entry_yield_on_price": metric(ex["entry_yield_on_price"], "ratio", refs("noi", "price")),
        "area_house_view": metric(ex["area_house_view"], "ratio",
                                  reg.refs([f"mandate.underwriting.market_view.exit_net_yield_by_area.{ctx.area}"])),
        "base_source": ex["base_source"],
        "expansion_bps": ex["expansion_bps"],
        "age_premium_bps": ex["age_premium_bps"],
        "age_premium_rule": ctx.exit_age_premium_rule,
        "building_age_at_exit": ctx.building_age_at_exit,
        "exit_yield": metric(ex["exit_yield"], "ratio", dep_exit),
        "summary": (f"Buy at {ex['entry_yield_on_price']:.2%} (Year-1 NOI on price); exit at {ex['exit_yield']:.2%} = "
                    f"max(area {ex['area_house_view']:.2%}, entry {ex['entry_yield_on_price']:.2%}) "
                    f"+ {ex['expansion_bps']:.0f} bps expansion + {ex['age_premium_bps']:.0f} bps age premium"
                    + ("" if ctx.building_age_at_exit is not None else " (building age unknown)") + "."),
    }

    # ---- acquisition cost breakdown and closing adjustments -----------------------------------------
    a = cap["acquisition_costs"]
    dep_tr = refs("acquisition")
    dep_mr = refs("mortgage_registration")
    acq_out = {k: metric(a[k], "AED", dep_mr if k == "mortgage_registration" else dep_tr)
               for k in ("dld_transfer_fee", "dld_admin", "trustee_fee", "broker_fee", "broker_fee_vat",
                         "mortgage_registration", "transfer_costs")}
    acq_out["total"] = metric(a["total"], "AED", dep_acq)
    closing_adjustments = {
        "security_deposits_aed": M["security_deposits_aed"],
        "note": "tenant security deposits pass to the buyer as a liability; the seller credits them at closing. "
                "Shown for the closing statement only: not in NOI, cost or returns.",
    }

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
        "leasing_fees_modelled": refs("rent_model"), "leasing_fees": refs("rent_model", "opex"),
        "commercial_income_share": refs("rent_model"),
        "input_vat_gross": dep_noi, "input_vat_recovered": dep_noi, "input_vat": dep_noi,
        "total_operating_costs": dep_noi, "noi": dep_noi,
    }
    cash_flow = {
        "unit": "AED",
        "years": years,
        "period_start": [s.isoformat() for s in starts],
        "period_end": [e.isoformat() for e in ends],
        "in_hold": [y <= hold for y in years],
        "lines": {k: series(v, line_deps[k], "ratio" if k == "commercial_income_share" else None)
                  for k, v in L.items()},
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
            "unlevered_post_tax": series(cap["cash_flows"]["unlevered_post_tax"], dep_unlev + dep_tax, indicative),
            "levered_pre_tax": series(cap["cash_flows"]["levered_pre_tax"], dep_lev,
                                      "year 0: equity; final year includes net sale less loan repayment"),
            "levered_post_tax": series(cap["cash_flows"]["levered_post_tax"], dep_lev + dep_tax, indicative),
            "tax_unlevered": series([0.0] + cap["tax_unlevered"], dep_noi + dep_tax, indicative),
            "tax_levered": series([0.0] + cap["tax_levered"], dep_lev + dep_tax,
                                  "taxable income = NOI - interest - arrangement fee amortisation; "
                                  "final year adds the exit gain; " + indicative),
        },
    }

    unit_rows = []
    for u, ref, sched, path in zip(ctx.units, ctx.unit_market_rent_ref, ops.unit_schedules,
                                   ops.unit_reference_rent_by_year):
        let = u.status in OCCUPIED_STATUSES
        unit_rows.append({
            "unit": u.unit, "unit_type": u.unit_type, "area_sqft": u.area_sqft, "status": u.status,
            "in_place_rent_aed": u.annual_rent_aed if let else None,
            "screen_reference_rent_aed": ref,
            "rent_vs_reference": (u.annual_rent_aed / ref - 1) if let and u.annual_rent_aed and ref else None,
            "expiry_month": u.expiry_month,
            "reference_rent_by_year": path,
            "expected_rent_by_year": [sum(sched.rent[12 * y: 12 * y + 12]) for y in range(hold + 1)],
            "events": sched.events,
        })
    unit_schedule = {"depends_on": refs("rent_model"), "units": unit_rows,
                     "note": "expected value over renewal and turnover outcomes; RERA bands apply to each renewing "
                             "tenant's own rent; months counted from the analysis start"}

    # The OM check registers its own inputs, so it runs before the registry is copied out.
    om_check = _om_yield_check(ctx, noi1, cap, refs) if ctx.om_stated else None

    result: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "deal_id": ctx.deal_id,
        "analysis_start": ctx.analysis_start.isoformat(),
        "hold_years": hold,
        "decision_basis": "unlevered, pre-tax",
        "headline": list(HEADLINE_METRICS),
        "inputs": reg.as_dict(),
        "metrics": M,
        "exit": exit_block,
        "debt": debt,
        "acquisition_costs": acq_out,
        "closing_adjustments": closing_adjustments,
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
    novated = bool(ctx.rent_roll)
    return {
        "tenant": ml.tenant,
        "related_party": ml.related_party,
        "annual_rent_aed": metric(ml.annual_rent_aed, "AED/yr", refs("master_lease")),
        "lease_end": ml.lease_end,
        "cheques": ml.cheques,
        "reversion_month": ml.reversion_month,
        "reversion_date": reversion.isoformat(),
        "reversion_basis": "novation" if novated else "all_turnover",
        "note": ("income is the master rent until reversion; then the sub-tenancies novate: let units keep their "
                 "sub-let rent to their own lease end and then roll; vacant units lease up after the downtime"
                 if novated else
                 "income is the master rent until reversion; with no unit data every unit is assumed to turn over "
                 "and let at the reference after the downtime"),
    }
