"""Metric 2: rent roll. Unit rows matched on unit id; totals; summary rows counted as units.

Compares ``run.rent_roll_summary`` with ``truth.rent_roll``. See evals/README.md.
"""

from __future__ import annotations

import re

from .docs import rent_roll_path, value_in_unit_row
from .common import (CORRECT, MISSED, SPURIOUS, WRONG, check, get, is_num, norm_company, norm_unit_id, num_close,
                     parse_date, ratio)

SECTION = "rent_roll"
LET = {"occupied", "under_renewal", "notice_served", "legal_case"}
# occupied and under_renewal are the same status to the engine (engine/leases.py OCCUPIED_STATUSES), and a
# rent roll often cannot tell them apart; notice_served, legal_case and vacant change the cash flow.
STATUS_CLASS = {"under_renewal": "occupied"}
TOTAL_LABEL = re.compile(r"\b(total|sub-?total|grand|summary|average|occupancy)\b", re.I)


def _cat(v):
    return None if v is None else str(v).strip().lower().replace(" ", "_").replace("-", "_")


def _row_of(source) -> tuple[str | None, int | None]:
    """(sheet, row) of a truth unit or summary row; also takes a run unit's source dict."""
    if isinstance(source, dict):
        return source.get("sheet"), source.get("row")
    s = str(source or "")
    m = re.match(r"^(?P<sheet>.+?)!A(?P<row>\d+)", s)
    if m:
        return m.group("sheet"), int(m.group("row"))
    m = re.match(r"^line (\d+)", s)
    if m:
        return None, int(m.group(1))
    return None, None


def _summary_rows(rr_t: dict) -> set[tuple[str | None, int]]:
    sheet = rr_t.get("sheet")
    out = set()
    for s in rr_t.get("summary_rows") or []:
        r = s.get("row", s.get("line"))
        if r is not None:
            out.add((sheet, int(r)))
    return out


def _is_summary_like(u: dict, summary_rows: set, sheet_based: bool) -> bool:
    sheet, row = _row_of(u.get("source"))
    if row is not None and sheet_based and any(r == row and (s is None or sheet is None or s == sheet)
                                               for s, r in summary_rows):
        return True
    return bool(TOTAL_LABEL.search(str(u.get("unit") or "")) or TOTAL_LABEL.search(str(u.get("tenant") or "")))


