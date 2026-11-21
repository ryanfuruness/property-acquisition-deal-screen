"""Score every run against truth and write the results.

``score_runs`` returns the full results dict; ``write_results`` saves it to
``evals/results/<timestamp>_<label>.json``, refreshes ``evals/summary.json`` (latest headline
plus the history of labelled runs) and regenerates ``evals/REPORT.md``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import score_discrepancies, score_memo, score_om, score_opex, score_rentroll, score_underwriting
from .common import DEALS_DIR, EVALS_DIR, RESULTS_DIR, RUNS_DIR, SETS, deal_sets, norm_verdict, ratio, rel_path
from .truth import engine_on_truth, list_truth_deals, load_truth

SCORER_VERSION = "1.1.0"
UW_LABEL = "Underwriting inputs (engine on extracted vs true inputs)"


def _hl(value, k=None, n=None, label=""):
    return {"value": value, "k": k, "n": n, "label": label}


def score_deal(deal_id: str, truth: dict, run: dict, expected: dict | None = None) -> dict:
    expected = expected or engine_on_truth(truth)
    return {
        "om": score_om.score(deal_id, truth, run),
        "rent_roll": score_rentroll.score(deal_id, truth, run),
        "opex": score_opex.score(deal_id, truth, run),
        "discrepancies": score_discrepancies.score(deal_id, truth, run),
        "underwriting": score_underwriting.score(deal_id, truth, run, expected),
        "memo": score_memo.score(deal_id, run),
        "meta": score_memo.score_meta(deal_id, run),
        "expected_from_engine": expected,
    }


def load_runs(runs_dir: Path, deal_ids: list[str]) -> tuple[dict[str, dict], dict[str, str]]:
    runs, problems = {}, {}
    for d in deal_ids:
        p = runs_dir / d / "run.json"
        if not p.exists():
            problems[d] = "no run.json"
            continue
        try:
            runs[d] = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            problems[d] = f"unreadable run.json: {exc.__class__.__name__}: {exc}"
    return runs, problems


def score_runs(runs_dir: Path = RUNS_DIR, deals_dir: Path = DEALS_DIR, label: str = "unlabelled",
               deal_ids: list[str] | None = None, runs: dict[str, dict] | None = None,
               sets: dict[str, str] | None = None) -> dict:
    """Score runs (read from ``runs_dir`` unless given) for every deal with a truth.json."""
    all_deals = deal_ids or list_truth_deals(deals_dir)
    if runs is None:
        runs, problems = load_runs(runs_dir, all_deals)
    else:
        problems = {d: "no run.json" for d in all_deals if d not in runs}
    deals = {}
    for d in all_deals:
        if d not in runs:
            continue
        deals[d] = score_deal(d, load_truth(d, deals_dir), runs[d])
    res = {
        "label": label,
        "scored_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "scorer_version": SCORER_VERSION,
        "runs_dir": rel_path(runs_dir),
        "deals_scored": sorted(deals),
        "deal_sets": {d: (sets if sets is not None else deal_sets(deals_dir)).get(d, "dev") for d in all_deals},
        "deals_not_scored": problems,
        "pipeline_versions": sorted({str(r.get("meta", {}).get("pipeline_version")) for r in runs.values()}),
    }
    res.update(aggregate(deals))
    res["by_set"] = {s: aggregate({d: v for d, v in deals.items() if res["deal_sets"][d] == s}) for s in SETS}
    res["headline_by_set"] = {**{s: res["by_set"][s]["headline"] for s in SETS}, "combined": res["headline"]}
    res["deals"] = {d: _strip(s) for d, s in deals.items()}
    res["checks"] = [c for s in deals.values() for c in _all_checks(s)]
    res["misses"] = [c for c in res["checks"] if not c["ok"]]
    # Right values the run could not verify (they cannot feed the engine) and invalid citations: not misses of the
    # value, but listed in the report.
    res["verification_gaps"] = (
        [{"deal_id": c["deal_id"], "item": c["item"], "kind": "correct but not verified", "run_status": c.get("run_status")}
         for c in res["checks"] if c["section"] == "om" and c["ok"] and not c.get("trusted")] +
        [{"deal_id": d, "item": c["item"], "kind": "citation not valid", "run_status": c["run_status"],
          "cited_page": c["cited_page"], "truth_pages": c["truth_pages"], "value_correct": c["value_correct"]}
         for d, s in deals.items() for c in s["om"]["citations"] if not c["valid"]])
    return res


def _all_checks(s: dict) -> list[dict]:
    out = []
    for sec in ("om", "rent_roll", "opex", "discrepancies", "underwriting", "memo"):
        out += s[sec]["checks"]
        out += s[sec].get("unit_checks", [])
    return out


def _strip(s: dict) -> dict:
    """Per-deal detail without the check lists (they are in the top-level ``checks``)."""
    out = {sec: {k: v for k, v in s[sec].items() if k not in ("checks", "unit_checks")}
           for sec in ("om", "rent_roll", "opex", "discrepancies", "underwriting", "memo", "meta")}
    out["expected_from_engine"] = s["expected_from_engine"]
    return out


def aggregate(deals: dict[str, dict]) -> dict:
    n = len(deals)
    S = lambda sec: [s[sec]["summary"] for s in deals.values()]  # noqa: E731

    om_checks = [c for s in deals.values() for c in s["om"]["checks"]]
    om_ok = sum(c["ok"] for c in om_checks)
    om_trusted = sum(c["trusted"] for c in om_checks)
    cits = [c for s in deals.values() for c in s["om"]["citations"]]
    by_field: dict[str, dict] = {}
    for c in om_checks:
        f = by_field.setdefault(c["item"], {"n": 0, "correct": 0, "trusted_correct": 0, "missed": 0, "spurious": 0, "wrong": 0})
        f["n"] += 1
        f["correct"] += c["ok"]
        f["trusted_correct"] += c["trusted"]
        if c["outcome"] in ("missed", "spurious", "wrong"):
            f[c["outcome"]] += 1
    for f in by_field.values():
        f["accuracy"] = ratio(f["correct"], f["n"])

    rr = S("rent_roll")
    t_units = sum(x["truth_units"] for x in rr)
    r_units = sum(x["run_units"] for x in rr)
    matched = sum(x["matched"] for x in rr)
    unit_fields: dict[str, dict] = {}
    for x in rr:
        for f, v in (x.get("unit_fields") or {}).items():
            u = unit_fields.setdefault(f, {"n": 0, "correct": 0})
            u["n"] += v["n"]
            u["correct"] += v["correct"]
    for u in unit_fields.values():
        u["accuracy"] = ratio(u["correct"], u["n"])
    uf_n = sum(u["n"] for u in unit_fields.values())
    uf_ok = sum(u["correct"] for u in unit_fields.values())
    rr_tot_n = sum(x.get("totals_n", 0) for x in rr)
    rr_tot_ok = sum(x.get("totals_correct", 0) for x in rr)

    op = S("opex")
    cat_n = sum(x["categories_n"] for x in op)
    cat_ok = sum(x["categories_correct"] for x in op)

    disc = score_discrepancies.aggregate({d: s["discrepancies"]["summary"] for d, s in deals.items()})

    uw = S("underwriting")
    uw_n = sum(x["n"] for x in uw)
    uw_ok = sum(x["within_tolerance"] for x in uw)

    def mean_abs_rel(metric):
        vals = [abs(x["errors"][metric]["rel_error"]) for x in uw
                if metric in x["errors"] and x["errors"][metric]["rel_error"] is not None]
        return (round(sum(vals) / len(vals), 4) if vals else None), len(vals)

    def mean_abs(metric):
        vals = [abs(x["errors"][metric]["abs_error"]) for x in uw
                if metric in x["errors"] and x["errors"][metric]["abs_error"] is not None]
        return (round(sum(vals) / len(vals), 5) if vals else None), len(vals)

    verdict_ok = sum(x["verdict_ok"] for x in uw)
    memo = S("memo")
    nums = sum(x["numbers"] or 0 for x in memo)
    grounded = sum(x["grounded"] or 0 for x in memo)
    memo_pass = sum(x["status"] == "passed" for x in memo)
    meta = S("meta")
    costs = [x["cost_usd"] for x in meta if x["cost_usd"] is not None]
    durs = [x["duration_s"] for x in meta if x["duration_s"] is not None]

    noi_mare, noi_n = mean_abs_rel("noi_year1")
    wa_mare, wa_n = mean_abs_rel("walk_away_price_aed")
    yoc_mae, yoc_n = mean_abs("going_in_net_yield_on_cost")
    irr_mae, irr_n = mean_abs("levered_irr_pre_tax")
    headline = {
        "deals_scored": _hl(n, label="Deals scored"),
        "om_field_accuracy": _hl(ratio(om_ok, len(om_checks)), om_ok, len(om_checks), "OM fields correct"),
        "om_trusted_accuracy": _hl(ratio(om_trusted, len(om_checks)), om_trusted, len(om_checks),
                                   "OM fields correct and verified"),
        "om_citation_valid": _hl(ratio(sum(c["valid"] for c in cits), len(cits)), sum(c["valid"] for c in cits),
                                 len(cits), "Citations valid"),
        "om_citation_page_match": _hl(ratio(sum(c["page_match"] for c in cits), len(cits)),
                                      sum(c["page_match"] for c in cits), len(cits), "Cited page = truth page"),
        "rent_roll_unit_recall": _hl(ratio(matched, t_units), matched, t_units, "Rent-roll units found"),
        "rent_roll_unit_precision": _hl(ratio(matched, r_units), matched, r_units, "Parsed rows that are real units"),
        "rent_roll_summary_rows_as_units": _hl(sum(x["summary_rows_as_units"] for x in rr), label="Summary rows counted as units"),
        "rent_roll_unit_field_accuracy": _hl(ratio(uf_ok, uf_n), uf_ok, uf_n, "Unit fields correct (matched units)"),
        "rent_roll_totals_accuracy": _hl(ratio(rr_tot_ok, rr_tot_n), rr_tot_ok, rr_tot_n, "Rent-roll totals correct"),
        "rent_roll_in_place_rent_ok": _hl(ratio(sum(bool(x.get("in_place_rent_ok")) for x in rr), n),
                                          sum(bool(x.get("in_place_rent_ok")) for x in rr), n, "In-place rent within 0.5%"),
        "rent_roll_occupancy_ok": _hl(ratio(sum(bool(x.get("occupancy_ok")) for x in rr), n),
                                      sum(bool(x.get("occupancy_ok")) for x in rr), n, "Occupancy within 0.5%"),
        "opex_category_accuracy": _hl(ratio(cat_ok, cat_n), cat_ok, cat_n, "Statement categories within 0.5%"),
        "opex_period_ok": _hl(ratio(sum(bool(x["period_ok"]) for x in op), n), sum(bool(x["period_ok"]) for x in op), n,
                              "Statement period and annualisation right"),
        "discrepancy_recall": _hl(disc["recall"], disc["tp"], disc["tp"] + disc["fn"], "Planted discrepancies found"),
        "discrepancy_precision": _hl(disc["precision"], disc["tp"], disc["tp"] + disc["fp"], "Flags that were planted"),
        "false_flags_on_clean_deals": _hl(disc["false_flags_on_clean_deals"], n=len(disc["clean_deals"]),
                                          label="False flags on clean deals"),
        # Key kept as "underwriting_within_tolerance" for the site; what it measures is the label.
        "underwriting_within_tolerance": _hl(ratio(uw_ok, uw_n), uw_ok, uw_n, f"{UW_LABEL}: outputs within tolerance"),
        "noi_mean_abs_rel_error": _hl(noi_mare, n=noi_n, label="Underwriting inputs: Year-1 NOI mean abs. relative error"),
        "walk_away_mean_abs_rel_error": _hl(wa_mare, n=wa_n, label="Underwriting inputs: walk-away price mean abs. relative error"),
        "yield_on_cost_mean_abs_error": _hl(yoc_mae, n=yoc_n, label="Underwriting inputs: yield on cost mean abs. error"),
        "levered_irr_mean_abs_error": _hl(irr_mae, n=irr_n, label="Underwriting inputs: levered IRR mean abs. error"),
        "verdict_agreement": _hl(ratio(verdict_ok, n), verdict_ok, n, "Verdict matches engine on truth"),
        "memo_grounding": _hl(ratio(grounded, nums) if nums else None, grounded, nums, "Memo numbers grounded"),
        "memo_pass_rate": _hl(ratio(memo_pass, n), memo_pass, n, "Memos that passed the number check"),
        "cost_usd_per_deal": _hl(round(sum(costs) / len(costs), 4) if costs else None, n=len(costs),
                                 label="Cost per deal (USD)"),
        "cost_usd_total": _hl(round(sum(costs), 4) if costs else None, n=len(costs), label="Cost, all deals (USD)"),
        "duration_s_per_deal": _hl(round(sum(durs) / len(durs), 1) if durs else None, n=len(durs),
                                   label="Time per deal (s)"),
    }
    return {"headline": headline, "om_by_field": by_field, "rent_roll_unit_fields": unit_fields,
            "discrepancies": disc}


# ---------------------------------------------------------------------------- writing


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "unlabelled"


def per_deal_brief(res: dict) -> dict:
    out = {}
    for d, s in res["deals"].items():
        om = s["om"]["summary"]
        rr = s["rent_roll"]["summary"]
        di = s["discrepancies"]["summary"]
        uw = s["underwriting"]["summary"]
        out[d] = {
            "om_accuracy": ratio(om["correct"], om["n"]),
            "rent_roll_recall": rr["recall"], "rent_roll_precision": rr["precision"],
            "opex_category_accuracy": s["opex"]["summary"].get("category_accuracy"),
            "opex_period_ok": s["opex"]["summary"]["period_ok"],
            "discrepancies": {"tp": len(di["tp"]), "fn": len(di["fn"]), "fp": len(di["fp"])},
            "noi_rel_error": uw["errors"].get("noi_year1", {}).get("rel_error"),
            "walk_away_rel_error": uw["errors"].get("walk_away_price_aed", {}).get("rel_error"),
            "set": res.get("deal_sets", {}).get(d, "dev"),
            "verdict": {"expected": norm_verdict(uw["verdict_expected"]), "got": norm_verdict(uw["verdict_got"])},
            "memo": {"status": s["memo"]["summary"]["status"], "grounding": s["memo"]["summary"]["share"]},
            "cost_usd": s["meta"]["summary"]["cost_usd"], "duration_s": s["meta"]["summary"]["duration_s"],
            "pipeline_version": s["meta"]["summary"]["pipeline_version"],
        }
    return out


def write_results(res: dict, results_dir: Path = RESULTS_DIR, evals_dir: Path = EVALS_DIR,
                  history: bool = True) -> Path:
    from .report import markdown_report
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromisoformat(res["scored_at"]).strftime("%Y%m%dT%H%M%SZ")
    path = results_dir / f"{stamp}_{_slug(res['label'])}.json"
    path.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))

    summary_path = evals_dir / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"history": []}
    entry = {"label": res["label"], "scored_at": res["scored_at"], "results_file": str(path.relative_to(evals_dir.parent))
             if path.is_relative_to(evals_dir.parent) else str(path),
             "pipeline_versions": res["pipeline_versions"], "deals_scored": res["deals_scored"],
             "headline": {k: v["value"] for k, v in res["headline"].items()},
             "headline_by_set": {s: {k: v["value"] for k, v in h.items()}
                                 for s, h in (res.get("headline_by_set") or {}).items()},
             "deal_sets": res.get("deal_sets", {})}
    summary["latest"] = {**entry, "headline_detail": res["headline"],
                         "headline_detail_by_set": res.get("headline_by_set"), "per_deal": per_deal_brief(res),
                         "deals_not_scored": res["deals_not_scored"]}
    if history:
        hist = [h for h in summary.get("history", []) if h.get("label") != res["label"]]
        hist.append(entry)
        summary["history"] = sorted(hist, key=lambda h: h["scored_at"])
    summary["updated_at"] = res["scored_at"]
    summary["note"] = ("Written by `python -m evals score`. latest = most recent scoring; history = one entry per "
                       "label (re-scoring a label replaces its entry). headline = all scored deals; headline_by_set = "
                       "dev, heldout and combined. stability = latest `python -m evals stability`. "
                       "Metric definitions: evals/README.md.")
    summary_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    (evals_dir / "REPORT.md").write_text(markdown_report(res, summary))
    return path


def latest_results_file(results_dir: Path = RESULTS_DIR) -> Path | None:
    """Most recent scoring results file (stability files excluded)."""
    files = sorted(p for p in results_dir.glob("*.json") if "_stability_" not in p.name)
    return files[-1] if files else None
