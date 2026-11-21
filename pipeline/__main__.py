"""Command line: ``python -m pipeline run <deal_id>`` and ``python -m pipeline run-all``."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
import time

from .config import BUDGET_USD, DEFAULT_MODEL, MAPPING_MODEL, RunSettings
from .llm import BudgetExceeded, Ledger
from .run import list_deals, run_deal


def _summary(run: dict) -> str:
    fit, meta = run["mandate_fit"], run["meta"]
    wa = ((run["underwriting"].get("outputs") or {}).get("metrics", {}).get("walk_away_price_aed") or {}).get("value")
    return (f"{run['deal']['deal_id']}: {fit['verdict']} | discrepancies "
            f"{len(run['discrepancies'])} | walk-away {'AED {:,.0f}'.format(wa) if wa else 'n/a'} | memo "
            f"{run['memo']['status']} | USD {meta['cost_usd']:.3f} | {meta['duration_s']:.0f}s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "run-all"):
        p = sub.add_parser(name)
        if name == "run":
            p.add_argument("deal_id")
        p.add_argument("--model", default=DEFAULT_MODEL, help="model for extraction, review and memo")
        p.add_argument("--mapping-model", default=None,
                       help=f"model for rent-roll and statement mapping (default: --model, or {MAPPING_MODEL})")
        p.add_argument("--replay", action="store_true",
                       help="reuse stored model responses for identical requests (development; no cost)")
        p.add_argument("--budget", type=float, default=BUDGET_USD, help="refuse to start above this ledger total (USD)")
    args = ap.parse_args(argv)
    settings = RunSettings(model=args.model, mapping_model=args.mapping_model or args.model,
                           budget_usd=args.budget, replay=args.replay)
    ledger = Ledger(settings.runs_dir / "_ledger.json")
    deals = [args.deal_id] if args.cmd == "run" else list_deals(settings.deals_dir)
    status = 0
    for deal_id in deals:
        t = time.monotonic()
        try:
            print(_summary(run_deal(deal_id, settings, ledger=ledger)), flush=True)
        except BudgetExceeded as exc:
            print(f"stopped: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001 - report and continue with the next deal
            if os.environ.get("DEAL_SCREEN_DEBUG"):
                traceback.print_exc()
            print(f"{deal_id}: FAILED after {time.monotonic() - t:.0f}s: {exc.__class__.__name__}: {exc}",
                  file=sys.stderr)
            status = 1
    print(f"ledger total USD {ledger.total_usd:.2f}", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