def score(deal_id: str, truth: dict, run: dict) -> dict:
    rr_t = truth["rent_roll"]
    rr_r = run.get("rent_roll_summary")
    checks: list[dict] = []
    unit_checks: list[dict] = []
    if not rr_r:
        checks.append(check(SECTION, deal_id, "rent roll parsed", True, False, False, MISSED,
                            "the run has no rent_roll_summary"))
        n_t = len(rr_t["units"])
        return {"checks": checks, "unit_checks": [], "summary": {
            "truth_units": n_t, "run_units": 0, "matched": 0, "recall": 0.0, "precision": None,
            "summary_rows_as_units": 0, "extra_units": 0, "duplicates": 0}}

    truth_units = {norm_unit_id(u["unit"]): u for u in rr_t["units"]}
    summary_rows = _summary_rows(rr_t)
    sheet_based = rr_t.get("format") in ("xlsx", "csv")
    matched: dict[str, dict] = {}
    summary_as_units, extras, dups = [], [], []
    for u in rr_r.get("units") or []:
        k = norm_unit_id(u.get("unit"))
        if k in truth_units and k not in matched:
            matched[k] = u
        elif k in matched:
            dups.append(u)
        elif _is_summary_like(u, summary_rows, sheet_based):
            summary_as_units.append(u)
        else:
            extras.append(u)

    for k, tu in truth_units.items():
        if k not in matched:
            checks.append(check(SECTION, deal_id, f"unit {tu['unit']}", "unit row", None, False, MISSED,
                                "unit in the rent roll not parsed by the run", kind="unit_recall"))
    for u in summary_as_units:
        checks.append(check(SECTION, deal_id, f"row {_row_of(u.get('source'))[1]} ({u.get('unit')!r})",
                            "not a unit (summary/heading row)", "counted as a unit", False, SPURIOUS,
                            f"rent {u.get('annual_rent_aed')}", kind="summary_row_as_unit"))
    for u in extras:
        checks.append(check(SECTION, deal_id, f"unit {u.get('unit')!r}", "no such unit", "counted as a unit", False,
                            SPURIOUS, f"row {_row_of(u.get('source'))[1]}", kind="unit_precision"))
    for u in dups:
        checks.append(check(SECTION, deal_id, f"unit {u.get('unit')!r}", "one row", "duplicate row", False, SPURIOUS,
                            kind="unit_precision"))

    # Asking rents of vacant units count only where the rent roll prints them (see evals/docs.py).
    doc = rent_roll_path(truth)
    visible_asking = {}
    for k, tu in truth_units.items():
        a = tu.get("asking_rent_aed")
        if tu.get("status") not in LET and a:
            visible_asking[k] = bool(doc and value_in_unit_row(doc, tu["unit"], a))
    for k, u in matched.items():
        tu = truth_units[k]
        unit_checks += _unit_field_checks(deal_id, tu, u, visible_asking.get(k, True))

    n_run = len(rr_r.get("units") or [])
    # Totals.
    tc = dict(rr_t["totals_computed"])
    hidden = sum(truth_units[k]["asking_rent_aed"] for k, vis in visible_asking.items() if not vis)
    asking_note = None
    if hidden:
        tc["vacant_asking_rent_aed"] = (tc.get("vacant_asking_rent_aed") or 0) - hidden
        tc["potential_rent_aed"] = (tc.get("potential_rent_aed") or 0) - hidden
        asking_note = (f"truth includes AED {hidden:,.0f} of asking rent the rent roll does not print "
                       f"({sum(1 for v in visible_asking.values() if not v)} vacant units); expected excludes it")
    s = rr_r.get("summary") or {}
    for item, exp, got, kind in [
        ("unit_count", tc.get("unit_count"), s.get("unit_count"), "count"),
        ("let_units", tc.get("occupied_units"), s.get("let_units"), "count"),
        ("in_place_rent_aed", tc.get("in_place_rent_aed"), s.get("in_place_rent_aed"), "num"),
        ("occupancy_by_units", tc.get("occupancy_units"), s.get("occupancy_by_units"), "num"),
        ("occupancy_by_area", tc.get("occupancy_area"), s.get("occupancy_by_area"), "num"),
        ("vacant_asking_rent_aed", tc.get("vacant_asking_rent_aed"), s.get("vacant_asking_rent_aed"), "num"),
        ("potential_rent_aed", tc.get("potential_rent_aed"), s.get("potential_rent_aed"), "num"),
    ]:
        if exp is None:
            continue
        ok = is_num(got) and (int(got) == int(exp) if kind == "count" else num_close(float(exp), float(got)))
        note = asking_note if item in ("vacant_asking_rent_aed", "potential_rent_aed") else None
        checks.append(check(SECTION, deal_id, item, exp, got, ok, None if got is not None else MISSED, note, kind="total",
                            headline=item in ("in_place_rent_aed", "occupancy_by_units")))
    e_date = get(truth, "true_building", "engine_inputs", "rent_roll_date") or get(truth, "true_building", "rent_roll_date")
    if e_date:
        g_date = s.get("as_of")
        ed, gd = parse_date(e_date), parse_date(g_date)
        checks.append(check(SECTION, deal_id, "as_of (rent roll date)", e_date, g_date,
                            bool(gd and (ed.year, ed.month) == (gd.year, gd.month)), None if g_date else MISSED,
                            "without it the engine starts the expiry windows at the analysis start" if not g_date else None,
                            kind="total"))
    for item, exp, got in [
        ("expired_leases_shown_occupied", tc.get("expired_but_occupied_units") or [], s.get("expired_leases_shown_occupied")),
        ("let_units_missing_ejari", tc.get("missing_ejari_units") or [], s.get("let_units_missing_ejari")),
    ]:
        e = sorted(norm_unit_id(x) for x in exp)
        g = sorted(norm_unit_id(x) for x in (got or []))
        checks.append(check(SECTION, deal_id, item, sorted(exp), sorted(got or []), e == g, kind="total"))

    # Master lease (the owner's income when the building is master-leased).
    ml_t = rr_t.get("master_lease") or get(truth, "true_building", "engine_inputs", "master_lease")
    ml_r = get(run, "underwriting", "deal_inputs", "master_lease")
    if ml_t or ml_r:
        if not ml_r:
            checks.append(check(SECTION, deal_id, "master_lease", "master lease", None, False, MISSED, kind="master_lease"))
        elif not ml_t:
            checks.append(check(SECTION, deal_id, "master_lease", None, ml_r, False, SPURIOUS, kind="master_lease"))
        else:
            e_rent, g_rent = ml_t.get("annual_rent_aed"), ml_r.get("annual_rent_aed")
            checks.append(check(SECTION, deal_id, "master_lease.annual_rent_aed", e_rent, g_rent,
                                is_num(g_rent) and num_close(e_rent, g_rent), kind="master_lease"))
            e_end = ml_t.get("end") or ml_t.get("lease_end")
            checks.append(check(SECTION, deal_id, "master_lease.lease_end", e_end, ml_r.get("lease_end"),
                                parse_date(e_end) == parse_date(ml_r.get("lease_end")), kind="master_lease"))
            checks.append(check(SECTION, deal_id, "master_lease.tenant", ml_t.get("tenant"), ml_r.get("tenant"),
                                norm_company(ml_t.get("tenant")) == norm_company(ml_r.get("tenant")), kind="master_lease"))

    by_field: dict[str, dict] = {}
    for c in unit_checks:
        f = by_field.setdefault(c["item"].split(".", 1)[1], {"n": 0, "correct": 0})
        f["n"] += 1
        f["correct"] += c["ok"]
    for f in by_field.values():
        f["accuracy"] = ratio(f["correct"], f["n"])
    totals = [c for c in checks if c.get("kind") == "total"]
    return {"checks": checks, "unit_checks": unit_checks, "summary": {
        "truth_units": len(truth_units), "run_units": n_run, "matched": len(matched),
        "recall": ratio(len(matched), len(truth_units)), "precision": ratio(len(matched), n_run),
        "summary_rows_as_units": len(summary_as_units), "extra_units": len(extras), "duplicates": len(dups),
        "unit_fields": by_field,
        "totals_n": len(totals), "totals_correct": sum(c["ok"] for c in totals),
        "in_place_rent_ok": next((c["ok"] for c in totals if c["item"] == "in_place_rent_aed"), None),
        "occupancy_ok": next((c["ok"] for c in totals if c["item"] == "occupancy_by_units"), None),
    }}


