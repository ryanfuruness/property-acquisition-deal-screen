#!/usr/bin/env python3
"""Run the engine and mandate fit on each deal's truth (engine_inputs + deal_facts) and print a summary.

    python tools/check_engine.py [deal_id ...]

Used to calibrate asking prices; results are not written into truth.json (expected_verdict stays null).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from engine import load_mandate, load_market, mandate_fit, underwrite  # noqa: E402


def main(ids):
    mandate, market = load_mandate(), load_market()
    for p in sorted((REPO / "data" / "deals").glob("*/truth.json")):
        t = json.loads(p.read_text())
        if ids and t["deal_id"] not in ids:
            continue
        ei, facts = t["true_building"]["engine_inputs"], t["true_building"]["deal_facts"]
        r = underwrite(ei, mandate, market)
        fit = mandate_fit(facts, r, mandate)
        m = {k: v["value"] for k, v in r["metrics"].items()}
        soft = [x["name"] for x in fit["tests"] if x["kind"] == "soft" and x["status"] != "pass"]
        hard = [x["name"] for x in fit["tests"] if x["kind"] == "hard" and x["status"] != "pass"]
        g = m["gross_yield_in_place_on_price"]
        print(f"{t['deal_id']:24s} gross {g*100:5.2f}% NIYc {m['going_in_net_yield_on_cost']*100:5.2f}% DSCR {m['dscr_year1']:.2f} "
              f"LIRR {(m['levered_irr_pre_tax'] or float('nan'))*100:6.2f}% EM {m['levered_equity_multiple_pre_tax']:.2f} "
              f"walk {m['walk_away_price_aed']/1e6:6.1f}M ask {ei['price_aed']/1e6:6.1f}M | {fit['verdict']:10s} hard={hard} soft={soft}")
        for w in r.get("warnings", []):
            print("     warning:", w)


if __name__ == "__main__":
    main(sys.argv[1:])
