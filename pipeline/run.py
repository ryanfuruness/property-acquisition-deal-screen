"""Run the whole screen for one deal and write ``runs/<deal_id>/run.json`` plus page images.

Order: ingest -> extract + verify (OM) -> rent roll -> operating statement -> deal_inputs and
a base underwriting -> reconcile rules (which use engine outputs for impacts) -> model review ->
final underwriting -> mandate fit -> memo. The schema of run.json is in pipeline/README.md.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import time
from pathlib import Path
from typing import Callable

import engine

from . import config
from .config import PIPELINE_VERSION, RunSettings
from .extract import extract_om
from .ingest import Document, ingest_package
from .llm import AnthropicClient, CallRecord, Ledger, ModelClient, ReplayClient
from .loader import PackageLoader
from .memo import build_fact_sheet, write_memo
from .opex import run_opex
from .reconcile import Context, merge, related_party_flag, review, run_rules
from .rentroll import run_rent_roll
from .verdict import TITLE_BLOCK, summarise_fit
from .underwriting import CannotUnderwrite, build_deal_inputs, chiller_landlord_pays, deal_facts, underwrite


def list_deals(deals_dir: Path = config.DEALS_DIR) -> list[str]:
    """Deal ids with a package folder. (index.json is not read: it lists the planted answers.)"""
    return sorted(p.name for p in deals_dir.iterdir() if (p / "package").is_dir())


def _pick(docs: list[Document], role: str, notes: list[str]) -> Document | None:
    found = [d for d in docs if d.role == role]
    if len(found) > 1:
        notes.append(f"{len(found)} documents look like {role}; using {found[0].doc_id}")
    return found[0] if found else None


def _doc_record(d: Document) -> dict:
    rec = {"doc_id": d.doc_id, "kind": d.kind, "role": d.role, "role_reason": d.role_reason}
    if d.kind == "pdf":
        rec["scanned"] = d.scanned
        rec["pages"] = [{"number": p.number, "image": p.image, "width_pt": p.width_pt, "height_pt": p.height_pt,
                         "ocr": p.ocr, "ocr_mean_conf": round(p.ocr_mean_conf, 1) if p.ocr_mean_conf else None}
                        for p in d.pages]
    else:
        rec["sheets"] = [{"name": s.name, "n_rows": s.n_rows, "n_cols": s.n_cols, "merged": s.merged,
                          "rows": [[None if c.value is None else str(c.value) for c in row] for row in s.rows]}
                         for s in d.sheets]
    return rec


class _Timer:
    def __init__(self) -> None:
        self.stages: dict[str, float] = {}

    def __call__(self, name: str):
        timer = self

        class _T:
            def __enter__(self):
                self.t = time.monotonic()

            def __exit__(self, *exc):
                timer.stages[name] = round(time.monotonic() - self.t, 2)
        return _T()


def run_deal(deal_id: str, settings: RunSettings | None = None,
             client_factory: Callable[[Ledger, str], ModelClient] | None = None,
             ledger: Ledger | None = None) -> dict:
    """Screen one deal end to end; returns the run record (also written to disk)."""
    settings = settings or RunSettings()
    ledger = ledger or Ledger(settings.runs_dir / "_ledger.json")
    ledger.check(settings.budget_usd)
    factory = client_factory or AnthropicClient
    client: ModelClient = (ReplayClient(factory, ledger, deal_id, settings.runs_dir / deal_id / ".model_cache")
                           if settings.replay else factory(ledger, deal_id))
    started, t0 = dt.datetime.now(dt.timezone.utc), time.monotonic()
    timer = _Timer()
    calls: list[CallRecord] = []
    notes: list[str] = []
    errors: list[dict] = []
    mandate, market = engine.load_mandate(), engine.load_market()
    market_areas = list(market["areas"])

    out_dir = settings.runs_dir / deal_id
    pages_dir = out_dir / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    loader = PackageLoader(deal_id, settings.deals_dir)
    with timer("ingest"):
        docs = ingest_package(loader, pages_dir, rel_to=out_dir)
    om_doc = _pick(docs, "om", notes)
    rr_doc = _pick(docs, "rent_roll", notes)
    st_doc = _pick(docs, "operating_statement", notes)

    om_fields: dict = {}
    if om_doc:
        with timer("extract_om"):
            om_fields, res = extract_om(client, settings.model, docs, om_doc, market_areas)
            calls.append(res.call)
    else:
        errors.append({"stage": "extract_om", "error": "no offering memorandum found in the package"})

    rr = None
    if rr_doc:
        with timer("rent_roll"):
            rr, res = run_rent_roll(client, settings.mapping_model, rr_doc)
            calls.append(res.call)
    else:
        errors.append({"stage": "rent_roll", "error": "no rent roll found in the package"})

    chiller, _ = chiller_landlord_pays(om_fields, rr["units"] if rr else [])
    opex = None
    if st_doc:
        with timer("opex"):
            opex, res = run_opex(client, settings.mapping_model, st_doc, docs, chiller)
            calls.append(res.call)
    else:
        notes.append("No operating statement in the package; every cost is a mandate default.")

    deal_inputs, prov, uw, uw_error = None, {}, None, None
    with timer("underwrite_base"):
        try:
            deal_inputs, prov, in_notes = build_deal_inputs(deal_id, om_fields, rr, opex, market)
            notes += in_notes
            uw = underwrite(deal_inputs, mandate, market)
        except (CannotUnderwrite, engine.DealInputError, engine.MarketDataError) as exc:
            uw_error = f"{exc.__class__.__name__}: {exc}"

    ctx = Context(om=om_fields, rr=rr, opex=opex, uw=uw, deal_inputs=deal_inputs, mandate=mandate, market=market)
    with timer("reconcile_rules"):
        rule_findings, rule_errors = run_rules(ctx)
        errors += [{"stage": "reconcile", **e} for e in rule_errors]
    model_findings, rejected, conclusion = [], [], "unclear"
    if om_doc:
        with timer("review"):
            try:
                model_findings, rejected, conclusion, res = review(client, settings.model, om_doc, docs, ctx,
                                                                   rule_findings, market_areas)
                calls.append(res.call)
            except Exception as exc:  # noqa: BLE001 - the rule findings stand; the gap is reported
                errors.append({"stage": "review", "error": f"{exc.__class__.__name__}: {exc}"})
    discrepancies = merge(rule_findings, model_findings)
    related, lease_structure = related_party_flag(discrepancies, conclusion, om_fields)

    if deal_inputs and deal_inputs.get("master_lease") and related is not None:
        with timer("underwrite_final"):
            deal_inputs, prov, _ = build_deal_inputs(deal_id, om_fields, rr, opex, market, related_party=related)
            uw = underwrite(deal_inputs, mandate, market)
    facts, facts_prov = deal_facts(om_fields, rr, related, lease_structure)
    fit = engine.mandate_fit(facts, uw, mandate)
    fit_words = summarise_fit(fit)
    for t in fit["tests"]:
        if any(b["test"] == t["name"] for b in fit_words["blocked_on"]):
            t["screen_note"] = TITLE_BLOCK

    fact_sheet = build_fact_sheet(om_fields, rr, opex, uw, fit | fit_words, discrepancies, mandate,
                                  notes + ([f"Could not underwrite: {uw_error}"] if uw_error else []))
    with timer("memo"):
        memo, results = write_memo(client, settings.model, fact_sheet)
        calls += [r.call for r in results]

    run = {
        "deal": {"deal_id": deal_id, "building_name": (om_fields.get("building_name") or {}).get("value"),
                 "market_area": (om_fields.get("market_area") or {}).get("value"),
                 "documents_used": {"om": om_doc and om_doc.doc_id, "rent_roll": rr_doc and rr_doc.doc_id,
                                    "operating_statement": st_doc and st_doc.doc_id}},
        "documents": [_doc_record(d) for d in docs],
        "extracted": {"om": om_fields},
        "rent_roll_summary": rr,
        "opex": opex,
        "discrepancies": discrepancies,
        "rejected_model_findings": rejected,
        "underwriting": {"status": "ok" if uw else "not_underwritten", "error": uw_error,
                         "deal_inputs": deal_inputs, "inputs_provenance": prov,
                         "outputs": uw, "sensitivities": (uw or {}).get("sensitivity")},
        "mandate_fit": {**fit, **fit_words, "deal_facts": facts, "deal_facts_provenance": facts_prov,
                        "lease_structure_conclusion": conclusion},
        "fact_sheet": fact_sheet,
        "memo": memo,
        "notes": notes,
        "errors": errors,
        "meta": _meta(settings, calls, started, time.monotonic() - t0, timer.stages),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str))
    return run


def _meta(settings: RunSettings, calls: list[CallRecord], started: dt.datetime, duration: float,
          stages: dict[str, float]) -> dict:
    tot = {k: sum(getattr(c, k) for c in calls) for k in
           ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
    return {
        "pipeline_version": PIPELINE_VERSION, "engine_version": engine.ENGINE_VERSION,
        "model": settings.model, "mapping_model": settings.mapping_model,
        "started_at": started.isoformat(timespec="seconds"), "duration_s": round(duration, 1),
        "stage_durations_s": stages, "calls": [c.as_dict() for c in calls], "tokens": tot,
        "cost_usd": round(sum(c.cost_usd for c in calls), 4),
        "prices_usd_per_mtok": {m: config.PRICES_USD_PER_MTOK.get(m, config.FALLBACK_PRICE)
                                for m in {settings.model, settings.mapping_model}},
        "prices_note": "assumed list prices; see pipeline/config.py",
    }