def _unit_field_checks(deal_id: str, tu: dict, u: dict, asking_visible: bool = True) -> list[dict]:
    out = []
    uid = tu["unit"]

    def add(field, exp, got, ok):
        out.append(check(SECTION, deal_id, f"unit {uid}.{field}", exp, got, ok, kind="unit_field"))

    add("unit_type", tu.get("unit_type"), u.get("unit_type"), _cat(tu.get("unit_type")) == _cat(u.get("unit_type")))
    ea, ga = tu.get("area_sqft"), u.get("area_sqft")
    add("area_sqft", ea, ga, is_num(ga) and num_close(ea, ga))
    st = lambda x: STATUS_CLASS.get(_cat(x), _cat(x))  # noqa: E731
    add("status", tu.get("status"), u.get("status"), st(tu.get("status")) == st(u.get("status")))
    if tu.get("status") in LET:
        er, gr = tu.get("annual_rent_aed"), u.get("annual_rent_aed")
        add("annual_rent_aed", er, gr, (er is None and gr is None) or (is_num(er) and is_num(gr) and num_close(er, gr)))
        el, gl = tu.get("lease_end"), u.get("lease_end")
        add("lease_end", el, gl, parse_date(el) == parse_date(gl))
    else:
        ea_, ga_ = (tu.get("asking_rent_aed") if asking_visible else None), u.get("asking_rent_aed")
        add("asking_rent_aed", ea_, ga_, (ea_ is None and ga_ is None) or (is_num(ea_) and is_num(ga_) and num_close(ea_, ga_)))
    return out
