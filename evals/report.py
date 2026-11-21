"""Console report and evals/REPORT.md, both generated from a results dict.

Order: headline, history of labelled runs, per-deal table, then every miss (deal, item,
expected, got, note), grouped by metric. The misses are the useful part.
"""

from __future__ import annotations

import json
from collections import defaultdict

from .common import SETS, norm_verdict, rel_path

SECTIONS = [("om", "OM field extraction"), ("rent_roll", "Rent roll"), ("opex", "Operating statement"),
            ("discrepancies", "Discrepancies"), ("underwriting", "Underwriting inputs (engine on extracted vs true inputs)"),
            ("verdict", "Verdict"), ("memo", "Memo grounding")]

PCT_KEYS = {"om_field_accuracy", "om_trusted_accuracy", "om_citation_valid", "om_citation_page_match",
            "rent_roll_unit_recall", "rent_roll_unit_precision", "rent_roll_unit_field_accuracy",
            "rent_roll_totals_accuracy", "rent_roll_in_place_rent_ok", "rent_roll_occupancy_ok",
            "opex_category_accuracy", "opex_period_ok", "discrepancy_recall", "discrepancy_precision",
            "underwriting_within_tolerance", "noi_mean_abs_rel_error", "walk_away_mean_abs_rel_error",
            "verdict_agreement", "memo_grounding", "memo_pass_rate"}
PP_KEYS = {"yield_on_cost_mean_abs_error", "levered_irr_mean_abs_error"}


def fmt(v, maxlen: int = 90) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.4g}"
    if isinstance(v, int):
        return f"{v:,}" if abs(v) >= 10000 else str(v)
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def fmt_head(key: str, h: dict) -> str:
    v = h["value"]
    if v is None:
        s = "n/a"
    elif key in PCT_KEYS:
        s = f"{v * 100:.1f}%"
    elif key in PP_KEYS:
        s = f"{v * 100:.2f} pts"
    elif key.startswith("cost"):
        s = f"${v:.3f}"
    else:
        s = fmt(v)
    if h.get("k") is not None and h.get("n") is not None:
        s += f" ({h['k']}/{h['n']})"
    elif h.get("n") is not None and key not in ("deals_scored",):
        s += f" (n={h['n']})"
    return s


def _pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _signed_pct(x):
    return "n/a" if x is None else f"{x * 100:+.1f}%"


def _set_of(res: dict, d: str) -> str:
    return (res.get("deal_sets") or {}).get(d, "dev")


def _norm_miss(m: dict) -> dict:
    if m.get("section") == "verdict":
        m = {**m, "expected": norm_verdict(m.get("expected")), "got": norm_verdict(m.get("got"))}
    return m


def headline_rows(res: dict) -> tuple[list[str], list[list[str]]]:
    """Headline with dev and held-out side by side (results scored before sets existed: combined only)."""
    hb = res.get("headline_by_set")
    if not hb:
        return ["metric", "all deals"], [[h["label"], fmt_head(k, h)] for k, h in res["headline"].items()]
    cols = [s for s in SETS] + ["combined"]
    rows = [[h["label"]] + [fmt_head(k, hb[c][k]) if hb.get(c) and hb[c]["deals_scored"]["value"] else "n/a"
                            for c in cols] for k, h in res["headline"].items()]
    return ["metric", "dev", "held-out", "combined"], rows


def per_deal_rows(res: dict) -> list[list[str]]:
    rows = []
    order = sorted(res["deals"], key=lambda d: (SETS.index(_set_of(res, d)) if _set_of(res, d) in SETS else 9, d))
    for d in order:
        s = res["deals"][d]
        om, rr, op = s["om"]["summary"], s["rent_roll"]["summary"], s["opex"]["summary"]
        di, uw, me, mt = (s["discrepancies"]["summary"], s["underwriting"]["summary"], s["memo"]["summary"],
                          s["meta"]["summary"])
        rows.append([
            d, _set_of(res, d),
            f"{om['correct']}/{om['n']}",
            f"{_pct(rr['recall'])}/{_pct(rr['precision'])}",
            f"{op.get('categories_correct', 0)}/{op.get('categories_n', 0)}" + ("" if op.get("period_ok") else " P!"),
            f"{len(di['tp'])}/{len(di['fn'])}/{len(di['fp'])}",
            _signed_pct(uw["errors"]["noi_year1"]["rel_error"]),
            _signed_pct(uw["errors"]["walk_away_price_aed"]["rel_error"]),
            f"{norm_verdict(uw['verdict_got'])} " + ("=" if uw["verdict_ok"] else f"≠ {norm_verdict(uw['verdict_expected'])}"),
            f"{me['status']} {_pct(me['share'])}",
            "n/a" if mt["cost_usd"] is None else f"${mt['cost_usd']:.2f}",
            "n/a" if mt["duration_s"] is None else f"{mt['duration_s']:.0f}s",
        ])
    return rows


