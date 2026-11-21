"""Metrics 5 and 6: underwriting inputs (engine on extracted vs true inputs), and verdict.

This does not test the engine: the same engine runs on both sides. The engine's own correctness is
tested separately (tests/engine and the spreadsheet tie-out in evals/tieout/).

The expected numbers come from :func:`evals.truth.engine_on_truth` (engine.underwrite and
engine.mandate_fit on ``true_building.engine_inputs`` and ``deal_facts``). The gap measures
how far the screen, working from the broker's documents, lands from the true building; it
includes legitimate document-vs-truth differences (a statement that omits a cost the owner
really pays), which is the point: the screen should find them.
"""

from __future__ import annotations

from .common import MISSED, UW_TOL, check, get, is_num, norm_verdict, rel_err
from .truth import UW_METRICS

SECTION_UW, SECTION_VERDICT = "underwriting", "verdict"


def within(metric: str, expected, got) -> bool:
    if expected is None and got is None:
        return True
    if not (is_num(expected) and is_num(got)):
        return False
    kind, tol = UW_TOL[metric]
    if kind == "abs":
        return abs(got - expected) <= tol
    return abs(got - expected) <= tol * abs(expected)


def score(deal_id: str, truth: dict, run: dict, expected: dict) -> dict:
    uw_status = get(run, "underwriting", "status")
    metrics = get(run, "underwriting", "outputs", "metrics", default={}) or {}
    checks, errors = [], {}
    # No engine result on truth (area outside the screen's reference data): nothing to compare the run's
    # underwriting with, so no underwriting checks; the verdict is still scored.
    applicable = bool(expected.get("metrics"))
    for m in (UW_METRICS if applicable else ()):
        e = expected["metrics"].get(m)
        g = get(metrics, m, "value")
        ok = within(m, e, g)
        ae = (g - e) if is_num(e) and is_num(g) else None
        re_ = rel_err(e, g)
        errors[m] = {"expected": e, "got": g, "abs_error": ae, "rel_error": re_, "within_tolerance": ok}
        kind, tol = UW_TOL[m]
        checks.append(check(SECTION_UW, deal_id, m, e, g, ok, None if g is not None else MISSED,
                            ("not underwritten: " + str(get(run, "underwriting", "error"))) if g is None and uw_status != "ok"
                            else f"abs error {ae:,.4g}, rel error {re_:+.2%} (tolerance {kind} {tol:g})"
                            if ae is not None and re_ is not None else None,
                            abs_error=ae, rel_error=re_))
    v_exp, v_got = norm_verdict(expected["verdict"]), norm_verdict(get(run, "mandate_fit", "verdict"))
    run_tests = {t["name"]: t for t in get(run, "mandate_fit", "tests", default=[]) or []}
    hard_got = sorted(n for n, t in run_tests.items() if t.get("kind") == "hard" and t.get("status") == "fail")
    diffs = []
    for name, et in expected.get("tests", {}).items():
        rt = run_tests.get(name)
        if rt is None or rt.get("status") != et["status"]:
            diffs.append(f"{name} ({et['kind']}): truth {et['status']}, run {rt.get('status') if rt else 'missing'}")
    vcheck = check(SECTION_VERDICT, deal_id, "verdict", v_exp, v_got, v_exp == v_got, None,
                   ("tests that differ: " + "; ".join(diffs)) if diffs else "every mandate test has the same status",
                   expected_hard_fails=expected["hard_fails"], run_hard_fails=hard_got, test_differences=diffs)
    return {"checks": checks + [vcheck], "summary": {
        "status": uw_status, "errors": errors, "applicable": applicable,
        "within_tolerance": sum(c["ok"] for c in checks), "n": len(checks),
        "verdict_expected": v_exp, "verdict_got": v_got, "verdict_ok": v_exp == v_got,
        "hard_fails_expected": expected["hard_fails"], "hard_fails_got": hard_got,
        "mandate_test_differences": diffs,
    }}
