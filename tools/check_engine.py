#!/usr/bin/env python3
"""Run engine v2 and mandate fit on each deal's truth (engine_inputs + deal_facts) and print a summary.

    python tools/check_engine.py [--set dev|heldout] [--md] [deal_id ...]

Used to calibrate asking prices; results are not written into truth.json (expected_verdict stays null).
A deal whose area has no screen reference (out of mandate) cannot be underwritten: mandate_fit then runs
with uw_result=None and declines on the area filter.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from engine import load_mandate, load_market, mandate_fit, underwrite  # noqa: E402


def run(truth, mandate, market):
    ei, facts = truth["true_building"]["engine_inputs"], truth["true_building"]["deal_facts"]
    try:
        r = underwrite(ei, mandate, market)
    except Exception as e:  # out-of-mandate area: no screen reference
        r, err = None, f"{type(e).__name__}: {e}"
    else:
        err = None
    fit = mandate_fit(facts, r, mandate)
    m = {k: v["value"] for k, v in r["metrics"].items()} if r else {}
    return {
        "deal_id": truth["deal_id"], "price": ei["price_aed"], "gross_ask": truth["true_building"]["metrics"]["gross_yield_in_place_on_price"],
        "entry_yield": m.get("entry_yield_on_price"), "exit_yield": m.get("exit_yield"),
        "yield_on_cost": m.get("going_in_net_yield_on_cost"), "noi": m.get("noi_year1"),
        "unlev_irr": m.get("unlevered_irr_pre_tax"), "unlev_em": m.get("unlevered_equity_multiple_pre_tax"),
        "lev_irr": m.get("levered_irr_pre_tax"), "dscr": m.get("dscr_year1"),
        "sizing": r["debt"]["sizing_constraint"] if r else None, "walk": m.get("walk_away_price_aed"),
        "verdict": fit["verdict"], "blocked_on": fit["blocked_on"], "stop_reason": fit["stop_reason"],
        "misses": [x["name"] for x in fit["tests"] if x["status"] != "pass"],
        "planted": [d["num"] for d in truth["planted_discrepancies"]], "engine_error": err,
        "warnings": r.get("warnings", []) if r else [],
    }


def pct(x, d=2):
    return "-" if x is None else f"{x * 100:.{d}f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--set", choices=["dev", "heldout"])
    ap.add_argument("--md", action="store_true", help="markdown table")
    a = ap.parse_args()
    mandate, market = load_mandate(), load_market()
    index = json.loads((REPO / "data" / "deals" / "index.json").read_text()) if (REPO / "data/deals/index.json").exists() else {"deals": []}
    sets = {d["deal_id"]: d.get("set") for d in index["deals"]}
    rows = []
    for p in sorted((REPO / "data" / "deals").glob("*/truth.json")):
        t = json.loads(p.read_text())
        if a.ids and t["deal_id"] not in a.ids:
            continue
        if a.set and sets.get(t["deal_id"]) != a.set:
            continue
        rows.append((sets.get(t["deal_id"]), run(t, mandate, market)))
    if a.md:
        print("| Set | Deal | Ask (AED M) | Gross ask | Entry -> exit yield | Yield on cost | Unlev IRR | Lev IRR | DSCR (sizing) | Walk-away / ask | Verdict | Blocked on / stop reason | Planted |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for st, x in rows:
        walk = f"{x['walk'] / 1e6:.1f}M ({x['walk'] / x['price'] * 100:.0f}%)" if x["walk"] else "-"
        dscr = f"{x['dscr']:.2f} ({x['sizing']})" if x["dscr"] else "-"
        why = x["stop_reason"] or (f"blocked on {x['blocked_on']}" if x["blocked_on"] else ", ".join(x["misses"]) or "-")
        if a.md:
            print(f"| {st} | {x['deal_id']} | {x['price'] / 1e6:.1f} | {pct(x['gross_ask'])} | {pct(x['entry_yield'])} -> {pct(x['exit_yield'])} | "
                  f"{pct(x['yield_on_cost'])} | {pct(x['unlev_irr'])} | {pct(x['lev_irr'])} | {dscr} | {walk} | {x['verdict']} | {why} | {x['planted'] or '-'} |")
        else:
            print(f"{x['deal_id']:24s} ask {x['price'] / 1e6:6.1f}M gross {pct(x['gross_ask'])} entry {pct(x['entry_yield'])} exit {pct(x['exit_yield'])} "
                  f"YoC {pct(x['yield_on_cost'])} uIRR {pct(x['unlev_irr'])} uEM {x['unlev_em'] or 0:.2f} lIRR {pct(x['lev_irr'])} DSCR {dscr} "
                  f"walk {walk} | {x['verdict']} | {why}")
            if x["engine_error"]:
                print("     engine:", x["engine_error"])


if __name__ == "__main__":
    main()