DEAL_HEADER = ["deal", "set", "OM fields", "RR recall/prec", "opex cats", "disc TP/FN/FP", "NOI err", "walk-away err",
               "verdict", "memo", "cost", "time"]


def _misses_by_section(res: dict) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for c in res["misses"]:
        out[c["section"]].append(_norm_miss(c))
    return out


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def markdown_report(res: dict, summary: dict | None = None) -> str:
    L = [f"# Deal Screen eval report: `{res['label']}`", "",
         f"Generated by `python -m evals score` at {res['scored_at']} from `{rel_path(res['runs_dir'])}`; scorer "
         f"{res['scorer_version']}, pipeline version(s) {', '.join(res['pipeline_versions']) or 'n/a'}. "
         "Do not edit by hand: re-run the scorer. Metric definitions are in [README.md](README.md); "
         "failures and fixes are logged in [FAILURES.md](FAILURES.md).", ""]
    if res["deals_not_scored"]:
        L += ["**Not scored:** " + "; ".join(f"`{d}` ({why})" for d, why in res["deals_not_scored"].items()), ""]
    sets_line = ", ".join(f"{s}: {sum(1 for d in res['deals_scored'] if _set_of(res, d) == s)} scored"
                          for s in SETS)
    L += ["## Headline", "", f"Deals by set ({sets_line}). Held-out deals are generated with a fresh seed and layouts "
          "not seen during development; the pipeline is not tuned on them.", "",
          _md_table(*headline_rows(res)), ""]
    hist = (summary or {}).get("history") or []
    if hist:
        keys = ["om_field_accuracy", "rent_roll_unit_recall", "discrepancy_recall", "discrepancy_precision",
                "false_flags_on_clean_deals", "verdict_agreement", "memo_grounding", "cost_usd_per_deal"]
        rows = [[h["label"], h["scored_at"][:16], str(len(h.get("deals_scored", [])))] +
                [fmt_head(k, {"value": h["headline"].get(k)}) for k in keys] for h in hist]
        L += ["## History (labelled runs)", "", "All scored deals:", "",
              _md_table(["label", "scored", "deals"] + keys, rows), ""]
        rows = []
        for h in hist:
            for s in SETS:
                hs = (h.get("headline_by_set") or {}).get(s)
                if hs and hs.get("deals_scored"):
                    rows.append([h["label"], s, str(hs["deals_scored"])] + [fmt_head(k, {"value": hs.get(k)}) for k in keys])
        if rows:
            L += ["By set (labels scored since sets were introduced):", "",
                  _md_table(["label", "set", "deals"] + keys, rows), ""]
    stab = (summary or {}).get("stability")
    if stab:
        L += stability_markdown(stab)
    L += ["## Per deal", "",
          "OM fields = correct/scored. RR = rent-roll unit recall/precision. opex cats = categories within 0.5% "
          "(P! = period or annualisation wrong). Errors are run minus engine-on-truth, relative.", "",
          _md_table(DEAL_HEADER, per_deal_rows(res)), ""]

    L += ["## OM fields", "", _md_table(["field", "accuracy", "correct", "wrong", "missed", "spurious"], [
        [f, _pct(v["accuracy"]), f"{v['correct']}/{v['n']}", v["wrong"], v["missed"], v["spurious"]]
        for f, v in res["om_by_field"].items()]), ""]
    d = res["discrepancies"]
    L += ["## Discrepancies by catalogue id", "",
          _md_table(["id", "planted", "found", "missed", "false flags", "recall", "precision"], [
              [i, v["planted"], v["tp"], v["fn"], v["fp"], _pct(v["recall"]), _pct(v["precision"])]
              for i, v in d["by_id"].items() if v["planted"] or v["fp"]]), "",
          f"False flags on clean deals ({', '.join(d['clean_deals']) or 'none scored'}): "
          f"{d['false_flags_on_clean_deals']} — " + "; ".join(f"{k}: {v or 'none'}" for k, v in
                                                              d["false_flags_on_clean_deals_by_deal"].items()), ""]
    unscored = {dd: s["discrepancies"]["summary"]["unscored_findings"] for dd, s in res["deals"].items()
                if s["discrepancies"]["summary"]["unscored_findings"]}
    if unscored:
        L += ["Findings outside the catalogue (listed, not scored): " + "; ".join(
            f"{dd}: " + ", ".join(f"{u['id']} ({u['title']})" for u in us) for dd, us in unscored.items()), ""]

    gaps = res.get("verification_gaps") or []
    L += ["## Verification gaps", "",
          "Values that are right but that the run's verifier did not confirm (so they cannot feed the engine), and "
          "citations that are not valid. Not counted as misses of the value.", ""]
    L += [_md_table(["deal", "item", "gap", "run status", "detail"],
                    [[g["deal_id"], g["item"], g["kind"], g.get("run_status"),
                      f"cited page {g['cited_page']}, truth pages {g['truth_pages']}" if "cited_page" in g else ""]
                     for g in gaps]) if gaps else "None.", ""]
    L += ["## Misses", "", f"{len(res['misses'])} failed checks. Every one is listed.", ""]
    by = _misses_by_section(res)
    for sec, title in SECTIONS:
        ms = by.get(sec, [])
        L += [f"### {title} ({len(ms)})", ""]
        if not ms:
            L += ["None.", ""]
            continue
        unit = [m for m in ms if m.get("kind") == "unit_field"]
        other = [m for m in ms if m.get("kind") != "unit_field"]
        if other:
            L += [_md_table(["deal", "item", "expected", "got", "outcome", "note"],
                            [[m["deal_id"], m["item"], fmt(m["expected"]), fmt(m["got"]), m["outcome"],
                              fmt(m.get("note") or "", 200)] for m in other]), ""]
        if unit:
            L += [f"Unit-level field misses on matched units ({len(unit)}):", "", "<details><summary>show</summary>", "",
                  _md_table(["deal", "item", "expected", "got"],
                            [[m["deal_id"], m["item"], fmt(m["expected"]), fmt(m["got"])] for m in unit]),
                  "", "</details>", ""]
    return "\n".join(L) + "\n"


