"""Plain-language reading of the engine's mandate fit, for the memo and the site.

The engine decides the verdict. This module only words it: test names in plain English, and a
deal whose title the documents do not establish is reported as blocked on title. The screen never
decides title (DESIGN.md, item 16), so an unknown title stays unknown in the engine; but nothing
else about the deal matters until legal has confirmed it, so it leads the verdict and the open items.
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
    "target_levered_irr": "levered IRR target",
    "target_equity_multiple": "equity multiple target",
    "min_occupancy": "minimum occupancy",
    "max_lease_expiry_share_in_any_quarter": "lease expiry concentration",
    "max_over_rent_share_of_income": "share of income let above market",
}

TITLE_BLOCK = "Title not stated; legal check required before any further work."


def words(test_name: str) -> str:
    return TEST_WORDS.get(test_name, test_name.replace("_", " "))


def summarise_fit(fit: dict) -> dict:
    """``{headline, plain_reason, blocked_on, tests_in_words}`` for a ``mandate_fit`` result."""
    tests = fit["tests"]
    hard_fail = [t for t in tests if t["kind"] == "hard" and t["status"] == "fail"]
    soft_fail = [t for t in tests if t["kind"] == "soft" and t["status"] == "fail"]
    unknown = [t for t in tests if t["status"] == "unknown"]
    blocked = [{"test": "title", "statement": TITLE_BLOCK} for t in unknown if t["name"] == "title"]
    parts = []
    if hard_fail:
        parts.append("fails the mandate on " + ", ".join(words(t["name"]) for t in hard_fail))
    if soft_fail:
        parts.append("misses " + ", ".join(words(t["name"]) for t in soft_fail))
    others = [t for t in unknown if t["name"] != "title"]
    if others:
        parts.append("cannot yet test " + ", ".join(words(t["name"]) for t in others))
    text = "; ".join(parts)
    plain = ("Meets every mandate test" if not parts else text[0].upper() + text[1:]) + "."
    if blocked and not hard_fail:
        headline = f"{fit['verdict']}, blocked on title: {TITLE_BLOCK}"
    else:
        headline = f"{fit['verdict']}: {plain}"
    return {"headline": headline, "plain_reason": plain, "blocked_on": blocked,
            "tests_in_words": {t["name"]: words(t["name"]) for t in tests}}
