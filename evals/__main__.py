"""Command line.

    python -m evals score [--runs runs/] [--label NAME] [--deal ID ...] [--no-write]
    python -m evals report [RESULTS_FILE]        # reprint a saved result (default: latest)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import DEALS_DIR, EVALS_DIR, RESULTS_DIR, RUNS_DIR
from .report import markdown_report, text_report
from .scorer import score_runs, write_results


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
            print(f"\nwrote {path}\nupdated {EVALS_DIR / 'summary.json'} and {EVALS_DIR / 'REPORT.md'}")
        return 0

    path = args.results or max(RESULTS_DIR.glob("*.json"), default=None)
    if path is None:
        print("no results yet: run `python -m evals score`", file=sys.stderr)
        return 1
    res = json.loads(Path(path).read_text())
    sys.stdout.write(text_report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