def text_report(res: dict, summary: dict | None = None, max_unit_misses: int = 10) -> str:
    def table(header, rows):
        w = [max(len(str(x)) for x in col) for col in zip(header, *rows)] if rows else [len(h) for h in header]
        line = lambda r: "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r))  # noqa: E731
        return "\n".join([line(header), line(["-" * x for x in w])] + [line(r) for r in rows])

    L = [f"Deal Screen evals — label {res['label']} — {res['scored_at']}",
         f"runs: {rel_path(res['runs_dir'])}   scored: {len(res['deals_scored'])}   pipeline: {', '.join(res['pipeline_versions'])}"]
    if res["deals_not_scored"]:
        L.append("not scored: " + ", ".join(f"{d} ({w})" for d, w in res["deals_not_scored"].items()))
    L += ["", "HEADLINE (dev and held-out side by side)", table(*headline_rows(res)),
          "", "PER DEAL", table(DEAL_HEADER, per_deal_rows(res))]
    gaps = res.get("verification_gaps") or []
    if gaps:
        L += ["", f"VERIFICATION GAPS ({len(gaps)}): right value not verified, or citation not valid"]
        L += [f"  {g['deal_id']:22s} {g['item']}: {g['kind']} (run status {g.get('run_status')})" for g in gaps]
    L += ["", f"MISSES ({len(res['misses'])})"]
    by = _misses_by_section(res)
    for sec, title in SECTIONS:
        ms = by.get(sec, [])
        if not ms:
            continue
        L.append(f"\n[{title}] {len(ms)}")
        unit_count: dict[str, int] = defaultdict(int)
        for m in ms:
            if m.get("kind") == "unit_field":
                unit_count[m["deal_id"]] += 1
                if unit_count[m["deal_id"]] > max_unit_misses:
                    continue
            note = f"  — {fmt(m.get('note'), 160)}" if m.get("note") else ""
            L.append(f"  {m['deal_id']:22s} {m['item']}: expected {fmt(m['expected'], 60)}, got {fmt(m['got'], 60)}"
                     f" [{m['outcome']}]{note}")
        for dd, k in unit_count.items():
            if k > max_unit_misses:
                L.append(f"  {dd:22s} … and {k - max_unit_misses} more unit-level misses (all in evals/REPORT.md)")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------- stability


