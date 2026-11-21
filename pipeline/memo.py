"""Stage 9, memo: the model writes from the fact sheet only; code checks every number.

**Fact sheet.** A flat dict ``{fact_id: {"value", "unit", "label", "source"}}`` built from
verified OM fields, the code-parsed rent roll and statement, engine outputs, mandate tests,
discrepancies and assumptions. Nothing else is shown to the model.

**Anchor syntax.** Every number in the memo is followed by ``[[fact_id]]``, e.g.
``AED 61.2m [[uw.walk_away_price_aed]]``. The site turns each anchor into a link to the fact,
and through the fact's ``source`` to the page, box or cell it came from.

**Check.** :func:`check_memo` finds every number (money with k/m/bn, %, x, bps, sq ft, counts,
years, dates, quarter labels), pairs it with the anchor that follows it (within a few
characters, with no other number in between), and compares it with the fact after rounding to
the precision written. A number anchored to a text fact must appear in that text. Exempt:
"Year 1", "T-12", unit types ("1BR"), floor codes ("G+4") and list markers.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

from .llm import ModelClient, ToolResult, load_prompt
from .numbers import parse_date, parse_numbers
from .schemas import MEMO_TOOL
from .verify import TRUSTED

ANCHOR_RE = re.compile(r"\[\[([A-Za-z0-9_.\-+]+)\]\]")
SNAKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
MAX_ANCHOR_GAP = 32

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
EXEMPT_RES = [
    re.compile(r"\b[Yy]ear[- ]?\d{1,2}\b"),
    re.compile(r"\bT-?12\b"),
    re.compile(r"\b(?:[BGMP]\+)+\d*[A-Z]?(?:\+\d+[A-Z]?)*"),
    re.compile(r"\b\d\s?(?:BR|B/R|BHK|[Bb]ed(?:room)?s?)\b"),
    re.compile(r"^\s*\d+[.)]\s", re.M),
    re.compile(r"^#+\s.*$", re.M),       # headings carry no figures
    re.compile(r"\b(?:Phase|District|Cluster|Barsha|Plot)\s\d+\b"),   # place names (JVC District 11, Al Barsha 1)
    re.compile(r"\b[Yy]ears?\s\d{1,2}\s?(?:to|-|–|and)\s?\d{1,2}\b"),  # "Years 1 to 5"
    re.compile(r"\b(?:3|12)-month\b"),
    re.compile(r"\b(?:within|over|in|for)\s(?:the\s)?(?:next\s)?12\smonths\b"),          # "within 12 months"
    re.compile(r"\b(?:in|through|during|by|until|across|from)\s20[23]\d\b(?![-/])"),    # calendar references
    re.compile(r"\b\dM\s(?:EIBOR|Eibor)\b"),
]
DATE_RES = [
    (re.compile(rf"\b\d{{1,2}}\s{_MONTH}\s\d{{4}}\b"), "day"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "day"),
    (re.compile(rf"\b{_MONTH}\s\d{{4}}\b"), "month"),
]
QUARTER_RE = re.compile(r"\b(?:(20\d\d)[- ]?Q([1-4])|Q([1-4])[ -](20\d\d))\b")
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<sign>[-−+])?(?P<cur>AED\s?)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>\s?(?:k|mn|m|million|bn|billion)\b)?"
    r"(?P<suf>\s?%|x\b|\s?bps\b|\s?(?:sq\.?\s?ft|sqft)\b|\s?pp\b|\s?(?:percentage\s)?points?\b)?"
)
_SCALES = {"k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


# ---------------------------------------------------------------------------- fact sheet

# Labels for engine metrics whose names carry digits or jargon a writer would copy into prose.
METRIC_WORDS = {
    "breakeven_occupancy_dscr_1": "occupancy at which Year-1 NOI just covers debt service",
    "dscr_year1": "Year-1 debt service cover (DSCR), secondary",
    "unlevered_irr_pre_tax": "unlevered IRR, pre-tax (the decision metric)",
    "unlevered_equity_multiple_pre_tax": "unlevered equity multiple, pre-tax",
    "levered_irr_pre_tax": "levered IRR, pre-tax (secondary)",
    "levered_equity_multiple_pre_tax": "levered equity multiple, pre-tax (secondary)",
    "exit_yield": "exit yield (house view: max of area yield and entry yield, plus expansion and age premium)",
    "walk_away_price_aed": "walk-away price: highest price meeting the unlevered IRR target (house view)",
    "icr_year1": "Year-1 interest cover",
    "noi_year1": "Year-1 NOI",
    "debt_yield_year1": "Year-1 debt yield",
    "max_expiry_share_quarter": "largest share of in-place rent expiring in one three-month window",
    "over_rent_share_of_income": "share of in-place rent from units let above market reference rent",
}


def _val(x: Any) -> Any:
    """An engine value that may be wrapped as a metric ``{"value": ...}``."""
    return x.get("value") if isinstance(x, dict) else x


def _fact(value: Any, unit: str, label: str, source: dict | None = None) -> dict:
    return {"value": value, "unit": unit, "label": label, "source": source}


DISCREPANCY_WORDS = {
    "occupancy_mismatch": "OM occupancy vs rent roll", "potential_rent_as_income": "OM income includes potential rent",
    "gross_yield_as_net": "gross yield called net", "yield_excludes_acquisition_costs": "yield before acquisition costs",
    "over_rented_vs_market": "units let above the screen reference", "upside_exceeds_rera_cap": "uplift claim beyond RERA bands",
    "missing_opex_items": "costs missing from the statement", "area_basis_confusion": "area basis",
    "rent_roll_does_not_foot": "rent roll totals do not add up", "unit_mix_mismatch": "unit mix differs",
    "expired_lease_counted_occupied": "expired or unregistered leases shown occupied", "collections_gap": "collections gap",
    "annualised_partial_period": "part-year statement presented as annual",
    "master_lease_related_party": "master lease", "expiry_concentration": "lease expiry concentration",
    "title_check": "title check", "other_om_claim": "other OM claim"}
RELIED_ON_WORDS = {"rent_roll": "the rent roll", "rent_roll_rows": "the rent roll's unit rows", "engine": "the engine",
                   "mandate_defaults": "mandate defaults", "operating_statement": "the operating statement",
                   "master_lease_then_sub_leases": "the master-lease rent to its expiry, then the sub-tenancies, "
                                                   "which novate to the owner",
                   "documents": "the documents",
                   "none": "nothing: legal must confirm"}

# OM fields that are cosmetic: an unverified one is not a diligence item.
COSMETIC_FIELDS = {"building_name", "floors", "plot_number", "parking_spaces", "area"}
HOUSE_VIEW_NOTE = ("The walk-away price and the returns rest on the firm's house view (screen reference rent path, "
                   "exit yield, vacancy and downtime), not on market evidence for this building.")


def build_fact_sheet(om: dict, rr: dict | None, opex: dict | None, uw: dict | None, fit: dict | None,
                     discrepancies: list[dict], mandate: dict, notes: list[str], notices: list[dict] = (),
                     diligence: list[dict] = (), bridge: dict | None = None) -> dict[str, dict]:
    """Flat fact sheet; only verified or computed values."""
    F: dict[str, dict] = {}

    def om_fact(key: str, name: str, unit: str, label: str, value: Any = None) -> None:
        f = om.get(name) or {}
        if f.get("status") in TRUSTED:
            s = f["source"]
            F[key] = _fact(f["value"] if value is None else value, unit, label,
                           {"kind": "document", "doc": s["doc"], "page": s["page"], "bbox": s.get("bbox"),
                            "quote": f.get("quote"), "status": f["status"]})

    om_fact("deal.building_name", "building_name", "text", "building name")
    om_fact("deal.location", "area", "text", "location as stated in the OM")
    om_fact("deal.market_area", "market_area", "text", "market area")
    om_fact("deal.completion_year", "completion_year", "year", "completion year")
    om_fact("deal.floors", "floors", "text", "floors")
    om_fact("deal.asking_price_aed", "asking_price_aed", "AED", "asking price")
    om_fact("om.unit_count", "unit_count", "units", "unit count stated in the OM")
    om_fact("om.nsa_sqft", "nsa_sqft", "sqft", "NSA stated in the OM (sq ft)")
    om_fact("deal.bua_sqft", "bua_sqft", "sqft", "BUA stated in the OM (sq ft)")
    om_fact("om.occupancy_stated", "occupancy_stated", "ratio", "occupancy stated in the OM")
    om_fact("om.annual_rent_stated", "annual_rent_stated", "AED/yr", "annual rent stated in the OM")
    om_fact("om.yield_stated", "yield_stated", "ratio", "headline yield stated in the OM")
    om_fact("om.price_psf_stated", "price_psf_stated", "AED/sqft", "price per sq ft stated in the OM")
    for name, key, label in (("title_type", "deal.title", "title as stated"),
                             ("chiller_arrangement", "deal.chiller", "chiller arrangement as stated"),
                             ("lease_structure", "deal.lease_structure", "lease structure as stated")):
        f = om.get(name) or {}
        if f.get("status") in TRUSTED:
            om_fact(key, name, "text", label, value=json.dumps(f["value"]) if isinstance(f["value"], dict) else None)
    if (om.get("occupancy_stated") or {}).get("as_of") and "om.occupancy_stated" in F:
        F["om.occupancy_as_of"] = _fact(om["occupancy_stated"]["as_of"], "text", "date the OM gives for occupancy")
    for basis_key, name in (("om.annual_rent_basis", "annual_rent_stated"), ("om.yield_basis", "yield_stated"),
                            ("om.price_psf_basis", "price_psf_stated")):
        if (om.get(name) or {}).get("status") in TRUSTED:
            F[basis_key] = _fact(json.dumps(om[name].get("basis")), "text", f"the OM's own basis for {name}")
    for i, c in enumerate(c for c in om.get("upside_claims", []) if c["status"] in TRUSTED):
        F[f"om.upside_claim_{i + 1}"] = _fact(c["quote"], "text", "OM upside claim (verbatim)",
                                              {"kind": "document", **c["source"], "quote": c["quote"]})
    unverified = [k.replace("_", " ") for k, v in om.items() if isinstance(v, dict) and v.get("status") == "unverified"
                  and k not in COSMETIC_FIELDS]
    F["screen.unverified_om_fields"] = _fact(", ".join(unverified) or "none", "text",
                                             "material OM figures whose quote or value failed verification (not used)")
    F["screen.not_stated_om_fields"] = _fact(
        ", ".join(k for k, v in om.items() if isinstance(v, dict) and v.get("status") == "not_stated") or "none",
        "text", "OM fields the OM does not state")
    F["screen.house_view"] = _fact(HOUSE_VIEW_NOTE, "text", "what the walk-away price and returns rest on")

    if rr:
        s = rr["summary"]
        src = {"kind": "rent_roll", "doc": rr["doc"]}
        for k, unit, label in (("as_of", "date", "rent roll date"), ("unit_count", "units", "units on the rent roll"),
                               ("let_units", "units", "let units (occupied, renewal, notice, legal case)"),
                               ("vacant_units", "units", "vacant units"),
                               ("occupancy_by_units", "ratio", "occupancy by units, rent roll"),
                               ("occupancy_by_area", "ratio", "occupancy by area, rent roll"),
                               ("in_place_rent_aed", "AED/yr", "in-place contract rent, let units"),
                               ("potential_rent_aed", "AED/yr", "in-place plus asking rent on vacant units"),
                               ("vacant_asking_rent_aed", "AED/yr", "asking rent on vacant units"),
                               ("area_sqft_total", "sqft", "sum of unit areas (NSA used)"),
                               ("deposits_aed", "AED", "security deposits held (transfer to buyer)")):
            if s.get(k) is not None:
                F[f"rr.{k}"] = _fact(s[k], unit, label, src)
        for t, v in s["by_type"].items():
            F[f"rr.{t}.units"] = _fact(v["units"], "units", f"{t} units on the rent roll", src)
            if v["avg_rent_psf"]:
                F[f"rr.{t}.avg_rent_psf"] = _fact(v["avg_rent_psf"], "AED/sqft", f"average in-place rent per sq ft, {t}", src)
        for st, n in s["status_counts"].items():
            F[f"rr.status.{st}"] = _fact(n, "units", f"units with status {st}", src)
        if rr.get("master_lease"):
            ml = rr["master_lease"]
            F["rr.master_lease_rent_aed"] = _fact(ml.get("annual_rent_aed"), "AED/yr", "master lease rent", src)
            F["rr.master_lease_end"] = _fact(ml.get("lease_end"), "date", "master lease expiry", src)
            F["rr.master_tenant"] = _fact(ml.get("tenant"), "text", "master tenant", src)

    if opex:
        src = {"kind": "operating_statement", "doc": opex["doc"]}
        p = opex["period"]
        F["opex.months"] = _fact(p.get("months_used"), "months", "months covered by the operating statement", src)
        F["opex.period"] = _fact(f"{p.get('start')} to {p.get('end')}", "text", "statement period", src)
        F["opex.annualisation"] = _fact(p["annualisation"]["note"], "text", "how statement figures were annualised", src)
        for k, label in (("total_income_aed", "statement income net of losses (annual)"),
                         ("total_expenses_aed", "statement operating expenses (annual)"),
                         ("noi_aed", "statement NOI before the screen's adjustments (annual)")):
            F[f"opex.{k}"] = _fact(opex[k], "AED/yr", label, src)
        F["opex.opex_ratio"] = _fact(opex["opex_ratio"], "ratio", "statement expenses / income", src)
        for cat, v in opex["totals_by_category"].items():
            F[f"opex.{cat}"] = _fact(v, "AED/yr", f"statement {cat.replace('_', ' ')} (annual)", src)
        F["opex.absent_standard_categories"] = _fact(", ".join(opex["absent_standard_categories"]) or "none", "text",
                                                     "standard costs absent from the statement", src)

    if uw:
        for name, m in uw["metrics"].items():
            if m.get("value") is not None:
                F[f"uw.{name}"] = _fact(m["value"], m["unit"], METRIC_WORDS.get(name, name.replace("_", " ")),
                                        {"kind": "engine", "metric": name, "note": m.get("note")})
        wa = uw.get("walk_away") or {}
        disc_ = wa.get("discount_to_asking")
        disc_v = _val(disc_)
        if disc_v is not None:
            F["uw.walk_away_vs_asking"] = _fact(f"{disc_v:.0%} below asking" if disc_v > 0.005 else
                                                "asking is within our value", "text",
                                                "walk-away price against the asking price", {"kind": "engine"})
        sens_wa = wa.get("sensitivity") or {}
        label = _val(wa.get("most_sensitive_label") or sens_wa.get("most_sensitive_label"))
        if label:
            F["uw.walk_away_most_sensitive"] = _fact(label, "text", "the assumption that most moves the walk-away price",
                                                     {"kind": "engine"})
            swing = _val(wa.get("largest_swing_aed") or sens_wa.get("largest_swing_aed"))
            if swing:
                F["uw.walk_away_largest_swing_aed"] = _fact(abs(swing), "AED", "how far that assumption moves the "
                                                            "walk-away price", {"kind": "engine"})
        F["uw.analysis_start"] = _fact(uw["analysis_start"], "date", "analysis start", {"kind": "engine"})
        F["uw.hold_years"] = _fact(uw["hold_years"], "years", "hold period", {"kind": "engine"})
        if uw.get("om_yield_check"):
            yc = uw["om_yield_check"]
            F["uw.om_yield_summary"] = _fact(yc["summary"], "text", "OM yield on its basis vs the buyer's", {"kind": "engine"})
            labels = {"reproduced_on_om_basis": "the OM's yield recomputed on the OM's own income and basis",
                      "stated_income_on_price": "the OM's own income figure / asking price",
                      "stated_income_on_total_cost": "the OM's own income figure / (price + acquisition costs)",
                      "buyer_net_on_price": "buyer's net yield: Year-1 NOI / asking price",
                      "buyer_net_on_total_cost": "buyer's net yield: Year-1 NOI / (price + acquisition costs)",
                      "gap_vs_stated": "buyer's net yield on total cost minus the OM's stated yield, in percentage "
                                       "points (write it as points, e.g. 1.3 points)"}
            for k, label in labels.items():
                if (yc.get(k) or {}).get("value") is not None:
                    F[f"uw.om_yield.{k}"] = _fact(yc[k]["value"], "ratio", label, {"kind": "engine"})
        sens = uw["sensitivity"]
        F["uw.sens.rent_shift_step"] = _fact(max(abs(x) for x in sens["rent_shifts"]), "ratio",
                                             "sensitivity step for market rent (one step either side of base); "
                                             "anchor it every time you write it", {"kind": "engine"})
        F["uw.sens.exit_shift_step_bps"] = _fact(max(abs(x) for x in sens["exit_yield_shifts_bps"]), "bps",
                                                 "sensitivity step for the exit yield (one step either side of base); "
                                                 "anchor it every time you write it", {"kind": "engine"})
        for cell in sens["cells"]:
            r, e = round(cell["rent_shift"] * 100), cell["exit_yield_shift_bps"]
            key = f"uw.sens.r{r:+d}.e{e:+d}"
            rent_w = {1: "market rent one step higher", -1: "market rent one step lower", 0: "base market rent"}[
                (r > 0) - (r < 0)]
            exit_w = {1: "exit yield one step wider", -1: "exit yield one step tighter", 0: "base exit yield"}[
                (e > 0) - (e < 0)]
            for k, what in (("unlevered_irr_pre_tax", "unlevered IRR (pre-tax)"),
                            ("levered_irr_pre_tax", "levered IRR (pre-tax, secondary)"), ("dscr_year1", "Year-1 DSCR")):
                F[f"{key}.{k}"] = _fact(cell[k], "x" if k == "dscr_year1" else "ratio",
                                        f"sensitivity, {rent_w} and {exit_w}: {what}", {"kind": "engine"})
        windows = (uw.get("expiry_windows") or {}).get("windows") or []
        if windows:
            top = max(windows, key=lambda w: w["share"] or 0)
            F["uw.max_expiry_window_start"] = _fact(top["start"], "date", "start of the three-month window with the "
                                                    "most expiring rent", {"kind": "engine"})
            F["uw.max_expiry_window_end"] = _fact(top["end"], "date", "end of that window", {"kind": "engine"})
            F["uw.max_expiry_window_rent_aed"] = _fact(top["expiring_rent_aed"], "AED/yr",
                                                       "in-place rent expiring in that window", {"kind": "engine"})
        inputs = uw.get("inputs") or {}
        defaults = [k.split(".")[-1] for k, v in inputs.items() if k.startswith("deal.opex_aed.") and v.get("provenance") == "default"]
        F["uw.opex_defaulted"] = _fact(", ".join(defaults) or "none", "text",
                                       "opex categories filled from mandate defaults", {"kind": "engine"})
        for k in defaults:
            F[f"uw.opex_default.{k}"] = _fact(inputs[f"deal.opex_aed.{k}"]["value"], "AED/yr",
                                              f"mandate default applied for {k}", {"kind": "engine"})
        F["uw.warnings"] = _fact("; ".join(uw.get("warnings") or []) or "none", "text", "engine data warnings",
                                 {"kind": "engine"})
        ops = mandate["underwriting"]["operations"]
        mv = mandate["underwriting"]["market_view"]
        debt = mandate["underwriting"]["debt"]
        for key, val, unit, label in (
                ("max_ltv", debt["max_ltv"], "ratio", "maximum loan to value"),
                ("sizing_dscr", debt["sizing_dscr"], "x", "debt sized to cover Year-1 NOI at this DSCR"),
                ("eibor", debt["base_rate_3m_eibor"], "ratio", "3M EIBOR"),
                ("margin", debt["margin"], "ratio", "loan margin"),
                ("amortisation_years", debt["amortisation_years"], "years", "amortisation"),
                ("structural_vacancy", ops["structural_vacancy"], "ratio", "structural vacancy"),
                ("collection_loss", ops["collection_loss"], "ratio", "collection loss"),
                ("renewal_probability", ops["renewal_probability"], "ratio", "renewal probability"),
                ("management_fee", ops["property_management_pct_of_egi"], "ratio", "management fee, % of EGI"),
                ("exit_yield_expansion_bps", mv["exit_yield_expansion_bps"], "bps", "exit yield expansion")):
            F[f"assume.{key}"] = _fact(val, unit, label, {"kind": "mandate"})
        area = (inputs.get("deal.area") or {}).get("value")
        growth = mv["rent_growth_by_year"].get(area, mv["rent_growth_by_year"]["default"])
        for i, g in enumerate(growth[: uw["hold_years"]], start=1):
            F[f"assume.rent_growth_year{i}"] = _fact(g, "ratio", f"market rent change, year {i}", {"kind": "mandate"})

    if fit:
        F["mandate.verdict"] = _fact(fit["verdict"], "text", "mandate verdict", {"kind": "mandate_fit"})
        F["mandate.headline"] = _fact(fit["headline"], "text", "verdict in plain words", {"kind": "mandate_fit"})
        F["mandate.reason"] = _fact(fit["plain_reason"], "text", "why, in plain words", {"kind": "mandate_fit"})
        for t in fit["tests"]:
            k = f"mandate.{t['name']}"
            name = fit.get("tests_in_words", {}).get(t["name"], t["name"].replace("_", " "))
            result = {"pass": "passes", "fail": "fails", "unknown": "not known"}[t["status"]]
            decisive = "" if t.get("decisive", True) else " (not decisive: the deal is declined on a hard filter)"
            F[k] = _fact(f"{name}: {result}. {t['reason']}", "text",
                         f"{'hard' if t['kind'] == 'hard' else 'soft'} mandate test: {name}{decisive}",
                         {"kind": "mandate_fit"})
            if isinstance(t["threshold"], (int, float)) and not isinstance(t["threshold"], bool):
                tunit = ("ratio" if abs(t["threshold"]) < 1 else "x" if "dscr" in t["name"] or "multiple" in t["name"]
                         else "year" if "completion_year" in t["name"] else "number")
                F[f"{k}.threshold"] = _fact(t["threshold"], tunit,
                                            f"mandate threshold: {name}", {"kind": "mandate"})

    for d in discrepancies:
        k = f"disc.{d['id']}"
        src = {"kind": "discrepancy", "id": d["id"]}
        name = DISCREPANCY_WORDS.get(d["id"], d["id"].replace("_", " "))
        F[f"{k}.severity"] = _fact(d["severity"], "text", f"severity of: {name}", src)
        F[f"{k}.title"] = _fact(d["title"], "text", f"discrepancy: {name}", src)
        F[f"{k}.why"] = _fact(d["why"], "text", f"why it matters and what the screen relied on: {name}", src)
        F[f"{k}.relied_on"] = _fact(RELIED_ON_WORDS.get(d["relied_on"], d["relied_on"].replace("_", " ")), "text",
                                    f"source the screen relied on: {name}", src)
        F[f"{k}.analyst_action"] = _fact(d["analyst_action"], "text", f"analyst action: {name}", src)
        if d.get("same_gap_as"):
            F[f"{k}.same_gap_as"] = _fact(DISCREPANCY_WORDS.get(d["same_gap_as"], d["same_gap_as"]), "text",
                                          f"{name} is the same gap as this item; its impact is counted there", src)
        imp = d.get("impact") or {}
        if imp.get("counted_in"):
            continue
        if isinstance(imp.get("amount_aed"), (int, float)):
            F[f"{k}.impact_aed"] = _fact(imp["amount_aed"], "AED", f"impact of {name} ({imp.get('direction', '')}): "
                                         f"{imp.get('basis', '')}", src)
        if isinstance(imp.get("delta"), (int, float)):
            F[f"{k}.impact_ratio"] = _fact(abs(imp["delta"]), "ratio", f"impact of {name}, in percentage points (write it "
                                           f"as points): {imp.get('basis', '')}", src)
        if isinstance(imp.get("value"), (int, float)):
            F[f"{k}.impact_value"] = _fact(imp["value"], "AED/sqft" if "sqft" in str(imp.get("metric")) else "AED",
                                           f"{name}: {imp.get('metric', '').replace('_', ' ')}", src)
        if isinstance(imp.get("observed_gap"), (int, float)):
            F[f"{k}.observed_gap"] = _fact(imp["observed_gap"], "ratio", "collection loss underwritten (observed gap)", src)
    if fit:
        if fit.get("stop_reason_plain"):
            F["mandate.stop_reason"] = _fact(fit["stop_reason_plain"], "text",
                                             "DECLINED on a hard filter: state this and stop; returns are context only",
                                             {"kind": "mandate_fit"})
        for b in fit.get("blocked_on_statements", []):
            F[f"mandate.blocked_on.{b['test']}"] = _fact(b["statement"], "text",
                                                          "BLOCKING: lead the verdict and the open items with this",
                                                          {"kind": "mandate_fit"})
    for i, n in enumerate(notices, start=1):
        F[f"notice.{n['id']}" + (f".{i}" if n["id"] == "tenant_concentration" else "")] = _fact(
            n["text"], "text", f"notice ({n['severity']}): put it in the checks section", {"kind": "notice"})
    for it in diligence:
        F[f"diligence.{it['id']}"] = _fact(it["text"], "text", "standard first-pass diligence item", {"kind": "checklist"})
    if bridge:
        F["bridge.statement_noi_aed"] = _fact(bridge["statement_noi_aed"], "AED/yr", "NOI as the statement shows it",
                                              {"kind": "engine"})
        F["bridge.screen_noi_year1_aed"] = _fact(bridge["screen_noi_year1_aed"], "AED/yr", "the screen's Year-1 NOI",
                                                 {"kind": "engine"})
        for i, st in enumerate(bridge["steps"], start=1):
            F[f"bridge.step{i}"] = _fact(abs(st["aed"]), "AED/yr",
                                         f"NOI bridge, {'adds' if st['aed'] >= 0 else 'takes off'}: {st['label']}",
                                         {"kind": "engine"})
    return {k: v for k, v in F.items() if v["value"] is not None}


def display(fact: dict) -> str:
    """The value rounded as a memo should write it (54.94% -> 55%, AED 2,896,431 -> AED 2.9m). Negative amounts
    are shown as a size with "(lower)", so prose says "below" rather than printing a minus sign."""
    v, unit = fact["value"], fact["unit"]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        if unit == "date":
            d = parse_date(v)
            return d.strftime("%-d %B %Y") if d else str(v)
        return str(v)
    tail = " (negative)" if v < 0 else ""
    a = abs(v)
    if unit in ("ratio", "ratio/yr"):
        return (f"{a * 100:.0f}%" if a >= 0.10 else f"{a * 100:.1f}%") + tail
    if unit in ("AED", "AED/yr"):
        if a >= 1e6:
            return f"AED {a / 1e6:.1f}m{tail}"
        if a >= 1e4:
            return f"AED {a / 1e3:.0f}k{tail}"
        return f"AED {a:,.0f}{tail}"
    if unit == "AED/sqft":
        return f"AED {a:,.0f} per sq ft"
    if unit == "x":
        return f"{v:.2f}x"
    if unit == "bps":
        return f"{v:.0f} bps"
    if unit == "sqft":
        return f"{a:,.0f} sq ft"
    if unit == "year":
        return f"{v:.0f}"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def fact_sheet_for_model(facts: dict[str, dict]) -> str:
    """The citable facts as the writer sees them: ``fact_id | value as written | what it is`` (sources omitted)."""
    return "\n".join(f"{k} | {display(v)} | {v['label']}" for k, v in facts.items())


# ---------------------------------------------------------------------------- checker


@dataclass
class Token:
    raw: str
    start: int
    end: int
    kind: str          # money | pct | x | bps | sqft | plain | date_day | date_month | quarter
    value: Any
    tol: float = 0.0


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def tokens(markdown: str) -> tuple[list[Token], list[tuple[int, int, str]]]:
    """Numbers and anchors in the prose, in order."""
    anchors = [(m.start(), m.end(), m.group(1)) for m in ANCHOR_RE.finditer(markdown)]
    text = _mask(markdown, [(a, b) for a, b, _ in anchors])
    text = _mask(text, [m.span() for r in EXEMPT_RES for m in r.finditer(text)])
    toks: list[Token] = []
    for rx, kind in DATE_RES:
        for m in rx.finditer(text):
            d = parse_date(m.group(0)) if kind == "day" else parse_date("1 " + m.group(0))
            if d:
                toks.append(Token(m.group(0), m.start(), m.end(), f"date_{kind}", d))
        text = _mask(text, [m.span() for m in rx.finditer(text)])
    for m in QUARTER_RE.finditer(text):
        y, q = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        toks.append(Token(m.group(0), m.start(), m.end(), "quarter", f"{y}-Q{q}"))
    text = _mask(text, [m.span() for m in QUARTER_RE.finditer(text)])
    for m in NUMBER_RE.finditer(text):
        num = m.group("num").replace(",", "")
        dec = len(num.split(".")[1]) if "." in num else 0
        value = float(num)
        half = 0.5 * 10 ** -dec
        scale = _SCALES[m.group("scale").strip().lower()] if m.group("scale") else 1.0
        suf = (m.group("suf") or "").strip().lower()
        if suf == "%":
            kind, value, tol = "pct", value / 100, half / 100
        elif suf.startswith(("pp", "percentage", "point")):
            kind, tol = "points", half            # percentage points: compared with ratio x 100
        elif suf == "x":
            kind, tol = "x", half
        elif suf == "bps":
            kind, tol = "bps", half
        elif suf:
            kind, tol = "sqft", half
        else:
            kind = "money" if (m.group("cur") or m.group("scale")) else "plain"
            value, tol = value * scale, half * scale
        toks.append(Token(m.group(0).strip(), m.start(), m.end(), kind, value, tol))
    return sorted(toks, key=lambda t: t.start), anchors


def _compare(tok: Token, fact: dict) -> str | None:
    """None if the token matches the fact, else the reason."""
    v, unit = fact["value"], fact["unit"]
    if isinstance(v, str) and unit not in ("date",):
        if tok.kind == "quarter":
            return None if tok.value in v else f"{tok.raw} is not in the text fact"
        if tok.kind.startswith("date_"):
            return None if tok.value.isoformat()[:7] in v or tok.raw in v else f"{tok.raw} is not in the text fact"
        for n in parse_numbers(v):
            nv = n.value
            if tok.kind == "pct" and n.kind != "pct":
                continue
            if tok.kind == "points" and n.kind == "pct":
                nv *= 100
            if abs(abs(nv) - abs(tok.value)) <= tok.tol + 1e-9 * max(1, abs(nv)):
                return None
        return f"{tok.raw} does not appear in the text of the fact"
    if unit == "date" or tok.kind.startswith("date_") or tok.kind == "quarter":
        d = parse_date(v) if not isinstance(v, (dt.date,)) else v
        if tok.kind == "quarter":
            return None if isinstance(v, str) and v.startswith(tok.value) else f"{tok.raw} is not the fact {v}"
        if d is None or not tok.kind.startswith("date_"):
            return f"{tok.raw} compared with a date fact {v}"
        same = d == tok.value if tok.kind == "date_day" else (d.year, d.month) == (tok.value.year, tok.value.month)
        return None if same else f"{tok.raw} is not the date {v}"
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return f"fact value {v!r} is not a number"
    target = float(v)
    if tok.kind in ("pct", "points") and unit not in ("ratio", "ratio/yr"):
        return f"{tok.raw} is a percentage but the fact is in {unit}"
    if tok.kind == "points":
        target *= 100
    if tok.kind == "bps":
        target = target if unit == "bps" else target * 10000
    if tok.kind in ("money", "plain", "sqft", "x") and unit in ("ratio", "ratio/yr"):
        return f"{tok.raw} written as a number but the fact is a ratio (write it as a %)"
    if abs(abs(target) - abs(tok.value)) <= tok.tol + 1e-9 * max(1.0, abs(target)):
        return None
    return f"{tok.raw} does not match {fact['label']} = {v:g}"


def check_memo(markdown: str, facts: dict[str, dict]) -> list[str]:
    """All problems with the memo's numbers; empty means every number traces to a fact."""
    errors: list[str] = []
    prose = ANCHOR_RE.sub(" ", markdown)
    for ident in sorted(set(SNAKE_RE.findall(prose))):
        errors.append(f"plain language: '{ident}' is an identifier; say it in words")
    toks, anchors = tokens(markdown)
    for a in anchors:
        if a[2] not in facts:
            errors.append(f"anchor [[{a[2]}]] is not a fact-sheet key")
    starts = [t.start for t in toks]
    for i, t in enumerate(toks):
        nxt = starts[i + 1] if i + 1 < len(toks) else len(markdown) + 1
        anchor = next((a for a in anchors if t.end <= a[0] < nxt and a[0] - t.end <= MAX_ANCHOR_GAP), None)
        ctx = markdown[max(0, t.start - 25): t.end + 10].replace("\n", " ")
        if anchor is None:
            errors.append(f"number {t.raw!r} has no anchor right after it (…{ctx}…)")
            continue
        fact = facts.get(anchor[2])
        if fact is None:
            continue
        why = _compare(t, fact)
        if why is None and _is_negative(fact) and not _reads_negative(markdown, t):
            why = f"{t.raw} is written as a positive figure but {fact['label']} is negative; say so"
        if why:
            errors.append(f"[[{anchor[2]}]]: {why} (…{ctx}…)")
    return errors


