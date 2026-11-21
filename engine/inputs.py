"""Validate ``deal_inputs`` and gather every assumption a run needs into a context.

The context holds plain numbers for the calculation and an :class:`InputRegistry`
that records each of them with its provenance. See engine/README.md for the
``deal_inputs`` schema.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .finance import expiry_month_index, is_finite_number, parse_date
from .leases import (OCCUPIED_STATUSES, PHYSICALLY_LET_STATUSES, UNIT_STATUSES, LeaseAssumptions,
                     UnitLease)
from .provenance import PROVENANCE_TAGS, InputRegistry

# Expense categories of the chart of accounts in docs/DESIGN.md.
OPEX_CATEGORIES = (
    "service_charge", "district_cooling", "utilities_common", "property_management",
    "maintenance_repairs", "insurance", "security_cleaning", "marketing_leasing",
    "admin_other", "sinking_fund",
)
# The mandate's default for district cooling is keyed with this suffix and applies
# only when the landlord pays for chilled water (a "chiller-free" building).
LANDLORD_PAYS_SUFFIX = "_if_landlord_pays"
# Categories exempt from input VAT: a reserve contribution is not a purchase of services.
VAT_EXEMPT_CATEGORIES = ("sinking_fund",)

ALLOWED_TOP_LEVEL = {
    "deal_id", "price_aed", "area", "nsa_sqft", "bua_sqft", "units", "opex_aed",
    "opex_includes_vat", "other_income_aed", "chiller_landlord_pays", "om_stated",
    "provenance", "master_lease",
}


class DealInputError(ValueError):
    """``deal_inputs`` does not match the documented schema."""


class MarketDataError(ValueError):
    """The reference data has no entry the deal needs (for example its area)."""


@dataclass(frozen=True)
class MasterLease:
    """A master (bulk) lease of the whole building to one tenant."""

    tenant: str | None
    related_party: bool | None
    annual_rent_aed: float
    lease_end: str
    reversion_month: int             # analysis month in which the units revert to the owner
    cheques: int | None
    registry_names: list[str]


def _parse_master_lease(raw: Any, analysis_start: dt.date, reg: InputRegistry,
                        deal_tag) -> MasterLease | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DealInputError("master_lease must be a dict or null")
    bad = set(raw) - {"tenant", "related_party", "annual_rent_aed", "lease_end", "cheques"}
    if bad:
        raise DealInputError(f"master_lease has unknown fields {sorted(bad)}")
    rent = _num(raw.get("annual_rent_aed"), "master_lease.annual_rent_aed", positive=True)
    if raw.get("lease_end") in (None, ""):
        raise DealInputError("master_lease.lease_end is required")
    end = parse_date(raw["lease_end"], "master_lease.lease_end")
    related = raw.get("related_party")
    if related is not None and not isinstance(related, bool):
        raise DealInputError("master_lease.related_party must be true, false or null")
    cheques = raw.get("cheques")
    if cheques is not None and (not is_finite_number(cheques) or cheques <= 0):
        raise DealInputError("master_lease.cheques must be a positive number")
    tag = deal_tag("master_lease")
    names = [
        reg.add("deal.master_lease.annual_rent_aed", rent, "AED/yr", tag),
        reg.add("deal.master_lease.lease_end", end.isoformat(), "date", tag),
    ]
    reg.add("deal.master_lease.tenant", raw.get("tenant"), "text", tag)
    reg.add("deal.master_lease.related_party", related, "bool", tag,
            "unstated" if related is None else None)
    if cheques is not None:
        reg.add("deal.master_lease.cheques", cheques, "count", tag)
    return MasterLease(tenant=raw.get("tenant"), related_party=related, annual_rent_aed=rent,
                       lease_end=end.isoformat(), reversion_month=expiry_month_index(end, analysis_start),
                       cheques=int(cheques) if cheques is not None else None, registry_names=names)


@dataclass
class OpexLine:
    category: str
    amount: float
    provenance: str
    vatable: bool
    note: str | None = None
    from_reversion: bool = False      # default line under a master lease: owner bears it only after reversion


@dataclass
class Context:
    """Everything one underwriting run needs, already validated."""

    registry: InputRegistry
    deal_id: str | None
    price: float
    area: str                         # canonical area key in the market file
    nsa_sqft: float
    bua_sqft: float | None
    units: list[UnitLease]            # units as the lease model runs them
    rent_roll: list[UnitLease]        # units as stated (empty if a master lease has no rent roll)
    master_lease: MasterLease | None
    unit_market_rent_ref: list[float]  # as-of market reference rent per unit (no growth)
    opex: list[OpexLine]
    opex_includes_vat: bool
    other_income: float
    opex_growth: float
    other_income_growth: float
    chiller_landlord_pays: bool | None
    om_stated: dict | None
    analysis_start: dt.date
    hold_years: int
    lease: LeaseAssumptions
    growth_index: list[float]         # cumulative market-rent index by year, len hold + 1
    structural_vacancy: float
    collection_loss: float
    management_pct: float
    vat_on_opex: float
    acq: dict[str, float]
    ltv: float
    interest_rate: float
    amortisation_years: int
    arrangement_fee_pct: float
    exit_yield: float                 # area exit yield plus expansion
    selling_costs_pct: float
    tax_rate: float
    tax_threshold: float
    dscr_floor: float
    target_levered_irr: float
    warnings: list[str] = field(default_factory=list)
    # names of registry entries, grouped for depends_on lists
    deps: dict[str, list[str]] = field(default_factory=dict)


def _num(value: Any, name: str, *, positive: bool = False, allow_none: bool = False) -> float | None:
    if value is None:
        if allow_none:
            return None
        raise DealInputError(f"{name} is required")
    if not is_finite_number(value):
        raise DealInputError(f"{name} must be a number, got {value!r}")
    if positive and value <= 0:
        raise DealInputError(f"{name} must be positive, got {value!r}")
    return float(value)


def _canonical_key(value: str, options: list[str], name: str) -> str:
    """Match ``value`` to one of ``options``, ignoring case, spaces, '-' and '_'."""
    def squash(s: str) -> str:
        return "".join(ch for ch in str(s).lower() if ch not in " -_")
    lookup = {squash(o): o for o in options}
    key = lookup.get(squash(value))
    if key is None:
        raise DealInputError(f"{name}: {value!r} is not one of {sorted(options)}")
    return key


def _mandate_value(mandate: dict, path: str) -> Any:
    node: Any = mandate
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"mandate is missing {path}")
        node = node[part]
    return node


def _parse_unit(i: int, u: Any, factors: dict, analysis_start: dt.date, warnings: list[str],
                rent_required: bool) -> UnitLease:
    """Validate one rent-roll row. ``rent_required`` is off under a master lease."""
    label = f"units[{i}]"
    if not isinstance(u, dict):
        raise DealInputError(f"{label} must be a dict")
    unit_type = _canonical_key(u.get("unit_type", ""), list(factors), f"{label}.unit_type")
    area_sqft = _num(u.get("area_sqft"), f"{label}.area_sqft", positive=True)
    status = _canonical_key(u.get("status", ""), list(UNIT_STATUSES), f"{label}.status")
    rent = _num(u.get("annual_rent_aed"), f"{label}.annual_rent_aed", allow_none=True)
    unit_id = str(u.get("unit", i + 1))
    expiry: int | None = None
    if status in PHYSICALLY_LET_STATUSES and u.get("lease_end") not in (None, ""):
        expiry = expiry_month_index(parse_date(u["lease_end"], f"{label}.lease_end"), analysis_start)
    if status in OCCUPIED_STATUSES and rent_required:
        if rent is None or rent <= 0:
            raise DealInputError(f"{label}.annual_rent_aed is required for a {status} unit")
        if expiry is None:
            expiry = 0
            warnings.append(f"Unit {unit_id}: occupied with no lease end; treated as expiring "
                            f"at the start of the analysis.")
    return UnitLease(unit=unit_id, unit_type=unit_type, area_sqft=area_sqft, status=status,
                     annual_rent_aed=rent, expiry_month=expiry)


def build_context(deal_inputs: dict, mandate: dict, market: dict) -> Context:
    """Validate the inputs and build the run context with a provenance registry."""
    if not isinstance(deal_inputs, dict):
        raise DealInputError("deal_inputs must be a dict")
    unknown = set(deal_inputs) - ALLOWED_TOP_LEVEL
    if unknown:
        raise DealInputError(f"unknown deal_inputs fields: {sorted(unknown)}")

    reg = InputRegistry()
    warnings: list[str] = []
    deps: dict[str, list[str]] = {}

    tags = deal_inputs.get("provenance") or {}
    for key, tag in tags.items():
        if tag not in PROVENANCE_TAGS:
            raise DealInputError(f"provenance[{key!r}]: {tag!r} is not one of {PROVENANCE_TAGS}")

    def deal_tag(key: str) -> str:
        return tags.get(key, "document")

    def m(path: str, unit: str, note: str | None = None) -> tuple[Any, str]:
        """Read a mandate value and register it; returns (value, registry name)."""
        value = _mandate_value(mandate, path)
        return value, reg.add(f"mandate.{path}", value, unit, "mandate", note)

    # ---- deal facts -----------------------------------------------------------------
    price = _num(deal_inputs.get("price_aed"), "price_aed", positive=True)
    reg.add("deal.price_aed", price, "AED", deal_tag("price_aed"))

    areas = market.get("areas") or {}
    area_raw = deal_inputs.get("area")
    if not area_raw:
        raise DealInputError("area is required")
    try:
        area = _canonical_key(area_raw, list(areas), "area")
    except DealInputError as exc:
        raise MarketDataError(f"no market reference data for area {area_raw!r}; "
                              f"known areas: {sorted(areas)}") from exc
    reg.add("deal.area", area, "text", deal_tag("area"))

    nsa = _num(deal_inputs.get("nsa_sqft"), "nsa_sqft", positive=True)
    reg.add("deal.nsa_sqft", nsa, "sqft", deal_tag("nsa_sqft"))
    bua = _num(deal_inputs.get("bua_sqft"), "bua_sqft", positive=True, allow_none=True)
    reg.add("deal.bua_sqft", bua, "sqft", deal_tag("bua_sqft"),
            None if bua is not None else "not stated")

    # ---- mandate: timing and leasing ---------------------------------------------------
    hold_years, n_hold = m("underwriting.hold_years", "years")
    hold_years = int(hold_years)
    start_raw, n_start = m("underwriting.analysis_start", "date")
    analysis_start = parse_date(start_raw, "mandate underwriting.analysis_start")
    if analysis_start.day != 1:
        raise ValueError("mandate underwriting.analysis_start must be the first of a month")

    ops = "underwriting.operations"
    p_renew, n_p = m(f"{ops}.renewal_probability", "ratio")
    downtime, n_dt = m(f"{ops}.downtime_months_on_turnover", "months")
    fee_months, n_fee = m(f"{ops}.leasing_fee_months_on_turnover", "months")
    bands_raw, n_bands = m("underwriting.rera.increase_bands", "bands")
    bands = tuple(sorted((float(b["below_index_up_to"]), float(b["max_increase"])) for b in bands_raw))
    notice_days, n_notice = m("underwriting.rera.notice_days_for_change", "days")
    months_total = (hold_years + 1) * 12
    lease = LeaseAssumptions(
        renewal_probability=float(p_renew), downtime_months=float(downtime),
        leasing_fee_months=float(fee_months), rera_bands=bands,
        notice_months=float(notice_days) / (365.0 / 12.0), months=months_total,
    )

    # ---- market rent reference -------------------------------------------------------------
    area_data = areas[area]
    base_psf = area_data.get("market_rent_aed_psf_1br")
    if not is_finite_number(base_psf) or base_psf <= 0:
        raise MarketDataError(f"areas.{area}.market_rent_aed_psf_1br is missing")
    srcs = area_data.get("sources") or []
    n_base = reg.add(f"market.areas.{area}.market_rent_aed_psf_1br", float(base_psf), "AED/sqft/yr",
                     "market", "; ".join(srcs) if srcs else None)
    if any("UNVERIFIED" in str(s).upper() for s in srcs):
        warnings.append(f"Market reference rent for {area} is marked UNVERIFIED in areas.yaml.")
    factors = market["unit_type_factors"]
    n_factors = reg.add("market.unit_type_factors", dict(factors), "ratio", "market")

    growth_table = _mandate_value(mandate, "underwriting.market_view.rent_growth_by_year")
    growth_key = area if area in growth_table else "default"
    growth = [float(g) for g in growth_table[growth_key]]
    note = None
    if len(growth) < hold_years + 1:
        note = (f"path has {len(growth)} years; year(s) {len(growth) + 1}-{hold_years + 1} "
                f"repeat the last value ({growth[-1]:+.2%})")
        growth = growth + [growth[-1]] * (hold_years + 1 - len(growth))
    n_growth = reg.add(f"mandate.underwriting.market_view.rent_growth_by_year.{growth_key}",
                       growth[: hold_years + 1], "ratio/yr", "mandate", note)
    growth_index = []
    level = 1.0
    for g in growth[: hold_years + 1]:
        level *= 1.0 + g
        growth_index.append(level)

    # ---- units ------------------------------------------------------------------------
    # ---- master lease (optional) -------------------------------------------------------
    master = _parse_master_lease(deal_inputs.get("master_lease"), analysis_start, reg, deal_tag)
    deps["master_lease"] = master.registry_names if master else []

    # ---- units ------------------------------------------------------------------------
    raw_units = deal_inputs.get("units")
    if master is None and (not isinstance(raw_units, list) or not raw_units):
        raise DealInputError("units must be a non-empty list of rent-roll units")
    if raw_units is not None and not isinstance(raw_units, list):
        raise DealInputError("units must be a list of rent-roll units")
    rent_roll: list[UnitLease] = []
    for i, u in enumerate(raw_units or []):
        rent_roll.append(_parse_unit(i, u, factors, analysis_start, warnings,
                                     rent_required=master is None))
    if rent_roll:
        reg.add("deal.units", len(rent_roll), "units", deal_tag("units"),
                "rent-roll rows: unit_type, area_sqft, status, annual_rent_aed, lease_end"
                + ("; used only after the master lease reverts" if master else ""))
        unit_area_total = sum(u.area_sqft for u in rent_roll)
        if abs(unit_area_total - nsa) / nsa > 0.02:
            warnings.append(f"Sum of unit areas ({unit_area_total:,.0f} sqft) differs from NSA "
                            f"({nsa:,.0f} sqft) by more than 2%.")
    if master is None:
        units = rent_roll
    else:
        # On reversion every unit turns over: vacant from the reversion month, then let at
        # market after the downtime.
        basis = rent_roll
        if not rent_roll:
            basis = [UnitLease(unit="NSA", unit_type="1br", area_sqft=nsa, status="vacant",
                                   annual_rent_aed=None, expiry_month=None)]
            reg.add("deal.units", 1, "units", "default",
                    "no rent roll: after reversion the whole NSA is modelled as 1BR-equivalent space")
            if master.reversion_month < (hold_years + 1) * 12:
                warnings.append("Master lease reverts inside the model horizon and there is no rent roll; "
                                "the whole NSA is modelled as 1BR-equivalent space after reversion.")
        units = [UnitLease(unit=u.unit, unit_type=u.unit_type, area_sqft=u.area_sqft, status="vacant",
                           annual_rent_aed=None, expiry_month=None, available_month=master.reversion_month)
                 for u in basis]
    ref_rents = [float(base_psf) * float(factors[u.unit_type]) * u.area_sqft for u in units]

    # ---- income and operations -----------------------------------------------------------
    other_income = _num(deal_inputs.get("other_income_aed", 0.0), "other_income_aed",
                        allow_none=True) or 0.0
    n_other = reg.add("deal.other_income_aed", other_income, "AED/yr",
                      deal_tag("other_income_aed") if "other_income_aed" in deal_inputs else "default",
                      None if "other_income_aed" in deal_inputs else "not stated; taken as 0")
    vac, n_vac = m(f"{ops}.structural_vacancy", "ratio")
    coll, n_coll = m(f"{ops}.collection_loss", "ratio")
    mgmt, n_mgmt = m(f"{ops}.property_management_pct_of_egi", "ratio")
    vat, n_vat = m(f"{ops}.input_vat_on_opex_pct", "ratio")
    opex_growth, n_opex_g = m(f"{ops}.opex_growth", "ratio/yr", "applied from year 2; year 1 is the stated budget")
    other_growth, n_other_g = m(f"{ops}.other_income_growth", "ratio/yr", "applied from year 2")

    chiller = deal_inputs.get("chiller_landlord_pays")
    if chiller is not None and not isinstance(chiller, bool):
        raise DealInputError("chiller_landlord_pays must be true, false or null")
    n_chiller = reg.add("deal.chiller_landlord_pays", chiller, "bool",
                        deal_tag("chiller_landlord_pays"),
                        "unstated: district cooling default applied (conservative)" if chiller is None else None)
    if chiller is None:
        warnings.append("Chiller arrangement unstated; the district cooling default is applied.")
    opex_includes_vat = bool(deal_inputs.get("opex_includes_vat", False))
    n_opex_vat = reg.add("deal.opex_includes_vat", opex_includes_vat, "bool",
                         deal_tag("opex_includes_vat") if "opex_includes_vat" in deal_inputs else "default",
                         None if "opex_includes_vat" in deal_inputs else "not stated; stated opex taken as net of VAT")

    stated = deal_inputs.get("opex_aed") or {}
    if not isinstance(stated, dict):
        raise DealInputError("opex_aed must be a dict of chart-of-accounts category -> AED per year")
    bad = set(stated) - set(OPEX_CATEGORIES)
    if bad:
        raise DealInputError(f"opex_aed has unknown categories {sorted(bad)}; allowed: {list(OPEX_CATEGORIES)}")
    defaults_raw = _mandate_value(mandate, f"{ops}.opex_defaults_aed_per_sqft_nsa")
    defaults: dict[str, tuple[float, bool, str]] = {}
    for key, rate in defaults_raw.items():
        conditional = key.endswith(LANDLORD_PAYS_SUFFIX)
        cat = key[: -len(LANDLORD_PAYS_SUFFIX)] if conditional else key
        defaults[cat] = (float(rate), conditional, key)

    opex: list[OpexLine] = []
    opex_names: list[str] = []
    for cat in OPEX_CATEGORIES:
        if cat == "property_management":
            if stated.get(cat) is not None:
                reg.add(f"deal.opex_aed.{cat}", float(stated[cat]), "AED/yr", deal_tag(f"opex_aed.{cat}"),
                        "stated but not used: the mandate management fee on EGI applies")
            continue
        value = stated.get(cat)
        name = f"deal.opex_aed.{cat}"
        vatable = cat not in VAT_EXEMPT_CATEGORIES
        if value is not None:
            amount = _num(value, f"opex_aed.{cat}")
            opex.append(OpexLine(cat, amount, deal_tag(f"opex_aed.{cat}"), vatable))
            reg.add(name, amount, "AED/yr", deal_tag(f"opex_aed.{cat}"))
            opex_names.append(name)
            continue
        if cat in defaults:
            rate, conditional, key = defaults[cat]
            rate_name = reg.add(f"mandate.{ops}.opex_defaults_aed_per_sqft_nsa.{key}", rate,
                                "AED/sqft NSA/yr", "mandate")
            if conditional and chiller is False:
                continue
            amount = rate * nsa
            ml_note = "; under the master lease the operator bears it, so it applies from reversion" if master else ""
            opex.append(OpexLine(cat, amount, "default", vatable,
                                 f"{rate} AED/sqft x {nsa:,.0f} sqft NSA{ml_note}", from_reversion=master is not None))
            reg.add(name, amount, "AED/yr", "default",
                    f"missing from the operating statement; mandate default {rate} AED/sqft NSA{ml_note}")
            opex_names += [name, rate_name]
        else:
            opex.append(OpexLine(cat, 0.0, "default", vatable, "no mandate default; taken as 0"))
            reg.add(name, 0.0, "AED/yr", "default", "not stated and no mandate default; taken as 0")
            opex_names.append(name)
    opex_names.append("deal.nsa_sqft")

    # ---- capital ----------------------------------------------------------------------
    acq_path = "underwriting.acquisition_costs"
    acq: dict[str, float] = {}
    acq_names = []
    for key, unit in (("dld_transfer_fee_pct", "ratio of price"), ("dld_admin_aed", "AED"),
                      ("trustee_fee_aed", "AED"), ("broker_fee_pct", "ratio of price"),
                      ("broker_fee_vat_pct", "ratio of broker fee"),
                      ("mortgage_registration_pct", "ratio of loan"),
                      ("mortgage_registration_admin_aed", "AED")):
        value, name = m(f"{acq_path}.{key}", unit)
        acq[key] = float(value)
        acq_names.append(name)
    debt = "underwriting.debt"
    ltv, n_ltv = m(f"{debt}.ltv", "ratio of price")
    base_rate, n_base_rate = m(f"{debt}.base_rate_3m_eibor", "ratio/yr")
    margin, n_margin = m(f"{debt}.margin", "ratio/yr")
    amort, n_amort = m(f"{debt}.amortisation_years", "years")
    arr_fee, n_arr = m(f"{debt}.arrangement_fee_pct", "ratio of loan")

    mv = "underwriting.market_view"
    exit_by_area = _mandate_value(mandate, f"{mv}.exit_net_yield_by_area")
    if area not in exit_by_area:
        raise MarketDataError(f"mandate has no exit yield for area {area!r}")
    n_exit = reg.add(f"mandate.{mv}.exit_net_yield_by_area.{area}", float(exit_by_area[area]),
                     "ratio", "mandate")
    expansion, n_exp = m(f"{mv}.exit_yield_expansion_bps", "bps")
    selling, n_sell = m(f"{mv}.selling_costs_pct", "ratio of gross sale price")
    tax_rate, n_tax = m("underwriting.tax.corporate_tax_rate", "ratio")
    tax_thr, n_thr = m("underwriting.tax.corporate_tax_threshold_aed", "AED/yr")
    reg.add("mandate.underwriting.tax.model", _mandate_value(mandate, "underwriting.tax.model"),
            "text", "mandate")
    dscr_floor, n_dscr = m("buy_box.hard.min_dscr_year1", "x")
    target_irr, n_tirr = m("buy_box.soft.target_levered_irr", "ratio")

    # ---- dependency groups -------------------------------------------------------------
    timing = [n_start, n_hold]
    rent_model = ["deal.units", "deal.area", n_base, n_factors, n_growth, n_p, n_dt, n_fee,
                  n_bands, n_notice] + timing
    rent_model = rent_model + deps["master_lease"]
    deps["rent_roll"] = ["deal.units", "deal.area", n_base, n_factors]
    deps["rent_model"] = rent_model
    deps["other_income"] = [n_other, n_other_g]
    deps["egi"] = rent_model + [n_other, n_other_g, n_vac, n_coll]
    deps["opex"] = opex_names + [n_chiller, n_opex_g] + deps["master_lease"]
    deps["vat"] = [n_vat, n_opex_vat]
    deps["management"] = [n_mgmt]
    deps["noi"] = deps["egi"] + [n_mgmt] + deps["opex"] + deps["vat"]
    deps["price"] = ["deal.price_aed"]
    deps["acquisition"] = ["deal.price_aed"] + acq_names[:5]
    deps["mortgage_registration"] = ["deal.price_aed", n_ltv] + acq_names[5:]
    deps["loan"] = ["deal.price_aed", n_ltv]
    deps["interest_rate"] = [n_base_rate, n_margin]
    deps["debt_service"] = deps["loan"] + [n_base_rate, n_margin, n_amort]
    deps["arrangement_fee"] = deps["loan"] + [n_arr]
    deps["exit"] = [n_exit, n_exp, n_sell]
    deps["tax"] = [n_tax, n_thr, "mandate.underwriting.tax.model"]
    deps["dscr_floor"] = [n_dscr]
    deps["target_irr"] = [n_tirr]

    return Context(
        registry=reg, deal_id=deal_inputs.get("deal_id"), price=price, area=area,
        nsa_sqft=nsa, bua_sqft=bua, units=units, rent_roll=rent_roll, master_lease=master,
        unit_market_rent_ref=ref_rents, opex=opex,
        opex_includes_vat=opex_includes_vat, other_income=other_income,
        opex_growth=float(opex_growth), other_income_growth=float(other_growth),
        chiller_landlord_pays=chiller, om_stated=deal_inputs.get("om_stated"),
        analysis_start=analysis_start, hold_years=hold_years, lease=lease,
        growth_index=growth_index, structural_vacancy=float(vac), collection_loss=float(coll),
        management_pct=float(mgmt), vat_on_opex=float(vat), acq=acq, ltv=float(ltv),
        interest_rate=float(base_rate) + float(margin), amortisation_years=int(amort),
        arrangement_fee_pct=float(arr_fee),
        exit_yield=float(exit_by_area[area]) + float(expansion) / 10000.0,
        selling_costs_pct=float(selling), tax_rate=float(tax_rate), tax_threshold=float(tax_thr),
        dscr_floor=float(dscr_floor), target_levered_irr=float(target_irr),
        warnings=warnings, deps=deps,
    )
