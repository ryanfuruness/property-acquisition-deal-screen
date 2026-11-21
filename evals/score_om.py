"""Metric 1: OM field extraction, and citation validity.

Compares ``run.extracted.om`` with ``truth.om_fields``. See evals/README.md for the rules.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .common import (CORRECT, CORRECT_NULL, MISSED, SPURIOUS, WRONG, check, get, is_num, norm_company,
                     norm_text, num_close, squash, token_overlap)

SECTION = "om"
TRUSTED = {"verified", "verified_fuzzy"}

# Categorical aliases: the generator's truth vocabulary -> the pipeline schema's enum.
# These are spelling differences for the same category, not judgement calls.
CATEGORY_ALIASES = {
    "mixed_use_ground_floor_retail": "mixed_use_residential_retail",
}

CLAIM_MATCH_MIN_OVERLAP = 0.6
RENT_BASIS_WORDS = re.compile(r"in[- ]?place|passing|contracted|current|potential|projected|asking|full occupancy", re.I)


def _labels_rent_basis(quote: str | None) -> bool:
    """Does the OM's own text for the rent figure say what basis it is on?"""
    return bool(RENT_BASIS_WORDS.search(quote or ""))


def _label_measure(label: str | None) -> str:
    """The measure the OM's label itself claims: 'Net Yield' -> net, 'Gross Yield' -> gross, 'ROI' -> unstated."""
    t = (label or "").lower()
    return "net" if re.search(r"\bnet\b", t) else "gross" if re.search(r"\bgross\b", t) else "unstated"


def _is_null(v: Any) -> bool:
    return v is None or v == "unstated" or v == [] or v == {} or (
        isinstance(v, dict) and all(x in (None, "unstated") for x in v.values()))


def _cat(v: Any) -> Any:
    if v is None:
        return None
    s = str(v).strip().lower().replace("-", "_").replace(" ", "_")
    if s.startswith("unstated"):
        return "unstated"
    return CATEGORY_ALIASES.get(s, s)


# ---------------------------------------------------------------------------- comparators
# Each takes (expected, got) with both non-null and returns (ok, note).


def cmp_text(e, g):
    return norm_text(e) == norm_text(g), None


def cmp_code(e, g):
    return squash(e) == squash(g), None


def cmp_cat(e, g):
    return _cat(e) == _cat(g), None


def cmp_count(e, g):
    return is_num(g) and int(round(g)) == int(e) and abs(g - round(g)) < 1e-9, None


def cmp_num(e, g):
    return is_num(g) and num_close(float(e), float(g)), None


def cmp_mix(e, g):
    if not isinstance(g, dict):
        return False, "not a mapping"
    keys = set(e) | set(g)
    diff = {k: (e.get(k) or 0, g.get(k) or 0) for k in keys if (e.get(k) or 0) != (g.get(k) or 0)}
    return not diff, (f"differs on {diff}" if diff else None)


def _title_part(om: dict, part: str):
    """Truth title part, normalised; 'unstated (non-freehold indicated)' means the OM does not state it."""
    v = get(om, "title_type", "value") or {}
    raw = v.get("tenure") if part == "tenure" else v.get("title", v.get("ownership"))
    return None if _cat(raw) in (None, "unstated") else _cat(raw)


def _run_title_part(rf: dict, part: str):
    v = rf.get("value")
    raw = v.get(part) if isinstance(v, dict) else None
    return None if _cat(raw) in (None, "unstated") else _cat(raw)


# How to read the run's value for a field, when it is not simply ``value``.
GOT = {
    "title_type.tenure": lambda rf: _run_title_part(rf, "tenure"),
    "title_type.ownership": lambda rf: _run_title_part(rf, "ownership"),
}


def cmp_lease(e, g):
    et, gt = _cat(e.get("value", e.get("type"))), _cat((g or {}).get("type"))
    if et != gt:
        return False, f"type {gt} vs {et}"
    em, gm = e.get("master_tenant"), (g or {}).get("master_tenant")
    if em is None and gm is None:
        return True, None
    if em is None or gm is None or norm_company(em) != norm_company(gm):
        return False, f"master tenant {gm!r} vs {em!r}"
    return True, None


def claims_match(expected: list[str], got: list[dict]) -> tuple[bool, str | None]:
    quotes = [c.get("quote") or "" for c in got]
    unmatched_truth = [e for e in expected if not any(token_overlap(e, q) >= CLAIM_MATCH_MIN_OVERLAP for q in quotes)]
    extra = [q for q in quotes if not any(token_overlap(e, q) >= CLAIM_MATCH_MIN_OVERLAP for e in expected)]
    notes = []
    if unmatched_truth:
        notes.append(f"{len(unmatched_truth)} OM claim(s) not extracted")
    if extra:
        notes.append(f"{len(extra)} extracted claim(s) not in the OM's claims: {[q[:80] for q in extra]}")
    return not notes, "; ".join(notes) or None


