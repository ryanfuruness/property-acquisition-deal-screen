"""Stability: the same deal run several times, compared run against run.

    python -m evals stability --runs runs/ runs_repeat1/ runs_repeat2/ [--label NAME]

For every deal with a run.json in at least two of the directories: the verdict of each run and
whether they all agree; the catalogue discrepancy ids of each run and their mean pairwise
Jaccard agreement; the walk-away price range; whether each memo passed. Each run's verdict is
also compared with the engine's verdict on truth. Results go to
``evals/results/<stamp>_stability_<label>.json`` and the ``stability`` block of summary.json.
"""

from __future__ import annotations

import datetime as dt
import json
from itertools import combinations
from pathlib import Path
from statistics import median

from .common import DEALS_DIR, EVALS_DIR, RESULTS_DIR, SETS, deal_sets, get, norm_verdict, ratio, rel_path
from .score_discrepancies import catalogue
from .truth import engine_on_truth, list_truth_deals, load_truth


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _run_record(run_dir: Path, run: dict, expected_verdict: str | None) -> dict:
    cat = set(catalogue())
    ids = sorted({d.get("id") for d in run.get("discrepancies") or [] if d.get("id") in cat})
    v = norm_verdict(get(run, "mandate_fit", "verdict"))
    return {"runs_dir": rel_path(run_dir), "verdict": v, "verdict_correct": v == expected_verdict,
            "discrepancies": ids,
            "walk_away_price_aed": get(run, "underwriting", "outputs", "metrics", "walk_away_price_aed", "value"),
            "memo_status": get(run, "memo", "status"), "memo_passed": get(run, "memo", "status") == "passed",
            "cost_usd": get(run, "meta", "cost_usd"), "started_at": get(run, "meta", "started_at")}


def deal_stability(deal_id: str, records: list[dict], expected_verdict: str | None, deal_set: str) -> dict:
    verdicts = [r["verdict"] for r in records]
    modal = max(set(verdicts), key=verdicts.count)
    sets = [set(r["discrepancies"]) for r in records]
    pairs = [jaccard(a, b) for a, b in combinations(sets, 2)]
    always = sorted(set.intersection(*sets)) if sets else []
    sometimes = sorted(set.union(*sets) - set(always)) if sets else []
    wa = [r["walk_away_price_aed"] for r in records if isinstance(r["walk_away_price_aed"], (int, float))]
    spread = (max(wa) - min(wa)) if wa else None
    return {
        "deal_id": deal_id, "set": deal_set, "n_runs": len(records), "runs": records,
        "expected_verdict": expected_verdict,
        "verdicts": verdicts, "verdict_unanimous": len(set(verdicts)) == 1,
        "verdict_modal": modal, "verdict_modal_share": ratio(verdicts.count(modal), len(verdicts)),
        "verdict_correct_runs": sum(r["verdict_correct"] for r in records),
        "discrepancy_sets": [r["discrepancies"] for r in records],
        "discrepancy_jaccard_mean": round(sum(pairs) / len(pairs), 4) if pairs else None,
        "discrepancy_jaccard_min": round(min(pairs), 4) if pairs else None,
        "discrepancies_in_every_run": always, "discrepancies_in_some_runs": sometimes,
        "walk_away_min": min(wa) if wa else None, "walk_away_max": max(wa) if wa else None,
        "walk_away_spread_aed": spread,
        "walk_away_spread_rel": round(spread / median(wa), 4) if wa and median(wa) else None,
        "memo_passed": [r["memo_passed"] for r in records],
    }


