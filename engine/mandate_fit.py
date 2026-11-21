"""Apply the mandate's buy box to a deal: Pursue / Needs work / Pass, with one record per test.

Each filter in ``mandate.buy_box`` maps to exactly one test below. A filter in the
mandate with no test here raises an error, so the mandate and the code cannot drift
apart unnoticed. A test whose fact or metric is unknown gets status ``unknown``;
unknown counts as a soft fail (never a pass), even for a hard filter, because the
screen cannot clear a deal on something it has not seen.
"""

from __future__ import annotations

from typing import Any, Callable

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"


def _pct(x: float) -> str:
    return f"{x:.2%}"


def _x(x: float) -> str:
    return f"{x:.2f}x"


def _aed(x: float) -> str:
    return f"AED {x:,.0f}"


def _engine_value(uw_result: dict | None, name: str) -> Any:
    if not uw_result:
        return None
    m = (uw_result.get("metrics") or {}).get(name)
    return None if m is None else m.get("value")


def _record(name: str, kind: str, threshold: Any, actual: Any, passed: bool | None,
            reason: str, source: str) -> dict[str, Any]:
    return {
        "name": name, "kind": kind, "threshold": threshold, "actual": actual,
        "passed": passed, "status": UNKNOWN if passed is None else PASS if passed else FAIL,
        "reason": reason, "source": source,
    }


def _membership(name: str, kind: str, allowed: list, actual: Any, label: str) -> dict:
    if actual in (None, ""):
        return _record(name, kind, allowed, None, None, f"{label} unknown; counts as a soft fail.", "deal_facts")
    norm = {str(a).strip().lower(): a for a in allowed}
    ok = str(actual).strip().lower() in norm
    reason = (f"{label} {actual!r} is in the mandate." if ok
              else f"{label} {actual!r} is outside the mandate ({', '.join(map(str, allowed))}).")
    return _record(name, kind, allowed, actual, ok, reason, "deal_facts")


def _bound(name: str, kind: str, threshold: float, actual: Any, label: str,
           fmt: Callable[[float], str], minimum: bool, source: str) -> dict:
    if actual is None:
        return _record(name, kind, threshold, None, None, f"{label} unknown; counts as a soft fail.", source)
    ok = actual >= threshold if minimum else actual <= threshold
    word = "at least" if minimum else "at most"
    verdict = "meets" if ok else "misses"
    reason = f"{label} {fmt(actual)} {verdict} the {word} {fmt(threshold)} requirement."
    return _record(name, kind, threshold, actual, ok, reason, source)


def _related_party_master_lease(facts: dict, uw_result: dict | None) -> tuple[bool | None, str]:
    """Whether income depends on a master lease to a related party, and where that came from.

    Sources, combined so that any evidence of a related-party master lease wins:
    ``deal_facts.master_lease_related_party``; the master lease in the underwriting
    result (its ``related_party``); and ``deal_facts.lease_structure == "direct_leases"``,
    which means there is no master lease at all. Nothing known gives ``None``.
    """
    found: list[tuple[bool, str]] = []
    if facts.get("master_lease_related_party") is not None:
        found.append((bool(facts["master_lease_related_party"]), "deal_facts"))
    ml = (uw_result or {}).get("master_lease")
    if ml is not None and ml.get("related_party") is not None:
        found.append((bool(ml["related_party"]), "engine"))
    if ml is None and str(facts.get("lease_structure") or "").lower() == "direct_leases":
        found.append((False, "deal_facts"))
    for flag, src in found:
        if flag:
            return True, src
    if found:
        return False, found[0][1]
    return None, "engine" if ml is not None else "deal_facts"


