"""Plain-language reading of the engine's mandate fit, for the memo and the site.

The engine decides the verdict (Pursue / Needs work / Decline), the hard tests it is blocked on and the stop
reason for a declined deal. This module only words them: test names in plain English, a deal blocked on an
unknown hard test reported as "Needs work, blocked on ...", and a declined deal reported on its hard fail
alone. The screen never decides title (DESIGN.md, item 16): an unknown title blocks the deal until legal has
confirmed it, so it leads the verdict and the open items.
"""

from __future__ import annotations

TEST_WORDS = {
    "asset_type": "asset type",
    "title": "freehold single title",
    "areas": "location in a mandate area",
    "min_units": "minimum unit count",
    "max_units": "maximum unit count",
    "min_price_aed": "minimum price",
    "max_price_aed": "maximum price",
    "min_completion_year": "building age",
    "min_dscr_year1": "Year-1 debt service cover",
    "no_master_lease_to_related_party": "no master lease to a related party",
    "min_going_in_net_yield_on_cost": "going-in net yield on total cost",
    "target_unlevered_irr": "unlevered IRR target",
    "target_unlevered_equity_multiple": "unlevered equity multiple target",
    "min_occupancy": "minimum occupancy",
    "max_lease_expiry_share_in_any_quarter": "lease expiry concentration",
    "max_over_rent_share_of_income": "share of income let above the screen reference",
}

# What to say when a hard test cannot be decided from the documents.
BLOCK_STATEMENTS = {
    "title": "Title not stated; legal check required before any further work.",
    "no_master_lease_to_related_party": ("Whether the master tenant is related to the seller is not stated; "
                                         "confirm in writing before any further work."),
}
TITLE_BLOCK = BLOCK_STATEMENTS["title"]


def words(test_name: str) -> str:
    return TEST_WORDS.get(test_name, test_name.replace("_", " "))


def _sentence(text: str) -> str:
    return text[0].upper() + text[1:] + "."


def summarise_fit(fit: dict) -> dict:
    """``{headline, plain_reason, stop_reason_plain, blocked_on_statements, tests_in_words}`` for a ``mandate_fit`` result.

    ``blocked_on_statements`` is ``[{test, statement}]``, one per hard test the engine reports as unknown.
    """
    tests = fit["tests"]
    hard_fail = [t for t in tests if t["kind"] == "hard" and t["status"] == "fail"]
    soft_fail = [t for t in tests if t["kind"] == "soft" and t["status"] == "fail"]
    soft_unknown = [t for t in tests if t["kind"] == "soft" and t["status"] == "unknown"]
    blocked = [{"test": name, "statement": BLOCK_STATEMENTS.get(
        name, f"{_sentence(words(name))[:-1]} is not known; confirm before any further work.")}
        for name in fit.get("blocked_on") or []]
    stop_plain = None
    if hard_fail:
        stop_plain = _sentence("declined on the mandate's hard filters: " + ", ".join(words(t["name"]) for t in hard_fail))
        plain = stop_plain + " Returns are shown for reference only and are not decisive."
        headline = f"Decline: {stop_plain}"
    else:
        parts = []
        if soft_fail:
            parts.append("misses " + ", ".join(words(t["name"]) for t in soft_fail))
        if soft_unknown:
            parts.append("cannot yet test " + ", ".join(words(t["name"]) for t in soft_unknown))
        plain = _sentence("; ".join(parts)) if parts else "Meets every mandate test."
        if blocked:
            headline = (f"Needs work, blocked on {', '.join(words(b['test']) for b in blocked)}: "
                        + " ".join(b["statement"] for b in blocked))
        else:
            headline = f"{fit['verdict']}: {plain}"
    return {"headline": headline, "plain_reason": plain, "stop_reason_plain": stop_plain, "blocked_on_statements": blocked,
            "tests_in_words": {t["name"]: words(t["name"]) for t in tests}}