def _fmt_ratio(h: dict | None, pct: bool = True) -> str:
    if not h or h.get("value") is None:
        return "n/a"
    s = f"{h['value'] * 100:.1f}%" if pct else f"{h['value']:.3f}"
    if h.get("k") is not None:
        s += f" ({h['k']}/{h['n']})"
    return s


STAB_ROWS = [("verdict_unanimous", "Deals whose runs all give the same verdict", True),
             ("verdict_correct_runs", "Runs whose verdict matches engine on truth", True),
             ("discrepancy_sets_identical", "Deals with identical discrepancy ids in every run", True),
             ("discrepancy_jaccard_mean", "Mean pairwise Jaccard of discrepancy ids", False),
             ("walk_away_spread_rel_mean", "Walk-away spread (max-min)/median, mean", True),
             ("walk_away_spread_rel_max", "Walk-away spread (max-min)/median, worst deal", True),
             ("memo_pass_rate", "Memos passed, all runs", True)]


def _stab_tables(stab: dict) -> tuple[list[str], list[list[str]], list[str], list[list[str]]]:
    by = stab.get("aggregate_by_set") or {}
    h1 = ["metric", "dev", "held-out", "combined"]
    r1 = [[label] + [_fmt_ratio((by.get(s) or {}).get(k), pct) if (by.get(s) or {}).get("deals") else "n/a"
                     for s in SETS] + [_fmt_ratio(stab["aggregate"].get(k), pct)] for k, label, pct in STAB_ROWS]
    h2 = ["deal", "set", "runs", "verdicts (truth)", "disc. Jaccard", "ids not in every run", "walk-away min-max (AED m)",
          "memo passed"]
    r2 = []
    for d, p in sorted((stab.get("per_deal") or {}).items(), key=lambda kv: (kv[1]["set"], kv[0])):
        sets = p["discrepancy_sets"]
        every = set.intersection(*map(set, sets)) if sets else set()
        some = sorted(set().union(*map(set, sets)) - every)
        wa = ("n/a" if p["walk_away_min"] is None else
              f"{p['walk_away_min'] / 1e6:.2f}-{p['walk_away_max'] / 1e6:.2f}"
              + (f" ({p['walk_away_spread_rel'] * 100:.1f}%)" if p.get("walk_away_spread_rel") is not None else ""))
        r2.append([d, p["set"], str(p["n_runs"]),
                   ", ".join(norm_verdict(v) or "none" for v in p["verdicts"]) + f" ({norm_verdict(p['expected_verdict'])})",
                   "n/a" if p["discrepancy_jaccard_mean"] is None else f"{p['discrepancy_jaccard_mean']:.2f}",
                   ", ".join(some) or "none", wa, " ".join("y" if m else "n" for m in p["memo_passed"])])
    return h1, r1, h2, r2


def stability_markdown(stab: dict) -> list[str]:
    h1, r1, h2, r2 = _stab_tables(stab)
    L = ["## Stability (repeated runs)", "",
         f"`python -m evals stability` at {stab['scored_at']}, label `{stab['label']}`, over "
         f"{', '.join(f'`{r}`' for r in stab['run_dirs'])}. Each deal with at least two runs is compared run "
         "against run; Jaccard is over catalogue discrepancy ids.", "",
         _md_table(h1, r1), "", _md_table(h2, r2), ""]
    if stab.get("deals_not_compared"):
        L += ["Not compared (fewer than two runs): " + ", ".join(f"{d} ({w})" for d, w in stab["deals_not_compared"].items()), ""]
    return L


def stability_text(stab: dict) -> str:
    def table(header, rows):
        w = [max(len(str(x)) for x in col) for col in zip(header, *rows)] if rows else [len(h) for h in header]
        line = lambda r: "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r))  # noqa: E731
        return "\n".join([line(header), line(["-" * x for x in w])] + [line(r) for r in rows])
    h1, r1, h2, r2 = _stab_tables(stab)
    L = [f"Deal Screen stability — label {stab['label']} — {stab['scored_at']}",
         f"run dirs: {', '.join(stab['run_dirs'])}", "", "AGGREGATE", table(h1, r1), "", "PER DEAL", table(h2, r2)]
    if stab.get("deals_not_compared"):
        L += ["", "not compared: " + ", ".join(f"{d} ({w})" for d, w in stab["deals_not_compared"].items())]
    return "\n".join(L) + "\n"
