"""Shared pieces of the scorer: tolerances, normalisers and the check record.

Every comparison the scorer makes becomes one *check*: a flat dict with the section, deal,
item, expected value, value the run gave, whether it passed, an outcome word and a note. The
headline numbers are computed from checks, and the report lists every failed check, so a
number on the site can always be traced back to the comparisons behind it.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from typing import Any

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
DEALS_DIR = REPO_ROOT / "data" / "deals"
RUNS_DIR = REPO_ROOT / "runs"
EVALS_DIR = REPO_ROOT / "evals"
RESULTS_DIR = EVALS_DIR / "results"

# Tolerances (documented in evals/README.md). Change them here only, and say so in FAILURES.md.
REL_TOL = 0.005                # numbers: relative 0.5%
ABS_FLOOR = 1e-9               # so that 0 == 0 passes
UW_TOL = {                     # underwriting outputs vs the engine run on truth
    "noi_year1": ("rel", 0.02),
    "going_in_net_yield_on_cost": ("abs", 0.001),
    "levered_irr_pre_tax": ("abs", 0.005),
    "walk_away_price_aed": ("rel", 0.02),
}

# Outcomes of a field comparison.
CORRECT, CORRECT_NULL, WRONG, MISSED, SPURIOUS = "correct", "correct_null", "wrong", "missed", "spurious"
OK_OUTCOMES = {CORRECT, CORRECT_NULL}


def check(section: str, deal_id: str, item: str, expected: Any, got: Any, ok: bool,
          outcome: str | None = None, note: str | None = None, **extra: Any) -> dict:
    rec = {"section": section, "deal_id": deal_id, "item": item, "expected": expected, "got": got,
           "ok": bool(ok), "outcome": outcome or ("correct" if ok else "wrong")}
    if note:
        rec["note"] = note
    rec.update(extra)
    return rec


# ---------------------------------------------------------------------------- numbers


def is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not (isinstance(x, float) and math.isnan(x))


def num_close(expected: float, got: float, rel: float = REL_TOL) -> bool:
    return abs(got - expected) <= max(rel * abs(expected), ABS_FLOOR)


def rel_err(expected: float | None, got: float | None) -> float | None:
    if not (is_num(expected) and is_num(got)) or expected == 0:
        return None
    return (got - expected) / abs(expected)


def ratio(n: float, d: float) -> float | None:
    return round(n / d, 4) if d else None


# ---------------------------------------------------------------------------- text


def norm_text(s: Any) -> str:
    """Case-, accent-, punctuation- and whitespace-insensitive text."""
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def squash(s: Any) -> str:
    """Letters and digits only (for codes such as plot numbers, floors and unit ids)."""
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", str(s or "")).casefold())


def norm_unit_id(u: Any) -> str:
    """Unit ids: '101', 101, 101.0, ' 101 ' and 'Unit 101' are the same unit; 'G-01' == 'G01'."""
    if is_num(u):
        u = str(int(u)) if float(u).is_integer() else str(u)
    s = str(u or "").strip()
    s = re.sub(r"^(?:unit|flat|apt|apartment|shop)\s*(?:no\.?)?\s*", "", s, flags=re.I)
    s = re.sub(r"\.0$", "", s)
    return squash(s)


def norm_company(s: Any) -> str:
    """Company names without legal suffixes (L.L.C, LLC, FZE, Ltd)."""
    t = norm_text(s)
    t = re.sub(r"\b(l l c|llc|fze|fzco|ltd|limited|co|company|est|establishment)\b", " ", t)
    return " ".join(t.split())


def token_overlap(a: str, b: str) -> float:
    """Share of the shorter text's word tokens that appear in the other (0..1)."""
    ta, tb = set(norm_text(a).split()), set(norm_text(b).split())
    if not ta or not tb:
        return 0.0
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small & big) / len(small)


def parse_date(s: Any) -> dt.date | None:
    if isinstance(s, dt.date):
        return s
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def get(d: Any, *path: Any, default: Any = None) -> Any:
    """Nested get that tolerates missing keys and None along the way."""
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int) and -len(d) <= p < len(d):
            d = d[p]
        else:
            return default
        if d is None:
            return default
    return d


def summarise_checks(checks: list[dict]) -> dict:
    n = len(checks)
    ok = sum(1 for c in checks if c["ok"])
    return {"n": n, "correct": ok, "accuracy": ratio(ok, n)}