def aggregate(per_deal: list[dict]) -> dict:
    runs = [r for d in per_deal for r in d["runs"]]
    jac = [d["discrepancy_jaccard_mean"] for d in per_deal if d["discrepancy_jaccard_mean"] is not None]
    spr = [d["walk_away_spread_rel"] for d in per_deal if d["walk_away_spread_rel"] is not None]
    n = len(per_deal)
    return {
        "deals": n, "runs": len(runs),
        "verdict_unanimous": {"value": ratio(sum(d["verdict_unanimous"] for d in per_deal), n),
                              "k": sum(d["verdict_unanimous"] for d in per_deal), "n": n},
        "verdict_correct_runs": {"value": ratio(sum(r["verdict_correct"] for r in runs), len(runs)),
                                 "k": sum(r["verdict_correct"] for r in runs), "n": len(runs)},
        "discrepancy_sets_identical": {"value": ratio(sum(d["discrepancy_jaccard_min"] == 1.0 for d in per_deal), n),
                                       "k": sum(d["discrepancy_jaccard_min"] == 1.0 for d in per_deal), "n": n},
        "discrepancy_jaccard_mean": {"value": round(sum(jac) / len(jac), 4) if jac else None, "n": len(jac)},
        "walk_away_spread_rel_mean": {"value": round(sum(spr) / len(spr), 4) if spr else None, "n": len(spr)},
        "walk_away_spread_rel_max": {"value": max(spr) if spr else None, "n": len(spr)},
        "memo_pass_rate": {"value": ratio(sum(r["memo_passed"] for r in runs), len(runs)),
                           "k": sum(r["memo_passed"] for r in runs), "n": len(runs)},
    }


def run_stability(run_dirs: list[Path], deals_dir: Path = DEALS_DIR, label: str = "unlabelled",
                  sets: dict[str, str] | None = None) -> dict:
    sets = sets if sets is not None else deal_sets(deals_dir)
    per_deal, single = [], {}
    for d in list_truth_deals(deals_dir):
        found = []
        for rd in run_dirs:
            p = Path(rd) / d / "run.json"
            if p.exists():
                try:
                    found.append((Path(rd), json.loads(p.read_text())))
                except (OSError, json.JSONDecodeError):
                    continue
        if len(found) < 2:
            single[d] = f"{len(found)} readable run(s)"
            continue
        exp = engine_on_truth(load_truth(d, deals_dir))["verdict"]
        per_deal.append(deal_stability(d, [_run_record(rd, r, exp) for rd, r in found], exp, sets.get(d, "dev")))
    return {
        "kind": "stability", "label": label,
        "scored_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_dirs": [rel_path(r) for r in run_dirs],
        "aggregate": aggregate(per_deal),
        "aggregate_by_set": {s: aggregate([p for p in per_deal if p["set"] == s]) for s in SETS},
        "deals": per_deal, "deals_not_compared": single,
    }


def write_stability(res: dict, results_dir: Path = RESULTS_DIR, evals_dir: Path = EVALS_DIR) -> Path:
    from .report import markdown_report
    from .scorer import _slug, latest_results_file
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromisoformat(res["scored_at"]).strftime("%Y%m%dT%H%M%SZ")
    path = results_dir / f"{stamp}_stability_{_slug(res['label'])}.json"
    path.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str))
    summary_path = evals_dir / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"history": []}
    summary["stability"] = stability_block(res, path)
    summary_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    latest = latest_results_file(results_dir)
    if latest:
        (evals_dir / "REPORT.md").write_text(markdown_report(json.loads(latest.read_text()), summary))
    return path


def stability_block(res: dict, path: Path | None = None) -> dict:
    """The ``stability`` block of summary.json (also what the reports render)."""
    return {
        "label": res["label"], "scored_at": res["scored_at"], "results_file": rel_path(path) if path else None,
        "run_dirs": res["run_dirs"], "aggregate": res["aggregate"], "aggregate_by_set": res["aggregate_by_set"],
        "per_deal": {d["deal_id"]: {k: d[k] for k in (
            "set", "n_runs", "expected_verdict", "verdicts", "verdict_unanimous", "discrepancy_sets",
            "discrepancy_jaccard_mean", "walk_away_min", "walk_away_max", "walk_away_spread_rel", "memo_passed")}
            for d in res["deals"]},
        "deals_not_compared": res["deals_not_compared"],
    }