def mandate_fit(deal_facts: dict, uw_result: dict | None, mandate: dict) -> dict[str, Any]:
    """Test a deal against ``mandate.buy_box`` and return the verdict and test records.

    Parameters
    ----------
    deal_facts:
        ``asset_type``, ``area``, ``title_type``, ``unit_count``, ``price_aed``,
        ``completion_year``, ``master_lease_related_party`` (True if income depends on a
        master lease to a related party) and ``lease_structure`` (``direct_leases`` or
        ``master_lease``). Missing or ``None`` means unknown. The related-party flag is
        also read from the underwriting result's ``master_lease``.
        ``unit_count`` and ``price_aed`` fall back to the underwriting result if absent.
    uw_result:
        The output of :func:`engine.underwrite`, or ``None`` if the deal could not be
        underwritten (then every engine-based test is unknown).
    mandate:
        The parsed ``mandate.yaml``.

    Returns ``{"verdict", "reason", "hard_fails", "soft_fails", "unknown", "tests"}``.
    """
    facts = deal_facts or {}
    hard = mandate["buy_box"]["hard"]
    soft = mandate["buy_box"]["soft"]
    rules = mandate["verdict_rules"]
    tests: list[dict[str, Any]] = []

    handled_hard = {"asset_type", "title", "areas", "min_units", "max_units", "min_price_aed",
                    "max_price_aed", "min_completion_year", "min_dscr_year1",
                    "no_master_lease_to_related_party"}
    handled_soft = {"min_going_in_net_yield_on_cost", "target_levered_irr", "target_equity_multiple",
                    "min_occupancy", "max_lease_expiry_share_in_any_quarter",
                    "max_over_rent_share_of_income"}
    missing = (set(hard) - handled_hard) | (set(soft) - handled_soft)
    if missing:
        raise ValueError(f"mandate filters with no implemented test: {sorted(missing)}")

    # ---- hard filters ------------------------------------------------------------------
    if "asset_type" in hard:
        tests.append(_membership("asset_type", "hard", hard["asset_type"], facts.get("asset_type"), "Asset type"))
    if "title" in hard:
        tests.append(_membership("title", "hard", hard["title"], facts.get("title_type"), "Title"))
    if "areas" in hard:
        tests.append(_membership("areas", "hard", hard["areas"], facts.get("area"), "Area"))

    units, units_src = facts.get("unit_count"), "deal_facts"
    if units is None and _engine_value(uw_result, "unit_count") is not None:
        units, units_src = _engine_value(uw_result, "unit_count"), "engine"
    if "min_units" in hard:
        tests.append(_bound("min_units", "hard", hard["min_units"], units, "Unit count",
                            lambda v: f"{v:,.0f}", True, units_src))
    if "max_units" in hard:
        tests.append(_bound("max_units", "hard", hard["max_units"], units, "Unit count",
                            lambda v: f"{v:,.0f}", False, units_src))

    price, price_src = facts.get("price_aed"), "deal_facts"
    if price is None and _engine_value(uw_result, "price_aed") is not None:
        price, price_src = _engine_value(uw_result, "price_aed"), "engine"
    if "min_price_aed" in hard:
        tests.append(_bound("min_price_aed", "hard", hard["min_price_aed"], price, "Price", _aed, True, price_src))
    if "max_price_aed" in hard:
        tests.append(_bound("max_price_aed", "hard", hard["max_price_aed"], price, "Price", _aed, False, price_src))
    if "min_completion_year" in hard:
        tests.append(_bound("min_completion_year", "hard", hard["min_completion_year"],
                            facts.get("completion_year"), "Completion year", lambda v: f"{v:.0f}", True,
                            "deal_facts"))
    if "min_dscr_year1" in hard:
        tests.append(_bound("min_dscr_year1", "hard", hard["min_dscr_year1"],
                            _engine_value(uw_result, "dscr_year1"), "Year-1 DSCR", _x, True, "engine"))
    if hard.get("no_master_lease_to_related_party"):
        flag, src = _related_party_master_lease(facts, uw_result)
        if flag is None:
            tests.append(_record("no_master_lease_to_related_party", "hard", False, None, None,
                                 "Lease structure or master tenant relationship unknown; counts as a soft fail.",
                                 src))
        else:
            tests.append(_record("no_master_lease_to_related_party", "hard", False, flag, not flag,
                                 "Income depends on a master lease to a related party." if flag
                                 else "No master lease to a related party.", src))

    # ---- soft filters ----------------------------------------------------------------------
    soft_specs = (
        ("min_going_in_net_yield_on_cost", "going_in_net_yield_on_cost", "Going-in net yield on cost", _pct, True),
        ("target_levered_irr", "levered_irr_pre_tax", "Levered IRR (pre-tax)", _pct, True),
        ("target_equity_multiple", "levered_equity_multiple_pre_tax", "Levered equity multiple (pre-tax)", _x, True),
        ("min_occupancy", "occupancy_by_units", "Occupancy by units", _pct, True),
        ("max_lease_expiry_share_in_any_quarter", "max_expiry_share_quarter",
         "Largest quarterly lease expiry share (next 12 months)", _pct, False),
        ("max_over_rent_share_of_income", "over_rent_share_of_income", "Over-rented share of income", _pct, False),
    )
    for key, metric_name, label, fmt, minimum in soft_specs:
        if key in soft:
            tests.append(_bound(key, "soft", soft[key], _engine_value(uw_result, metric_name),
                                label, fmt, minimum, "engine"))

    # ---- verdict -----------------------------------------------------------------------------
    hard_fails = [t for t in tests if t["kind"] == "hard" and t["status"] == FAIL]
    unknown = [t for t in tests if t["status"] == UNKNOWN]
    soft_fails = [t for t in tests if t["kind"] == "soft" and t["status"] == FAIL] + unknown

    if rules.get("pass_if_any_hard_fails", True) and hard_fails:
        verdict = "Pass"
        reason = "Fails hard filter(s): " + ", ".join(t["name"] for t in hard_fails) + "."
    elif len(soft_fails) <= rules.get("pursue_if_soft_fails_at_most", 0):
        verdict = "Pursue"
        reason = "Meets every hard filter and every soft filter." if not soft_fails else \
            f"Meets every hard filter; {len(soft_fails)} soft fail(s) within the allowance."
    elif rules.get("needs_work_otherwise", True):
        verdict = "Needs work"
        reason = (f"Meets every hard filter; {len(soft_fails)} soft fail(s) or unknown(s): "
                  + ", ".join(t["name"] for t in soft_fails) + ".")
    else:
        verdict = "Pass"
        reason = "Soft fails exceed the allowance and the mandate has no 'needs work' outcome."
    return {
        "verdict": verdict,
        "reason": reason,
        "hard_fails": len(hard_fails),
        "soft_fails": len(soft_fails),
        "unknown": len(unknown),
        "tests": tests,
    }
