"""Copy recorded runs, page images, eval outputs and docs into site/data/ so the site is self-contained.

    python tools/build_site_data.py                      # from runs/, evals/, docs/
    python tools/build_site_data.py --runs-dir site/dev-fixture/runs   # local design work only

The site never reads anything outside site/. This script:

* copies ``runs/<deal_id>/run.json`` (minified, otherwise unchanged) and ``runs/<deal_id>/pages/*.png``
  to ``site/data/runs/<deal_id>/``;
* copies ``evals/summary.json``, ``evals/FAILURES.md`` and ``evals/tieout/README.md`` to ``site/data/evals/``;
* copies ``docs/BRIEF.md`` and ``docs/research/*.md`` to ``site/data/docs/``;
* copies ``assets/walkthrough.gif`` (repo root or ``site/assets/``) if it exists;
* writes ``site/data/manifest.json``: one summary row per deal for the inbox, plus what exists.

It is deterministic apart from ``generated_at``, and makes no network or model calls.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = SITE / "data"
REPO_URL = "https://github.com/ryanfuruness/property-acquisition-deal-screen"
VERDICT_ORDER = {"Pursue": 0, "Needs work": 1, "Decline": 2}


def norm_verdict(v: str | None) -> str | None:
    """Engine v1 called a hard fail "Pass"; the site says Decline everywhere."""
    return "Decline" if v == "Pass" else v
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _metric(outputs: dict | None, name: str):
    m = ((outputs or {}).get("metrics") or {}).get(name) or {}
    return m.get("value")


def _fact(run: dict, key: str):
    return ((run.get("fact_sheet") or {}).get(key) or {}).get("value")


def _count(v) -> int:
    """mandate_fit gives counts; the engine README describes lists. Accept both."""
    if isinstance(v, (list, tuple)):
        return len(v)
    return int(v or 0)


def summarise(run: dict) -> dict:
    """The inbox row for one run. Reads only run.json."""
    deal = run.get("deal") or {}
    uw = run.get("underwriting") or {}
    out = uw.get("outputs") or {}
    fit = run.get("mandate_fit") or {}
    discs = sorted(run.get("discrepancies") or [], key=lambda d: SEVERITY_ORDER.get(d.get("severity"), 3))
    sev = {k: sum(1 for d in discs if d.get("severity") == k) for k in ("high", "medium", "low")}
    wa = {k: (v.get("value") if isinstance(v, dict) and "value" in v else v)
          for k, v in (out.get("walk_away") or {}).items()}
    asking = _metric(out, "price_aed") or _fact(run, "deal.asking_price_aed")
    units = _metric(out, "unit_count") or ((run.get("rent_roll_summary") or {}).get("summary") or {}).get("unit_count")
    meta = run.get("meta") or {}
    memo = run.get("memo") or {}
    return {
        "deal_id": deal.get("deal_id"),
        "building_name": deal.get("building_name") or _fact(run, "deal.building_name") or deal.get("deal_id"),
        "market_area": deal.get("market_area") or _fact(run, "deal.market_area"),
        "location": _fact(run, "deal.location"),
        "units": units,
        "asking_price_aed": asking,
        "walk_away_price_aed": wa.get("price_aed"),
        "walk_away_binding_constraint": wa.get("binding_constraint"),
        "walk_away_discount_to_asking": wa.get("discount_to_asking"),
        "going_in_net_yield_on_cost": _metric(out, "going_in_net_yield_on_cost"),
        "levered_irr_pre_tax": _metric(out, "levered_irr_pre_tax"),
        "dscr_year1": _metric(out, "dscr_year1"),
        "verdict": norm_verdict(fit.get("verdict")),
        "verdict_reason": fit.get("plain_reason") or fit.get("reason"),
        "verdict_headline": fit.get("headline"),
        "blocked_on_statements": [b.get("statement") for b in fit.get("blocked_on_statements") or [] if b.get("statement")],
        "stop_reason": fit.get("stop_reason_plain") or fit.get("stop_reason"),
        "unlevered_irr_pre_tax": _metric(out, "unlevered_irr_pre_tax"),
        "unlevered_equity_multiple_pre_tax": _metric(out, "unlevered_equity_multiple_pre_tax"),
        "walk_away_most_sensitive": (out.get("walk_away") or {}).get("most_sensitive_label"),
        "walk_away_largest_swing_aed": ((out.get("walk_away") or {}).get("largest_swing_aed") or {}).get("value")
        if isinstance((out.get("walk_away") or {}).get("largest_swing_aed"), dict) else None,
        "notices": len(run.get("notices") or []),
        "hard_fails": _count(fit.get("hard_fails")),
        "soft_fails": _count(fit.get("soft_fails")),
        "unknown": _count(fit.get("unknown")),
        "failed_tests": [t.get("name") for t in fit.get("tests") or [] if t.get("status") != "pass"],
        "engine_version": meta.get("engine_version"),
        "underwriting_status": uw.get("status"),
        "discrepancy_count": len(discs),
        "discrepancy_severity": sev,
        "top_discrepancy": ({"id": discs[0].get("id"), "title": discs[0].get("title"),
                             "severity": discs[0].get("severity")} if discs else None),
        "memo_status": memo.get("status"),
        "scanned_om": any(d.get("scanned") for d in run.get("documents") or []),
        "cost_usd": meta.get("cost_usd"),
        "duration_s": meta.get("duration_s"),
        "pipeline_version": meta.get("pipeline_version"),
        "started_at": meta.get("started_at"),
    }


def copy_runs(runs_dir: Path) -> list[dict]:
    rows = []
    dest_root = OUT / "runs"
    if not runs_dir.is_dir():
        return rows
    for run_path in sorted(runs_dir.glob("*/run.json")):
        deal_dir = run_path.parent
        try:
            run = json.loads(run_path.read_text())
        except json.JSONDecodeError as exc:
            print(f"skip {run_path}: {exc}", file=sys.stderr)
            continue
        dest = dest_root / deal_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "run.json").write_text(json.dumps(run, ensure_ascii=False, separators=(",", ":")))
        pages = deal_dir / "pages"
        if pages.is_dir():
            (dest / "pages").mkdir(exist_ok=True)
            for png in sorted(pages.glob("*.png")):
                shutil.copy2(png, dest / "pages" / png.name)
        row = summarise(run)
        row["deal_id"] = row["deal_id"] or deal_dir.name
        rows.append(row)
    # Screen queue order: verdict, then the richest yield on cost first within each verdict.
    rows.sort(key=lambda r: (VERDICT_ORDER.get(r["verdict"], 3),
                             -(r["going_in_net_yield_on_cost"] if r["going_in_net_yield_on_cost"] is not None else -9),
                             r["deal_id"]))
    return rows


def copy_tree(src: Path, dest: Path, patterns: tuple[str, ...]) -> list[str]:
    copied = []
    if not src.is_dir():
        return copied
    for pat in patterns:
        for f in sorted(src.rglob(pat)):
            if any(part.startswith((".", "__")) for part in f.relative_to(src).parts):
                continue
            target = dest / f.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied.append(f.relative_to(src).as_posix())
    return sorted(set(copied))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    ap.add_argument("--evals-dir", type=Path, default=ROOT / "evals")
    args = ap.parse_args(argv)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    deals = copy_runs(args.runs_dir.resolve())
    # The summary and the hand-kept failure log (the site links to REPORT.md on GitHub). Per-run results files stay in the repo.
    eval_files = copy_tree(args.evals_dir, OUT / "evals", ("summary.json", "FAILURES.md"))
    eval_files += copy_tree(args.evals_dir / "tieout", OUT / "evals" / "tieout", ("README.md",))
    eval_files = ["tieout/README.md" if f == "README.md" else f for f in eval_files]
    docs = copy_tree(ROOT / "docs", OUT / "docs", ("BRIEF.md", "research/*.md"))

    gif = None
    for cand in (ROOT / "assets" / "walkthrough.gif", SITE / "assets" / "walkthrough.gif"):
        if cand.is_file():
            target = SITE / "assets" / "walkthrough.gif"
            if cand.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cand, target)
            gif = "assets/walkthrough.gif"
            break
    gif_info = None
    if gif:
        try:
            from PIL import Image

            with Image.open(SITE / gif) as im:
                total, frames = 0, 0
                for i in range(getattr(im, "n_frames", 1)):
                    im.seek(i)
                    total += im.info.get("duration", 100)
                    frames += 1
                gif_info = {"path": gif, "duration_s": round(total / 1000, 1), "frames": frames,
                            "width": im.size[0], "height": im.size[1]}
        except Exception as exc:
            print(f"gif not measured: {exc}", file=sys.stderr)
            gif_info = {"path": gif}

    index = ROOT / "data" / "deals" / "index.json"
    expected = []
    if index.is_file():
        # Only the public package facts; the planted answers stay with the evals.
        for d in json.loads(index.read_text()).get("deals", []):
            expected.append({k: d.get(k) for k in ("deal_id", "building_name", "area", "units", "asking_price_aed",
                                                   "broker", "documents", "scanned_om")} | {"set": d.get("set") or "dev"})

    mandate = {}
    try:
        import yaml  # PyYAML, already an engine dependency

        m = yaml.safe_load((ROOT / "data" / "mandate.yaml").read_text())
        hard, soft = m["buy_box"]["hard"], m["buy_box"]["soft"]
        debt = m["underwriting"]["debt"]
        mandate = {"firm": m.get("firm"), "as_of": str(m.get("as_of")),
                   "min_going_in_net_yield_on_cost": soft.get("min_going_in_net_yield_on_cost"),
                   "target_unlevered_irr": soft.get("target_unlevered_irr"),
                   "target_unlevered_equity_multiple": soft.get("target_unlevered_equity_multiple"),
                   "max_ltv": debt.get("max_ltv"), "sizing_dscr": debt.get("sizing_dscr"),
                   "min_dscr_year1": hard.get("min_dscr_year1")}
    except Exception as exc:  # the site shows thresholds only if they are available
        print(f"mandate thresholds not added: {exc}", file=sys.stderr)

    sets = {d["deal_id"]: d["set"] for d in expected}
    set_notes = {}
    if index.is_file():
        set_notes = json.loads(index.read_text()).get("sets") or {}
    for row in deals:
        row["set"] = sets.get(row["deal_id"], "dev")

    fixture = "dev-fixture" in args.runs_dir.resolve().as_posix()
    manifest = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "tools/build_site_data.py",
        "repo_url": REPO_URL,
        "synthetic": True,
        "dev_fixture": fixture,
        "mandate": mandate,
        "deals": deals,
        "package_index": expected,
        "sets": set_notes,
        "evals": {"files": eval_files, "summary": "summary.json" in eval_files,
                  "failures": "FAILURES.md" in eval_files},
        "docs": docs,
        "walkthrough_gif": gif,
        "walkthrough": gif_info,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"site/data: {len(deals)} runs, {len(eval_files)} eval files, {len(docs)} docs"
          + (", walkthrough gif" if gif else "") + (" [DEV FIXTURE]" if fixture else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
