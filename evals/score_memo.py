"""Metrics 7 and 8: memo grounding, and cost and time per deal.

Memo grounding re-runs the pipeline's own memo checker (``pipeline.memo.tokens`` and
``_compare``, the code that decides whether a memo ships) on the run's markdown and fact sheet,
counting numbers rather than errors. For a failed memo the rejected draft is scored, so a failed
run shows how far from grounded its last draft was. If the checker cannot be imported the
scorer falls back to the run's recorded check result and says so.
"""

from __future__ import annotations

from .common import check, get, ratio

SECTION_MEMO, SECTION_META = "memo", "meta"


def grounding(markdown: str, facts: dict) -> dict:
    """Numbers in the memo and how many trace to the fact sheet (pipeline rules)."""
    from pipeline import memo as pm  # read-only use of the pipeline's checker
    toks, anchors = pm.tokens(markdown)
    starts = [t.start for t in toks]
    ungrounded = []
    for i, t in enumerate(toks):
        nxt = starts[i + 1] if i + 1 < len(toks) else len(markdown) + 1
        anchor = next((a for a in anchors if t.end <= a[0] < nxt and a[0] - t.end <= pm.MAX_ANCHOR_GAP), None)
        if anchor is None:
            ungrounded.append({"number": t.raw, "why": "no anchor"})
            continue
        fact = facts.get(anchor[2])
        if fact is None:
            ungrounded.append({"number": t.raw, "why": f"anchor [[{anchor[2]}]] is not a fact"})
            continue
        why = pm._compare(t, fact)
        if why:
            ungrounded.append({"number": t.raw, "why": why})
    bad_anchors = [a[2] for a in anchors if a[2] not in facts]
    n = len(toks)
    return {"numbers": n, "grounded": n - len(ungrounded), "share": ratio(n - len(ungrounded), n) if n else 1.0,
            "ungrounded": ungrounded, "unknown_anchors": bad_anchors, "method": "pipeline.memo checker"}


def score(deal_id: str, run: dict) -> dict:
    memo = run.get("memo") or {}
    status = memo.get("status")
    md = memo.get("markdown") or memo.get("rejected_draft") or ""
    facts = run.get("fact_sheet") or {}
    try:
        g = grounding(md, facts) if md else {"numbers": 0, "grounded": 0, "share": None, "ungrounded": [],
                                             "unknown_anchors": [], "method": "no memo text"}
    except Exception as exc:  # noqa: BLE001 - the pipeline checker moved; fall back and say so
        last = (memo.get("attempts") or [{}])[-1]
        g = {"numbers": None, "grounded": None, "share": 1.0 if status == "passed" and not last.get("errors") else None,
             "ungrounded": last.get("errors", []), "unknown_anchors": [],
             "method": f"run's recorded check (pipeline checker unavailable: {exc.__class__.__name__})"}
    recorded = len(((memo.get("attempts") or [{}])[-1]).get("errors") or [])
    recheck = len(g["ungrounded"]) + len(g["unknown_anchors"]) if g["numbers"] is not None else None
    status_note = None
    if recheck is not None and status == "failed" and recheck == 0:
        status_note = (f"the run recorded {recorded} checker error(s) on its last draft, but the pipeline checker as it "
                       f"is now finds none in that draft (the checker changed after the run)")
    elif recheck is not None and status == "failed":
        status_note = f"run recorded {recorded} checker error(s); the current checker finds {recheck}"
    checks = [check(SECTION_MEMO, deal_id, "memo status", "passed", status, status == "passed", None, status_note)]
    for u in g["ungrounded"]:
        checks.append(check(SECTION_MEMO, deal_id, "memo number",
                            "traces to a fact", u["number"] if isinstance(u, dict) else u, False, "ungrounded",
                            u.get("why") if isinstance(u, dict) else None))
    for a in g["unknown_anchors"]:
        checks.append(check(SECTION_MEMO, deal_id, "memo anchor", "a fact-sheet key", f"[[{a}]]", False, "ungrounded",
                            "anchor names no fact"))
    consistent = (recheck is None) or ((status == "passed") == (recheck == 0))
    return {"checks": checks, "summary": {
        "status": status, "attempts": len(memo.get("attempts") or []),
        "scored_text": "markdown" if memo.get("markdown") else ("rejected_draft" if md else None),
        **{k: g[k] for k in ("numbers", "grounded", "share", "method")},
        "unknown_anchors": g["unknown_anchors"],
        "recorded_errors_last_attempt": recorded,
        "agrees_with_run_status": consistent,
    }}


def score_meta(deal_id: str, run: dict) -> dict:
    meta = run.get("meta") or {}
    tok = meta.get("tokens") or {}
    return {"summary": {
        "cost_usd": meta.get("cost_usd"), "duration_s": meta.get("duration_s"),
        "model": meta.get("model"), "mapping_model": meta.get("mapping_model"),
        "pipeline_version": meta.get("pipeline_version"), "engine_version": meta.get("engine_version"),
        "started_at": meta.get("started_at"), "calls": len(meta.get("calls") or []),
        "input_tokens": tok.get("input_tokens"), "output_tokens": tok.get("output_tokens"),
        "cache_read_input_tokens": tok.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": tok.get("cache_creation_input_tokens"),
        "stage_durations_s": meta.get("stage_durations_s"),
        "errors": run.get("errors") or [],
    }}
