"""Metric 4: discrepancies, against ``truth.planted_discrepancies`` by catalogue id.

A detection counts only if its id is the planted id (or maps to it through ``ALIASES``, which
is empty: see evals/README.md for each candidate overlap considered and why it was rejected).
Every catalogue id the run flags that was not planted is a false positive. Findings with ids
outside the catalogue (the review's ``other_om_claim``) are listed but not scored.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .common import DEALS_DIR, check, ratio

SECTION = "discrepancies"

# run id -> catalogue id it should be credited as. Keep empty unless two catalogue entries
# genuinely describe the same finding; justify each entry in evals/README.md.
ALIASES: dict[str, str] = {}


@lru_cache(maxsize=1)
def catalogue() -> tuple[str, ...]:
    idx = json.loads((DEALS_DIR / "index.json").read_text())
    return tuple(idx["discrepancy_catalogue"][k] for k in sorted(idx["discrepancy_catalogue"], key=int))


def score(deal_id: str, truth: dict, run: dict) -> dict:
    cat = set(catalogue())
    planted = sorted({d["id"] for d in truth.get("planted_discrepancies") or []})
    found_raw = [d for d in run.get("discrepancies") or []]
    flagged: dict[str, dict] = {}
    unscored = []
    for d in found_raw:
        i = ALIASES.get(d.get("id"), d.get("id"))
        if i in cat:
            flagged.setdefault(i, d)
        else:
            unscored.append({"id": d.get("id"), "title": d.get("title"), "severity": d.get("severity")})
    tp = sorted(set(planted) & set(flagged))
    fn = sorted(set(planted) - set(flagged))
    fp = sorted(set(flagged) - set(planted))
    not_planted = truth.get("rule_checks_not_planted") or {}
    checks = []
    for i in tp:
        checks.append(check(SECTION, deal_id, i, "flag", "flagged", True, "true_positive",
                            detected_by=flagged[i].get("detected_by"), severity=flagged[i].get("severity")))
    for i in fn:
        exp = next((d.get("expected") for d in truth["planted_discrepancies"] if d["id"] == i), None)
        checks.append(check(SECTION, deal_id, i, "flag", "not flagged", False, "false_negative",
                            "planted: " + json.dumps(exp, default=str)[:300]))
    for i in fp:
        d = flagged[i]
        ctx = not_planted.get(i)
        checks.append(check(SECTION, deal_id, i, "no flag", "flagged", False, "false_positive",
                            f"run: {d.get('title')}" + (f" | truth values for this check: "
                                                         f"{json.dumps(ctx, default=str)[:300]}" if ctx else ""),
                            detected_by=d.get("detected_by"), severity=d.get("severity")))
    return {"checks": checks, "summary": {
        "planted": planted, "flagged": sorted(flagged), "tp": tp, "fn": fn, "fp": fp,
        "recall": ratio(len(tp), len(planted)) if planted else None,
        "precision": ratio(len(tp), len(flagged)) if flagged else None,
        "clean_deal": not planted, "unscored_findings": unscored,
        "rejected_model_findings": len(run.get("rejected_model_findings") or []),
    }}


def aggregate(per_deal: dict[str, dict]) -> dict:
    """Micro recall/precision over deals, per-id table, false flags on clean deals."""
    tp = sum(len(s["tp"]) for s in per_deal.values())
    fn = sum(len(s["fn"]) for s in per_deal.values())
    fp = sum(len(s["fp"]) for s in per_deal.values())
    by_id: dict[str, dict] = {i: {"planted": 0, "tp": 0, "fn": 0, "fp": 0} for i in catalogue()}
    for s in per_deal.values():
        for k in ("tp", "fn", "fp"):
            for i in s[k]:
                by_id.setdefault(i, {"planted": 0, "tp": 0, "fn": 0, "fp": 0})[k] += 1
        for i in s["planted"]:
            by_id[i]["planted"] += 1
    for v in by_id.values():
        v["recall"] = ratio(v["tp"], v["planted"]) if v["planted"] else None
        v["precision"] = ratio(v["tp"], v["tp"] + v["fp"]) if (v["tp"] + v["fp"]) else None
    clean = {d: s["fp"] for d, s in per_deal.items() if s["clean_deal"]}
    planted_deals = {d: s["fp"] for d, s in per_deal.items() if not s["clean_deal"]}
    return {
        "tp": tp, "fn": fn, "fp": fp,
        "recall": ratio(tp, tp + fn), "precision": ratio(tp, tp + fp),
        "by_id": by_id,
        "clean_deals": sorted(clean),
        "false_flags_on_clean_deals": sum(len(v) for v in clean.values()),
        "false_flags_on_clean_deals_by_deal": clean,
        "false_flags_on_planted_deals": sum(len(v) for v in planted_deals.values()),
    }
