"""The scorer on synthetic fixtures: a perfect run scores 100%; known errors score exactly as expected."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from evals import score_discrepancies  # noqa: E402
from evals.__main__ import main as cli  # noqa: E402
from evals.docs import value_in_unit_row  # noqa: E402
from evals.scorer import score_deal, score_runs, write_results  # noqa: E402
from evals.truth import engine_on_truth, list_truth_deals, load_truth  # noqa: E402
from fixtures import perfect_run  # noqa: E402

ALL_DEALS = list_truth_deals()


def misses(scored: dict, section: str | None = None) -> list[dict]:
    out = []
    for sec in ("om", "rent_roll", "opex", "discrepancies", "underwriting", "memo"):
        for c in scored[sec]["checks"] + scored[sec].get("unit_checks", []):
            if not c["ok"] and (section is None or c["section"] == section):
                out.append(c)
    return out


@pytest.fixture(scope="module")
def truths():
    return {d: load_truth(d) for d in ALL_DEALS}


@pytest.fixture(scope="module")
def perfect(truths):
    return {d: perfect_run(t) for d, t in truths.items()}


# ---------------------------------------------------------------------------- perfect runs


@pytest.mark.parametrize("deal_id", ALL_DEALS)
def test_perfect_run_has_no_misses(deal_id, truths, perfect):
    s = score_deal(deal_id, truths[deal_id], perfect[deal_id])
    assert misses(s) == []
    assert s["om"]["summary"]["correct"] == s["om"]["summary"]["n"]
    cit = s["om"]["summary"]["citations"]
    assert cit["valid"] == cit["page_match"] == cit["n"] > 0
    rr = s["rent_roll"]["summary"]
    assert rr["recall"] == rr["precision"] == 1.0 and rr["summary_rows_as_units"] == 0
    assert s["opex"]["summary"]["period_ok"]
    assert s["underwriting"]["summary"]["verdict_ok"]
    assert s["memo"]["summary"]["share"] == 1.0 and s["memo"]["summary"]["numbers"] == 3


def test_perfect_set_headline_is_100_percent(perfect, tmp_path):
    res = score_runs(runs=perfect, label="perfect")
    h = {k: v["value"] for k, v in res["headline"].items()}
    for k in ("om_field_accuracy", "om_trusted_accuracy", "om_citation_valid", "om_citation_page_match",
              "rent_roll_unit_recall", "rent_roll_unit_precision", "rent_roll_unit_field_accuracy",
              "rent_roll_totals_accuracy", "opex_category_accuracy", "opex_period_ok", "discrepancy_recall",
              "discrepancy_precision", "underwriting_within_tolerance", "verdict_agreement", "memo_grounding",
              "memo_pass_rate"):
        assert h[k] == 1.0, k
    assert h["false_flags_on_clean_deals"] == 0
    assert h["rent_roll_summary_rows_as_units"] == 0
    assert h["noi_mean_abs_rel_error"] == 0.0
    assert h["deals_scored"] == len(ALL_DEALS)
    assert h["cost_usd_per_deal"] == 0.5 and h["duration_s_per_deal"] == 100.0
    assert res["misses"] == []
    assert res["discrepancies"]["clean_deals"] == ["d01-cedarline-dso", "d02-lantana-ic"]


# ---------------------------------------------------------------------------- OM fields


def test_om_known_errors(truths, perfect):
    d = "d06-opaline-jvc"
    run = copy.deepcopy(perfect[d])
    om = run["extracted"]["om"]
    om["asking_price_aed"]["value"] = 30_500_000 * 1.004        # inside 0.5%: still correct
    om["nsa_sqft"]["value"] = 32124 * 1.006                      # outside 0.5%: wrong
    om["occupancy_stated"] = {"value": None, "status": "not_stated", "source": None}            # missed
    om["opex_stated_aed"] = {"value": 100000.0, "status": "verified",                             # truth: not stated
                             "source": {"doc": "om.pdf", "page": 3}}
    om["unit_count"]["source"]["page"] = 4                       # right value, page not in truth list, verified
    om["floors"]["source"]["page"] = 4
    om["floors"]["status"] = "unverified"                        # wrong page and quote not found
    om["plot_number"]["status"] = "unverified"                   # right value but unverified
    s = score_deal(d, truths[d], run)
    got = {c["item"]: c["outcome"] for c in misses(s, "om")}
    assert got == {"nsa_sqft": "wrong", "occupancy_stated": "missed", "opex_stated_aed": "spurious"}
    summ = s["om"]["summary"]
    assert summ["correct"] == summ["n"] - 3
    # trusted also loses plot_number (correct but unverified) and floors (correct value, unverified)
    assert summ["trusted_correct"] == summ["n"] - 5
    cits = {c["item"]: c for c in s["om"]["citations"]}
    assert cits["unit_count"]["page_match"] is False and cits["unit_count"]["valid"] is True
    assert cits["floors"]["valid"] is False
    assert cits["plot_number"]["page_match"] is True and cits["plot_number"]["valid"] is False
    assert "occupancy_stated" not in cits and "opex_stated_aed" not in cits  # no citation for null/spurious


def test_om_basis_rules(truths, perfect):
    # d06: rent figure printed with no basis label -> 'unstated' accepted; yield labelled 'ROI' -> measure 'unstated' accepted.
    d = "d06-opaline-jvc"
    run = copy.deepcopy(perfect[d])
    run["extracted"]["om"]["annual_rent_stated"]["basis"] = "unstated"
    run["extracted"]["om"]["yield_stated"]["basis"] = {"measure": "unstated", "on": "asking_price"}
    assert misses(score_deal(d, truths[d], run), "om") == []
    run["extracted"]["om"]["yield_stated"]["basis"] = {"measure": "net", "on": "asking_price"}
    run["extracted"]["om"]["annual_rent_stated"]["basis"] = "potential"
    assert {c["item"] for c in misses(score_deal(d, truths[d], run), "om")} == {"yield_stated.basis",
                                                                                "annual_rent_stated.basis"}
    # d01: the OM labels its rent '(in-place)' -> 'unstated' is wrong.
    d = "d01-cedarline-dso"
    run = copy.deepcopy(perfect[d])
    run["extracted"]["om"]["annual_rent_stated"]["basis"] = "unstated"
    assert [c["item"] for c in misses(score_deal(d, truths[d], run), "om")] == ["annual_rent_stated.basis"]


def test_title_parts_and_aliases(truths, perfect):
    d = "d10-almehrab-barsha"     # OM does not state tenure; states one title deed
    run = copy.deepcopy(perfect[d])
    assert run["extracted"]["om"]["title_type"]["value"] == {"tenure": "unstated", "ownership": "single_title"}
    run["extracted"]["om"]["title_type"] = {"value": None, "status": "not_stated", "source": None}
    m = misses(score_deal(d, truths[d], run), "om")
    assert [(c["item"], c["outcome"]) for c in m] == [("title_type.ownership", "missed")]
    run["extracted"]["om"]["title_type"] = {"value": {"tenure": "freehold", "ownership": "single_title"},
                                            "status": "verified", "source": {"doc": "om.pdf", "page": 3}}
    m = misses(score_deal(d, truths[d], run), "om")
    assert [(c["item"], c["outcome"]) for c in m] == [("title_type.tenure", "spurious")]


def test_upside_claims(truths, perfect):
    d = "d05-larkspur-barsha"
    run = copy.deepcopy(perfect[d])
    assert run["extracted"]["om"]["upside_claims"]
    run["extracted"]["om"]["upside_claims"].append({"quote": "Prime location next to the metro", "status": "verified",
                                                    "source": {"doc": "om.pdf", "page": 2}})
    assert [c["item"] for c in misses(score_deal(d, truths[d], run), "om")] == ["upside_claims"]
    d = "d06-opaline-jvc"         # no claims in the OM
    run = copy.deepcopy(perfect[d])
    run["extracted"]["om"]["upside_claims"] = [{"quote": "x", "status": "verified", "source": {}}]
    assert [(c["item"], c["outcome"]) for c in misses(score_deal(d, truths[d], run), "om")] == [("upside_claims", "spurious")]


# ---------------------------------------------------------------------------- rent roll


def test_rent_roll_known_errors(truths, perfect):
    d = "d06-opaline-jvc"     # 48 units, total row 53
    run = copy.deepcopy(perfect[d])
    units = run["rent_roll_summary"]["units"]
    dropped = [units.pop(0)["unit"], units.pop(0)["unit"]]
    units.append({"unit": "Total", "unit_type": None, "area_sqft": 32124.0, "status": "occupied",
                  "annual_rent_aed": 2958000.0, "source": {"sheet": "Rent Roll", "row": 53}})
    units.append({"unit": "999", "unit_type": "studio", "area_sqft": 400.0, "status": "vacant",
                  "source": {"sheet": "Rent Roll", "row": 60}})
    target = next(u for u in units if u["status"] == "occupied" and u["annual_rent_aed"])
    target["annual_rent_aed"] *= 1.10
    run["rent_roll_summary"]["summary"]["in_place_rent_aed"] *= 1.01
    s = score_deal(d, truths[d], run)
    rr = s["rent_roll"]["summary"]
    assert (rr["matched"], rr["truth_units"], rr["run_units"]) == (46, 48, 48)
    assert rr["recall"] == round(46 / 48, 4) and rr["precision"] == round(46 / 48, 4)
    assert rr["summary_rows_as_units"] == 1 and rr["extra_units"] == 1
    assert rr["unit_fields"]["annual_rent_aed"]["correct"] == rr["unit_fields"]["annual_rent_aed"]["n"] - 1
    kinds = sorted((c.get("kind"), c["item"]) for c in misses(s, "rent_roll"))
    assert kinds == sorted([("unit_recall", f"unit {dropped[0]}"), ("unit_recall", f"unit {dropped[1]}"),
                            ("summary_row_as_unit", "row 53 ('Total')"), ("unit_precision", "unit '999'"),
                            ("unit_field", f"unit {target['unit']}.annual_rent_aed"), ("total", "in_place_rent_aed")])


def test_status_classes_and_asking_visibility(truths, perfect):
    d = "d08-jade-ic"
    run = copy.deepcopy(perfect[d])
    units = {u["unit"]: u for u in run["rent_roll_summary"]["units"]}
    units["114"]["status"] = "occupied"     # truth under_renewal: same to the engine, not a miss
    units["122"]["status"] = "occupied"     # truth notice_served: a miss
    m = misses(score_deal(d, truths[d], run), "rent_roll")
    assert [c["item"] for c in m] == ["unit 122.status"]
    # the asking-rent reader: d01 prints asking rents in Remarks; d06 prints none
    t1, t6 = truths["d01-cedarline-dso"], truths["d06-opaline-jvc"]
    p1 = Path(t1["_package_dir"]) / t1["rent_roll"]["document"]
    p6 = Path(t6["_package_dir"]) / t6["rent_roll"]["document"]
    assert value_in_unit_row(p1, "207", 76500)
    assert not value_in_unit_row(p6, "106", 108000)
    s = score_deal("d06-opaline-jvc", t6, perfect["d06-opaline-jvc"])
    exp = next(c for c in s["rent_roll"]["checks"] if c["item"] == "vacant_asking_rent_aed")
    assert exp["expected"] == 0 and "does not print" in exp["note"]


def test_master_lease_checks(truths, perfect):
    d = "d11-silverline-dso"
    run = copy.deepcopy(perfect[d])
    run["underwriting"]["deal_inputs"]["master_lease"]["annual_rent_aed"] = 5_102_500
    m = misses(score_deal(d, truths[d], run), "rent_roll")
    assert [c["item"] for c in m] == ["master_lease.annual_rent_aed"]
    del run["underwriting"]["deal_inputs"]["master_lease"]
    m = misses(score_deal(d, truths[d], run), "rent_roll")
    assert [(c["item"], c["outcome"]) for c in m] == [("master_lease", "missed")]


# ---------------------------------------------------------------------------- operating statement


def test_opex_known_errors(truths, perfect):
    d = "d05-larkspur-barsha"     # Jan-Sep annualised
    run = copy.deepcopy(perfect[d])
    run["opex"]["period"]["months_used"] = 12
    run["opex"]["period"]["annualised"] = False
    del run["opex"]["totals_by_category"]["insurance"]
    run["opex"]["totals_by_category"]["vacancy_loss"] = 5000.0
    s = score_deal(d, truths[d], run)
    got = sorted((c["item"], c["outcome"]) for c in misses(s, "opex"))
    assert got == [("insurance", "missed"), ("period.annualised", "wrong"), ("period.months_covered", "wrong"),
                   ("vacancy_loss", "spurious")]
    assert s["opex"]["summary"]["period_ok"] is False


# ---------------------------------------------------------------------------- discrepancies


def test_discrepancies_known_errors(truths, perfect):
    d = "d06-opaline-jvc"
    run = copy.deepcopy(perfect[d])
    run["discrepancies"] = [x for x in run["discrepancies"] if x["id"] != "collections_gap"]
    run["discrepancies"].append({"id": "occupancy_mismatch", "title": "x", "detected_by": "rule"})
    run["discrepancies"].append({"id": "other_om_claim", "title": "free-form", "detected_by": "model"})
    s = score_deal(d, truths[d], run)["discrepancies"]["summary"]
    assert (len(s["tp"]), s["fn"], s["fp"]) == (3, ["collections_gap"], ["occupancy_mismatch"])
    assert s["recall"] == 0.75 and s["precision"] == 0.75
    assert [u["id"] for u in s["unscored_findings"]] == ["other_om_claim"]


def test_false_flags_on_clean_deals(perfect):
    runs = copy.deepcopy(perfect)
    runs["d01-cedarline-dso"]["discrepancies"] = [{"id": "title_check", "title": "x"},
                                                  {"id": "upside_exceeds_rera_cap", "title": "y"}]
    runs["d03-sorrel-jvc"]["discrepancies"].append({"id": "title_check", "title": "z"})
    res = score_runs(runs=runs, label="t")
    d = res["discrepancies"]
    assert d["false_flags_on_clean_deals"] == 2 and d["false_flags_on_planted_deals"] == 1
    assert d["by_id"]["title_check"]["fp"] == 2
    planted = sum(len(t["planted_discrepancies"]) for t in (load_truth(x) for x in ALL_DEALS))
    assert d["recall"] == 1.0 and d["precision"] == round(planted / (planted + 3), 4)


def test_catalogue_and_aliases():
    assert len(score_discrepancies.catalogue()) == 16
    assert score_discrepancies.ALIASES == {}


# ---------------------------------------------------------------------------- underwriting, verdict, memo


def test_underwriting_tolerances_and_verdict(truths, perfect):
    d = "d02-lantana-ic"
    run = copy.deepcopy(perfect[d])
    m = run["underwriting"]["outputs"]["metrics"]
    m["noi_year1"]["value"] *= 1.01                       # within 2%
    m["walk_away_price_aed"]["value"] *= 0.97             # outside 2%
    m["levered_irr_pre_tax"]["value"] += 0.006            # outside 0.5 pts
    m["going_in_net_yield_on_cost"]["value"] += 0.0009    # within 0.1 pts
    run["mandate_fit"]["verdict"] = "Needs work"
    s = score_deal(d, truths[d], run)
    got = sorted(c["item"] for c in misses(s) if c["section"] in ("underwriting", "verdict"))
    assert got == ["levered_irr_pre_tax", "verdict", "walk_away_price_aed"]
    err = s["underwriting"]["summary"]["errors"]
    assert err["noi_year1"]["rel_error"] == pytest.approx(0.01)
    assert err["walk_away_price_aed"]["rel_error"] == pytest.approx(-0.03)
    assert err["levered_irr_pre_tax"]["abs_error"] == pytest.approx(0.006)


def test_not_underwritten(truths, perfect):
    d = "d12-tulip-ic"
    run = copy.deepcopy(perfect[d])
    run["underwriting"] = {"status": "not_underwritten", "error": "MarketDataError: area", "outputs": None}
    s = score_deal(d, truths[d], run)
    assert sorted(c["item"] for c in misses(s, "underwriting")) == sorted(
        ["going_in_net_yield_on_cost", "levered_irr_pre_tax", "noi_year1", "walk_away_price_aed"])


def test_expected_verdicts_are_computed_not_read():
    t = load_truth("d02-lantana-ic")
    assert t["expected_verdict"] is None
    assert engine_on_truth(t)["verdict"] == "Pursue"
    assert engine_on_truth(load_truth("d09-aurelia-bb"))["hard_fails"] == ["min_dscr_year1", "title"]


def test_memo_grounding(truths, perfect):
    d = "d04-kestrel-bb"
    run = copy.deepcopy(perfect[d])
    run["memo"] = {"status": "failed", "markdown": None, "attempts": [{"attempt": 2, "errors": ["x"]}],
                   "rejected_draft": perfect[d]["memo"]["markdown"] + " Rent is 12% [[rr.occupancy_by_units]] lower, "
                                                                      "over 30 days."}
    s = score_deal(d, truths[d], run)["memo"]["summary"]
    assert (s["numbers"], s["grounded"], s["status"], s["scored_text"]) == (5, 3, "failed", "rejected_draft")
    assert s["share"] == 0.6


# ---------------------------------------------------------------------------- writing and CLI


def test_write_results_history(perfect, tmp_path):
    evals_dir, results = tmp_path / "evals", tmp_path / "evals" / "results"
    evals_dir.mkdir()
    sub = {k: perfect[k] for k in ("d01-cedarline-dso", "d06-opaline-jvc")}
    for label in ("iter-1", "iter-2", "iter-1"):
        write_results(score_runs(runs=sub, label=label), results, evals_dir)
    summ = json.loads((evals_dir / "summary.json").read_text())
    assert [h["label"] for h in summ["history"]] == ["iter-2", "iter-1"]
    assert summ["latest"]["label"] == "iter-1" and summ["latest"]["headline"]["om_field_accuracy"] == 1.0
    assert set(summ["latest"]["per_deal"]) == set(sub)
    assert len(list(results.glob("*.json"))) >= 1
    report = (evals_dir / "REPORT.md").read_text()
    assert "## Headline" in report and "## Misses" in report and "d06-opaline-jvc" in report


def test_cli_scores_a_runs_directory(perfect, tmp_path, capsys):
    runs = tmp_path / "runs"
    for d in ("d06-opaline-jvc", "d11-silverline-dso"):
        (runs / d).mkdir(parents=True)
        run = copy.deepcopy(perfect[d])
        if d == "d06-opaline-jvc":
            run["extracted"]["om"]["unit_count"]["value"] = 47
        (runs / d / "run.json").write_text(json.dumps(run, default=str))
    (runs / "d01-cedarline-dso").mkdir()
    (runs / "d01-cedarline-dso" / "run.json").write_text("{ truncated")
    assert cli(["score", "--runs", str(runs), "--no-write"]) == 0
    out = capsys.readouterr().out
    assert "d06-opaline-jvc        unit_count: expected 48, got 47 [wrong]" in out
    assert "d01-cedarline-dso (unreadable run.json" in out
    assert "Deals scored" in out
