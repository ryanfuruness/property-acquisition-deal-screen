"""Command line.

    python -m evals score [--runs runs/] [--label NAME] [--deal ID ...] [--no-write]
    python -m evals stability --runs runs/ runs_repeat1/ [runs_repeat2/ ...] [--label NAME] [--no-write]
    python -m evals report [RESULTS_FILE]        # reprint a saved result (default: latest)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import DEALS_DIR, EVALS_DIR, RESULTS_DIR, RUNS_DIR, rel_path
from .report import stability_text, text_report
from .scorer import latest_results_file, score_runs, write_results
from .stability import run_stability, stability_block, write_stability


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="score every run against truth and write results")
    s.add_argument("--runs", type=Path, default=RUNS_DIR, help="directory holding <deal_id>/run.json (default runs/)")
    s.add_argument("--deals", type=Path, default=DEALS_DIR, help="directory holding <deal_id>/truth.json")
    s.add_argument("--label", default=None,
                   help="name of this iteration; labelled results are added to the history in evals/summary.json")
    s.add_argument("--deal", action="append", help="score only this deal (repeatable)")
    s.add_argument("--no-write", action="store_true", help="print the report only; write nothing")
    s.add_argument("--json", action="store_true", help="print the headline as JSON instead of the text report")
    st = sub.add_parser("stability", help="compare repeated runs of the same deals")
    st.add_argument("--runs", type=Path, nargs="+", required=True, help="two or more run directories")
    st.add_argument("--deals", type=Path, default=DEALS_DIR)
    st.add_argument("--label", default="unlabelled")
    st.add_argument("--no-write", action="store_true")
    r = sub.add_parser("report", help="print the text report for a saved results file")
    r.add_argument("results", nargs="?", type=Path)
    args = ap.parse_args(argv)

    if args.cmd == "score":
        res = score_runs(args.runs.resolve(), args.deals.resolve(), args.label or "unlabelled", args.deal)
        summary = None
        if not args.no_write:
            path = write_results(res, history=args.label is not None)
            summary = json.loads((EVALS_DIR / "summary.json").read_text())
        if args.json:
            print(json.dumps({k: v["value"] for k, v in res["headline"].items()}, indent=1))
        else:
            sys.stdout.write(text_report(res, summary))
        if not args.no_write:
            print(f"\nwrote {rel_path(path)}\nupdated {rel_path(EVALS_DIR / 'summary.json')} and "
                  f"{rel_path(EVALS_DIR / 'REPORT.md')}")
        return 0

    if args.cmd == "stability":
        if len(args.runs) < 2:
            print("stability needs at least two run directories", file=sys.stderr)
            return 2
        res = run_stability([p.resolve() for p in args.runs], args.deals.resolve(), args.label)
        path = None if args.no_write else write_stability(res)
        sys.stdout.write(stability_text(stability_block(res, path)))
        if path:
            print(f"\nwrote {rel_path(path)}\nupdated {rel_path(EVALS_DIR / 'summary.json')} (stability) and "
                  f"{rel_path(EVALS_DIR / 'REPORT.md')}")
        return 0

    path = args.results or latest_results_file(RESULTS_DIR)
    if path is None:
        print("no results yet: run `python -m evals score`", file=sys.stderr)
        return 1
    res = json.loads(Path(path).read_text())
    sys.stdout.write(text_report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