# ---------------------------------------------------------------------------- field table
# item, run field, truth field, how to read the truth value, comparator.


def _tv(key: str) -> Callable[[dict], Any]:
    return lambda om: get(om, key, "value")


def _price_psf_value(om):
    return get(om, "price_psf", "value", "value")


FIELDS: list[tuple[str, str, str, Callable[[dict], Any], Callable]] = [
    ("building_name", "building_name", "building_name", _tv("building_name"), cmp_text),
    ("asset_type", "asset_type", "asset_type", _tv("asset_type"), cmp_cat),
    ("area (market_area)", "market_area", "area", _tv("area"), cmp_text),
    ("plot_number", "plot_number", "plot_number", _tv("plot_number"), cmp_code),
    ("title_type.tenure", "title_type", "title_type", lambda om: _title_part(om, "tenure"), cmp_cat),
    ("title_type.ownership", "title_type", "title_type", lambda om: _title_part(om, "ownership"), cmp_cat),
    ("completion_year", "completion_year", "completion_year", _tv("completion_year"), cmp_count),
    ("floors", "floors", "floors", _tv("floors"), cmp_code),
    ("unit_count", "unit_count", "unit_count", _tv("unit_count"), cmp_count),
    ("unit_mix", "unit_mix", "unit_mix", _tv("unit_mix"), cmp_mix),
    ("bua_sqft", "bua_sqft", "bua_sqft", _tv("bua_sqft"), cmp_num),
    ("nsa_sqft", "nsa_sqft", "nsa_sqft", _tv("nsa_sqft"), cmp_num),
    ("parking_spaces", "parking_spaces", "parking_spaces", _tv("parking_spaces"), cmp_count),
    ("occupancy_stated", "occupancy_stated", "occupancy_stated", _tv("occupancy_stated"), cmp_num),
    ("annual_rent_stated", "annual_rent_stated", "annual_rent_stated", _tv("annual_rent_stated"), cmp_num),
    ("yield_stated", "yield_stated", "yield_stated", _tv("yield_stated"), cmp_num),
    ("asking_price_aed", "asking_price_aed", "asking_price_aed", _tv("asking_price_aed"), cmp_num),
    ("price_psf_stated", "price_psf_stated", "price_psf", _price_psf_value, cmp_num),
    ("chiller_arrangement", "chiller_arrangement", "chiller_arrangement", _tv("chiller_arrangement"), cmp_cat),
    ("opex_stated_aed", "opex_stated_aed", "opex_stated_aed", _tv("opex_stated_aed"), cmp_num),
    ("lease_structure", "lease_structure", "lease_structure", _tv("lease_structure"), cmp_lease),
]

# Fields in truth that are not scored, and why (also in README).
NOT_SCORED = {
    "broker": "not in the pipeline's extraction schema",
    "area (as written)": "free text; the canonical area is scored through market_area",
    "net_income_stated_aed": "truth.json has no answer for it",
}


def _truth_pages(tf: dict | None) -> list[int]:
    if not tf or tf.get("page") is None:
        return []
    return [tf["page"]] + list(tf.get("also_on_pages") or [])


def _compare(expected, got, cmp) -> tuple[str, bool, str | None]:
    en, gn = _is_null(expected), _is_null(got)
    if en and gn:
        return CORRECT_NULL, True, None
    if en:
        return SPURIOUS, False, "truth says the OM does not state this; the run gives a value"
    if gn:
        return MISSED, False, "the OM states this; the run gives no value"
    ok, note = cmp(expected, got)
    return (CORRECT if ok else WRONG), ok, note


