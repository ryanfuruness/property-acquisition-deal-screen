"""Metric 3: operating statement. Category totals and the period / annualisation.

Compares ``run.opex`` with ``truth.opex``. Truth totals are the amounts the statement itself
states for the period it presents (for an annualised statement, its annualised column), mapped
to the chart of accounts; categories the statement omits are absent (zero). See evals/README.md.
"""

from __future__ import annotations

from .common import MISSED, SPURIOUS, check, get, is_num, num_close, ratio

SECTION = "opex"
EXPENSES = ("service_charge", "district_cooling", "utilities_common", "property_management",
            "maintenance_repairs", "insurance", "security_cleaning", "marketing_leasing", "admin_other",
            "sinking_fund")
INCOME = ("rental_income", "other_income")
LOSSES = ("vacancy_loss", "collection_loss")


def score(deal_id: str, truth: dict, run: dict) -> dict:
    op_t = truth["opex"]
    op_r = run.get("opex")
    checks: list[dict] = []
    if not op_r:
        checks.append(check(SECTION, deal_id, "operating statement parsed", True, False, False, MISSED,
                            "the run has no opex block"))
        return {"checks": checks, "summary": {"categories_n": 0, "categories_correct": 0, "period_ok": False}}

    exp_cat = dict(op_t.get("opex_by_category_aed") or {})
    exp_cat["rental_income"] = op_t.get("rental_income_aed") or 0
    exp_cat["other_income"] = op_t.get("other_income_aed") or 0
    got_cat = {k: v for k, v in (op_r.get("totals_by_category") or {}).items()
               if k in EXPENSES + INCOME + LOSSES}
    for cat in [c for c in INCOME + EXPENSES + LOSSES if c in exp_cat or c in got_cat]:
        e, g = exp_cat.get(cat) or 0, got_cat.get(cat)
        g0 = g or 0
        ok = num_close(float(e), float(g0)) if is_num(g0) else False
        outcome = None
        if not ok and e and not g:
            outcome = MISSED
        elif not ok and not e and g:
            outcome = SPURIOUS
        checks.append(check(SECTION, deal_id, cat, e, g, ok, outcome, kind="category"))

    e_tot = op_t.get("total_opex_aed")
    g_tot = op_r.get("total_expenses_aed")
    if e_tot is not None:
        checks.append(check(SECTION, deal_id, "total_opex_aed", e_tot, g_tot,
                            is_num(g_tot) and num_close(e_tot, g_tot), kind="total"))

    pt, pr = op_t.get("period") or {}, op_r.get("period") or {}
    e_m, g_m = pt.get("months_covered"), pr.get("months_used", pr.get("months_covered"))
    checks.append(check(SECTION, deal_id, "period.months_covered", e_m, g_m, e_m == g_m, kind="period"))
    e_a = bool(pt.get("annualised"))
    g_a = pr.get("annualised")
    if g_a is None:
        g_a = op_r.get("amount_basis") == "annualised_total"
    checks.append(check(SECTION, deal_id, "period.annualised", e_a, g_a, bool(g_a) == e_a, kind="period",
                        note=None if bool(g_a) == e_a else f"run amount_basis={op_r.get('amount_basis')}"))
    period_ok = all(c["ok"] for c in checks if c.get("kind") == "period")
    for item in ("start", "end"):
        checks.append(check(SECTION, deal_id, f"period.{item}", pt.get(item), pr.get(item),
                            str(pt.get(item)) == str(pr.get(item)), kind="period_dates"))

    cats = [c for c in checks if c.get("kind") == "category"]
    return {"checks": checks, "summary": {
        "categories_n": len(cats), "categories_correct": sum(c["ok"] for c in cats),
        "category_accuracy": ratio(sum(c["ok"] for c in cats), len(cats)),
        "total_opex_ok": next((c["ok"] for c in checks if c["item"] == "total_opex_aed"), None),
        "period_ok": period_ok,
        "unverified_lines": get(op_r, "unverified_lines", default=[]),
    }}