NEGATIVE_CUES = re.compile(r"negative|loss|los(?:e|ing)|minus|below zero|fall|falls|fell|down|lower|declin|drop|"
                           r"reduc|less|short|cut|shrink|decrease", re.I)


def _is_negative(fact: dict) -> bool:
    v = fact["value"]
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0


def _reads_negative(markdown: str, tok: "Token") -> bool:
    """A negative fact must read as negative: a minus sign, or a negative word just before or after it."""
    if tok.raw.startswith(("-", "−")) or markdown[max(0, tok.start - 1):tok.start] in ("-", "−"):
        return True
    after = ANCHOR_RE.sub("", markdown[tok.end:tok.end + 80])[:25]      # the words after the anchor
    return bool(NEGATIVE_CUES.search(markdown[max(0, tok.start - 45):tok.start] + " " + after))


# ---------------------------------------------------------------------------- generation


def write_memo(client: ModelClient, model: str, facts: dict[str, dict]) -> tuple[dict, list[ToolResult]]:
    """Draft, check, retry once with the errors; a memo that still fails is marked failed, not shipped."""
    base = [{"type": "text", "text": "Citable facts, one per line as `fact_id | value as written | what it is`. "
                                     "These are the only numbers you may write.\n\n" + fact_sheet_for_model(facts)}]
    results: list[ToolResult] = []
    attempts = []
    content = base + [{"type": "text", "text": "Write the screening memo."}]
    for attempt in (1, 2):
        res = client.call_tool(stage=f"memo_{attempt}", model=model, system=load_prompt("memo"), content=content,
                               tools=[MEMO_TOOL], tool_name=MEMO_TOOL["name"])
        results.append(res)
        md = res.data.get("markdown", "")
        errors = check_memo(md, facts)
        attempts.append({"attempt": attempt, "errors": errors})
        if not errors:
            return {"status": "passed", "markdown": md, "attempts": attempts, "anchor_syntax": "[[fact_id]]"}, results
        content = base + [{"type": "text", "text": "Your previous draft:\n\n" + md},
                          {"type": "text", "text": "Code found these problems. Fix every one: anchor each number "
                                                   "to the fact it comes from and write it as that fact is written (or "
                                                   "rounded), remove any number that is not in the list, and say "
                                                   "identifiers in words. Then resubmit the whole memo.\n- "
                                                   + "\n- ".join(errors)}]
    return {"status": "failed", "markdown": None, "rejected_draft": md, "attempts": attempts,
            "anchor_syntax": "[[fact_id]]"}, results