def score(deal_id: str, truth: dict, run: dict) -> dict:
    om_t = truth.get("om_fields", {})
    om_r = get(run, "extracted", "om", default={}) or {}
    om_doc = get(run, "deal", "documents_used", "om")
    checks, citations = [], []

    for item, rkey, tkey, tval, cmp in FIELDS:
        rf = om_r.get(rkey) or {}
        expected = tval(om_t)
        got = GOT[item](rf) if item in GOT else rf.get("value")
        outcome, ok, note = _compare(expected, got, cmp)
        status = rf.get("status")
        checks.append(check(SECTION, deal_id, item, expected, got, ok, outcome, note,
                            run_status=status, trusted=bool(ok and (outcome == CORRECT_NULL or status in TRUSTED))))
        if outcome in (CORRECT, WRONG):
            citations.append(_citation(deal_id, item, om_t.get(tkey), rf, om_doc, ok))

    # Basis sub-fields: scored only where truth states the figure.
    ar = om_t.get("annual_rent_stated") or {}
    if ar.get("value") is not None:
        rf = om_r.get("annual_rent_stated") or {}
        accepted = sorted({ar.get("basis")} | ({"unstated"} if not _labels_rent_basis(ar.get("quote")) else set()) - {None})
        g = rf.get("basis")
        ok = _cat(g) in {_cat(b) for b in accepted}
        checks.append(check(SECTION, deal_id, "annual_rent_stated.basis", accepted if len(accepted) > 1 else accepted[0],
                            g, ok, None, "the true basis, or 'unstated' because the OM's figure carries no basis label"
                            if len(accepted) > 1 else None,
                            run_status=rf.get("status"), trusted=bool(ok and rf.get("status") in TRUSTED)))
    ys = om_t.get("yield_stated") or {}
    if ys.get("value") is not None:
        rf = om_r.get("yield_stated") or {}
        e, g = ys.get("basis") or {}, rf.get("basis") or {}
        measures = sorted({_cat(e.get("measure")), _label_measure(ys.get("label") or ys.get("quote"))} - {None})
        ok = _cat(g.get("measure")) in measures and _cat(e.get("on")) == _cat(g.get("on"))
        exp = {"measure": measures if len(measures) > 1 else measures[0], "on": e.get("on")}
        checks.append(check(SECTION, deal_id, "yield_stated.basis", exp, g or None, ok,
                            f"OM label {ys.get('label')!r}: the true measure or the label's own measure is accepted"
                            if len(measures) > 1 else None,
                            run_status=rf.get("status"), trusted=bool(ok and rf.get("status") in TRUSTED)))
    pp = get(om_t, "price_psf", "value")
    if pp:
        rf = om_r.get("price_psf_stated") or {}
        e = pp.get("basis") if pp.get("basis_labelled") else "unstated"
        g = rf.get("basis")
        ok = _cat(e) == _cat(g)
        checks.append(check(SECTION, deal_id, "price_psf_stated.basis", e, g, ok,
                            "the OM does not label the basis, so the extraction must say unstated" if e == "unstated" else None,
                            run_status=rf.get("status"), trusted=bool(ok and rf.get("status") in TRUSTED)))

    # Upside claims: a list.
    exp_claims = get(om_t, "upside_claims", "value", default=[]) or []
    got_claims = om_r.get("upside_claims") or []
    if not exp_claims and not got_claims:
        checks.append(check(SECTION, deal_id, "upside_claims", [], [], True, CORRECT_NULL, trusted=True))
    elif not exp_claims:
        checks.append(check(SECTION, deal_id, "upside_claims", [], [c.get("quote") for c in got_claims], False, SPURIOUS,
                            "the OM makes no upside claim; the run extracted some", trusted=False))
    elif not got_claims:
        checks.append(check(SECTION, deal_id, "upside_claims", exp_claims, [], False, MISSED, trusted=False))
    else:
        ok, note = claims_match(exp_claims, got_claims)
        trusted = ok and all(c.get("status") in TRUSTED for c in got_claims)
        checks.append(check(SECTION, deal_id, "upside_claims", exp_claims, [c.get("quote") for c in got_claims], ok,
                            None, note, run_status=",".join(sorted({str(c.get("status")) for c in got_claims})),
                            trusted=trusted))
        pages = _truth_pages(om_t.get("upside_claims"))
        for c in got_claims:
            citations.append(_citation(deal_id, "upside_claims", om_t.get("upside_claims"),
                                       {"source": c.get("source"), "status": c.get("status")}, om_doc, ok, pages))

    n = len(checks)
    correct = sum(c["ok"] for c in checks)
    trusted = sum(c["trusted"] for c in checks)
    cit = {
        "n": len(citations),
        "page_match": sum(c["page_match"] for c in citations),
        "run_verified": sum(c["run_verified"] for c in citations),
        "valid": sum(c["valid"] for c in citations),
    }
    return {"checks": checks, "citations": citations,
            "summary": {"n": n, "correct": correct, "trusted_correct": trusted, "citations": cit}}


def _citation(deal_id, item, tf, rf, om_doc, value_ok, pages=None) -> dict:
    pages = pages if pages is not None else _truth_pages(tf)
    src = rf.get("source") or {}
    page, doc = src.get("page"), src.get("doc")
    same_doc = om_doc is None or doc is None or doc == om_doc
    page_match = bool(same_doc and page in pages)
    run_verified = rf.get("status") in TRUSTED
    valid = bool(run_verified and (page_match or value_ok))
    return {"deal_id": deal_id, "item": item, "truth_pages": pages, "cited_doc": doc, "cited_page": page,
            "page_match": page_match, "run_status": rf.get("status"), "run_verified": run_verified,
            "value_correct": bool(value_ok), "valid": valid}
