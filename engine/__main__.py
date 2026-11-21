"""Command line: ``python -m engine path/to/deal_inputs.json``.

Prints a readable underwriting summary. ``--json`` prints the full result instead.
If the JSON file has a ``deal_facts`` key next to the inputs (``{"deal_inputs": ...,
"deal_facts": ...}``), the mandate fit is printed too; a plain deal_inputs file gets a
mandate fit from the facts the inputs contain (area, price, unit count).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import load_mandate, load_market, mandate_fit, underwrite
from .loaders import DEFAULT_MANDATE_PATH, DEFAULT_MARKET_PATH


def _v(result: dict, name: str) -> Any:
    return result["metrics"][name]["value"]


def _fmt(value: Any, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit.startswith("ratio"):
        return f"{value:.2%}"
    if unit == "x":
        return f"{value:.2f}x"
    if unit.startswith("AED/sqft"):
        return f"AED {value:,.0f}/sqft"
    if unit.startswith("AED"):
        return f"AED {value:,.0f}"
    return f"{value:,.0f}" if isinstance(value, (int, float)) else str(value)


def summary(result: dict, fit: dict | None = None) -> str:
    """Render a plain-text summary of an underwriting result."""
    M = result["metrics"]
    lines = [f"Deal screen underwriting  {result.get('deal_id') or ''}".rstrip(),
             f"engine {result['engine_version']}, analysis start {result['analysis_start']}, "
             f"hold {result['hold_years']} years", ""]

    def row(label: str, name: str) -> None:
        m = M[name]
        lines.append(f"  {label:<38}{_fmt(m['value'], m['unit']):>22}")

    sections = [
        ("Decision (unlevered, pre-tax)", [
            ("Unlevered IRR", "unlevered_irr_pre_tax"),
            ("Unlevered equity multiple", "unlevered_equity_multiple_pre_tax"),
            ("Entry yield (Year-1 NOI / price)", "entry_yield_on_price"),
            ("Exit yield", "exit_yield"),
            ("Net yield on total cost", "going_in_net_yield_on_cost"),
            ("Walk-away price", "walk_away_price_aed")]),
        ("Rent roll", [("Units", "unit_count"), ("Occupancy (units)", "occupancy_by_units"),
                       ("In-place rent", "in_place_rent_aed"),
                       ("Screen reference rent (all units)", "screen_reference_rent_aed"),
                       ("Over-rented share of income", "over_rent_share_of_income"),
                       ("Over-rent cut at renewal/expiry", "over_rent_excess_at_expiry_aed"),
                       ("Max 3-month expiry share", "max_expiry_share_quarter")]),
        ("Year 1", [("Gross rental income", "gross_rental_income_year1"),
                    ("Effective gross income", "effective_gross_income_year1"),
                    ("Operating costs", "operating_costs_year1"), ("NOI", "noi_year1")]),
        ("Pricing", [("Price", "price_aed"), ("Price per sq ft NSA", "price_per_sqft_nsa"),
                     ("Price per sq ft BUA", "price_per_sqft_bua"),
                     ("Acquisition costs", "acquisition_costs_aed"),
                     ("Gross yield (in-place rent / price)", "gross_yield_in_place_on_price"),
                     ("Security deposits (closing credit)", "security_deposits_aed")]),
        ("Debt (sized to cover)", [("Loan", "loan_aed"), ("LTV", "ltv"), ("Interest rate", "interest_rate"),
                  ("Annual debt service", "annual_debt_service_aed"), ("DSCR Year 1", "dscr_year1"),
                  ("Debt yield Year 1", "debt_yield_year1"),
                  ("Breakeven occupancy (DSCR 1.0)", "breakeven_occupancy_dscr_1")]),
        ("Secondary returns", [("Levered IRR pre-tax", "levered_irr_pre_tax"),
                               ("Levered equity multiple pre-tax", "levered_equity_multiple_pre_tax"),
                               ("Unlevered IRR post-tax (indicative)", "unlevered_irr_post_tax"),
                               ("Levered IRR post-tax (indicative)", "levered_irr_post_tax")]),
    ]
    for title, rows in sections:
        lines.append(title)
        for label, name in rows:
            row(label, name)
        lines.append("")
    lines.append(f"  {result['exit']['summary']}")
    debt = result["debt"]
    lines.append(f"  Loan sized by {debt['sizing_constraint']}; {debt['rate_note'] or ''}".rstrip("; "))
    wa = result["walk_away"]
    if wa["price_aed"]["value"] is not None:
        lines.append(f"  Walk-away is {wa['discount_to_asking']['value']:.1%} below asking; most sensitive to "
                     f"{wa['most_sensitive_label']} (swing AED {wa['largest_swing_aed']['value']:,.0f}).")
    lines.append("")

    lines.append("Sensitivity: unlevered IRR pre-tax (rows: reference rent shift; columns: exit yield shift)")
    s = result["sensitivity"]
    lines.append("  " + " " * 10 + "".join(f"{b:+d} bps".rjust(12) for b in s["exit_yield_shifts_bps"]))
    for r in s["rent_shifts"]:
        cells = [c for c in s["cells"] if c["rent_shift"] == r]
        lines.append(f"  {r:+.0%}".ljust(12) + "".join(_fmt(c["unlevered_irr_pre_tax"], "ratio").rjust(12)
                                                     for c in cells))
    lines.append("")
    if result.get("om_yield_check"):
        lines += ["OM yield check", f"  {result['om_yield_check']['summary']}", ""]
    if fit:
        lines.append(f"Mandate fit: {fit['verdict']}  ({fit['reason']})")
        if fit.get("blocked_on"):
            lines.append(f"  Blocked on: {', '.join(fit['blocked_on'])}")
        if fit.get("stop_reason"):
            lines.append(f"  Stop: {fit['stop_reason']}")
        for t in fit["tests"]:
            lines.append(f"  [{t['status']:<7}] {t['kind']:<4} {t['name']:<42} {t['reason']}")
        lines.append("")
    if result["warnings"]:
        lines.append("Warnings")
        lines += [f"  - {w}" for w in result["warnings"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description=__doc__.splitlines()[0])
    parser.add_argument("deal_inputs", help="path to a deal_inputs JSON file")
    parser.add_argument("--mandate", default=str(DEFAULT_MANDATE_PATH))
    parser.add_argument("--market", default=str(DEFAULT_MARKET_PATH))
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)

    with open(args.deal_inputs, encoding="utf-8") as fh:
        data = json.load(fh)
    deal_inputs = data.get("deal_inputs", data)
    deal_facts = data.get("deal_facts") or {
        "area": deal_inputs.get("area"), "price_aed": deal_inputs.get("price_aed"),
    }
    mandate, market = load_mandate(args.mandate), load_market(args.market)
    result = underwrite(deal_inputs, mandate, market)
    fit = mandate_fit(deal_facts, result, mandate)
    if args.json:
        json.dump({"underwriting": result, "mandate_fit": fit}, sys.stdout, indent=2)
        print()
    else:
        print(summary(result, fit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
