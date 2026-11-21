# Deal screen pipeline

Reads a broker's package (offering memorandum, rent roll, operating statement), checks every
figure it takes against its page or cell, reconciles the documents, underwrites the deal with
the deterministic engine, tests it against the mandate and writes a screening memo whose
numbers are checked against a fact sheet. The contract is [docs/DESIGN.md](../docs/DESIGN.md).

**The model reads, maps and judges; code computes and verifies.** No figure reaches the engine
or the memo unless code has traced it to a page, a cell or an engine calculation.

```
export ANTHROPIC_API_KEY_FILE=/path/to/key      # or ANTHROPIC_API_KEY
python -m pipeline run d03-sorrel-jvc           # one deal
python -m pipeline run-all [--model claude-sonnet-5-5] [--mapping-model claude-haiku-5-5] [--budget 25]
python -m pytest tests/pipeline                 # unit and stubbed end-to-end tests, no API calls
```

Output: `runs/<deal_id>/run.json` and `runs/<deal_id>/pages/<doc>-p<N>.png` (every PDF page;
text pages at 144 dpi as 256-colour palette PNG, about 25-45 KB; scanned pages at 108 dpi in
16 grey levels, about 300-400 KB, because scan speckle compresses badly). `--replay` reuses stored model responses for byte-identical
requests (`runs/<deal_id>/.model_cache/`), so code-side changes can be re-run at no cost.
`DEAL_SCREEN_DEBUG=1` prints tracebacks.

## Stages and modules

| Stage | Module | Model? | What code guarantees |
|---|---|---|---|
| Package access | `loader.py` | no | Only `data/deals/<id>/package/` is readable; `truth.json`, `index.json`, `..` and symlinks out are refused (tested). |
| 1 Ingest | `ingest.py` | no | PDF text and word boxes (pdfplumber); image pages with no text layer are OCR'd with Tesseract in three preprocessing passes (all kept); PDF tables become cell grids (ruled tables, else column clustering) with cell boxes; xlsx/csv become A1 grids; pages rendered to PNG; documents classified by file name, then content. |
| 2 Extract | `extract.py`, `schemas.py` | yes | OM sent as a native PDF document block (layout, and page images for a scan) with a tool schema: every field has value, unit, as_of, source {doc, page}, verbatim quote, or null with a reason. |
| 3 Verify | `verify.py`, `numbers.py` | no | Quote found on the cited page (case/whitespace, then punctuation-insensitive; ellipsis parts in order); fuzzy (>= 0.85) only on OCR pages and only if every figure in the quote is in the matched OCR text; value parses from the quote exactly (AED, commas, k/m/mn/million/bn, %, sq ft / sq m with conversion); categorical values need a keyword in the quote; boxes of the matched words. A quote found on another page is accepted with the page corrected and the move recorded. |
| 4 Rent roll | `rentroll.py` | maps | Model returns header rows, column meanings, units of measure, rows to exclude, status and unit-type vocabularies, summary-row cells and the cells of a master lease's terms. Code reads every cell, drops total rows even if the layout missed them, converts sq m and monthly rent, treats rent on a vacant row as asking rent, reads asking rents and notices from a Remarks/Notes column ("Asking AED 76,500", "Vacating on expiry"), keeps every cell address, and computes the summary. The roll date comes from the cell the model names, else a dated line ("as at", "as on", "updated", "run date") in the sheet or PDF text, else a dated title line, else the file name; a month alone is read as month end; `as_of_source` records which. |
| 5 Operating statement | `opex.py` | maps | Model maps each line to the chart of accounts and points to the amount cell, month range or (PDF) a quoted line, and states the period. Code reads amounts, annualises a partial period when needed, totals categories, checks the statement's own totals and lists absent standard costs. |
| 7 Underwrite (base) | `underwriting.py` | no | `deal_inputs` from verified fields and parsed documents only; rent roll drives units; mandate defaults fill gaps (labelled by the engine); provenance per input. |
| 6 Reconcile | `reconcile.py` | rules, then review | 16 catalogue rules with thresholds in `config.ReconcileThresholds`; impacts priced by re-running the engine where an input changes. Model review (OM cached) for master lease / related party, title, upside language and other OM claims; a finding needs a quote code verifies, and findings code facts contradict are rejected. |
| 7-8 Final underwriting, mandate fit | `run.py`, `verdict.py` | no | Re-run with the related-party flag; `engine.mandate_fit` on verified facts (unknown counts against the deal). `verdict.py` words the result: test names in plain English, and a deal whose title the documents do not establish is reported as blocked on title ("Title not stated; legal check required before any further work."), which leads the verdict and the memo's open items. The screen never decides title. |
| 9 Memo | `memo.py` | writes | Fact sheet only; every number carries `[[fact_id]]`; code checks each; one retry with the errors; a memo that still fails is marked `failed` and not shipped. |

Stages run in the order ingest, extract/verify, rent roll, statement, base underwriting, rules,
review, final underwriting, mandate fit, memo: the rules need engine outputs (over-rent share,
renewal rents, expiry windows) to test and price discrepancies.

Prompts are in `prompts/` (`om_system.md` is shared by the two OM calls so the cached prefix
matches). Model calls go through `llm.ModelClient`; tests use a stub (`tests/pipeline/helpers.py`).
Current models reject a forced `tool_choice`, so calls use `auto`, the prompt names the tool, and
a reply without a tool call gets one reminder turn.

## Memo anchor syntax

The writer sees the citable facts as `fact_id | value as written | what it is` (values formatted
by `memo.display`) and may write only those numbers. Every number in the memo is immediately
followed by `[[fact_id]]`, a key of `run.json`'s `fact_sheet`, one anchor per number (each end of a
date range has its own fact and anchor): `Walk-away AED 70.1m [[uw.walk_away_price_aed]], 15.6% [[uw.walk_away_discount_to_asking]] below asking.`
The checker finds money (with k/m/bn), percentages, multiples (`1.47x`), bps, sq ft, counts,
years, dates and month-years; pairs each with the anchor that follows within 32 characters with
no other number in between; and compares it with the fact after rounding to the precision
written (`1.5x` matches 1.4713). Ratios must be written as percentages. A number anchored to a
text fact must appear in that text. Exempt: `Year 1`, `T-12`, unit types (`1BR`), floor codes
(`G+P+7`), place names (`District 11`, `Al Barsha 1`), `Years 1 to 5`, `12-month`, `3M EIBOR`,
list markers and headings. Identifiers in prose (`min_dscr_year1`) are rejected: the memo must
use plain words. The site renders each anchor as a
link to `fact_sheet[fact_id].source`.

## run.json schema

Top-level keys (DESIGN.md's run record, plus what the site needs to render citations):

```
deal                 {deal_id, building_name, market_area, documents_used: {om, rent_roll, operating_statement}}
documents[]          {doc_id, kind: pdf|sheet, role, role_reason,
                      pdf:   scanned, pages[]: {number, image ("pages/om-p1.png"), width_pt, height_pt, ocr, ocr_mean_conf},
                      sheet: sheets[]: {name, n_rows, n_cols, merged[], rows: [[str|null]]}}   # full grid for cell citations
extracted.om         {<field>: FieldRecord, upside_claims: [ClaimRecord]}
rent_roll_summary    {doc, layout (model's mapping, verbatim), as_of_source, units[]: Unit, skipped_rows[],
                      master_lease: Unit|null, stated_totals[]: {measure, label, value, raw, cell, page, bbox}, summary}
opex                 {doc, period: {start, end, months_covered, presented_as_annual, annualised, evidence[], months_used,
                      annualisation: {factor, note}}, amount_basis, vat_basis, lines[]: Line, totals_by_category,
                      total_income_aed, total_deductions_aed, total_expenses_aed, noi_aed, opex_ratio,
                      stated_total_checks[], absent_standard_categories[], unverified_lines[], notes}
discrepancies[]      Discrepancy (DESIGN.md record), most severe first
rejected_model_findings[]   review findings dropped, with rejected_because
underwriting         {status: ok|not_underwritten, error, deal_inputs (exactly what the engine got),
                      inputs_provenance: {<input>: {from, status, doc, page, bbox, quote | cells | note}},
                      outputs (engine result, see engine/README.md), sensitivities (= outputs.sensitivity)}
mandate_fit          engine.mandate_fit result (title test gets screen_note when blocking) + {headline, plain_reason,
                      blocked_on[]: {test, statement}, tests_in_words, deal_facts, deal_facts_provenance,
                      lease_structure_conclusion}
fact_sheet           {<fact_id>: {value, unit, label, source}}
memo                 {status: passed|failed, markdown (null if failed), rejected_draft (failed only; never display),
                      attempts[]: {attempt, errors[]}, anchor_syntax: "[[fact_id]]"}
notes[], errors[]    data-handling notes; stage or rule errors (a rule that raises is reported here)
meta                 {pipeline_version, engine_version, model, mapping_model, started_at, duration_s,
                      stage_durations_s, calls[]: {stage, model, input_tokens, output_tokens,
                      cache_creation_input_tokens, cache_read_input_tokens, cost_usd, duration_s, stop_reason, tool},
                      tokens (totals), cost_usd, prices_usd_per_mtok, prices_note}
```

**FieldRecord** `{value, unit, as_of, quote, basis?, stated?: {value, unit} (areas as printed),
source: {doc, page, bbox: [[x0, top, x1, bottom], ...] (page fractions, one box per text line),
match: exact|normalised|fuzzy, similarity, ocr}, status: verified|verified_fuzzy|unverified|not_stated,
reason, checks: {quote, value}}`. Only `verified` and `verified_fuzzy` fields are used.

**Unit** `{unit, unit_type (studio|1br|2br|3br|retail|other), unit_type_text, floor, area_sqft,
area_original?: {value, unit: sqm}, tenant, tenant_type, ejari_no, lease_start, lease_end,
annual_rent_aed, asking_rent_aed, cheques, deposit_aed, status, status_text, status_stated (before remarks
refine it), chiller, remarks,
source: {doc, sheet, row, range ("Rent Roll!A7:K7"), cells: {field: "Rent Roll!H7"}, page?, bbox?: {field: box}},
notes[]}`. `rent_roll_summary.summary` has `as_of, unit_count, let_units, vacant_units,
status_counts, occupancy_by_units, occupancy_by_area, area_sqft_total, in_place_rent_aed,
legal_case_rent_aed, vacant_asking_rent_aed, vacant_units_with_asking_rent, potential_rent_aed,
by_type{type: {units, let, area_sqft, rent_aed, avg_rent_psf, avg_rent_aed}}, expiry_by_quarter[],
max_quarter_expiry_share, expired_leases_shown_occupied[], let_units_missing_ejari[], deposits_aed,
units_unparsed_type[], units_without_area[], let_units_without_rent[]`.

**Line** `{label, category, sign, note, amount_aed (as stated, before annualisation), status, reason,
source: {doc, cell | cells | page+quote+bbox, label_cell}}`.

**Discrepancy** `{id, severity, title, sources[]: {doc, page? | cell?, bbox?, quote?, value,
unit: aed|pct|sqft|count|date|text, label},
relied_on, why, impact: {metric, delta_aed | delta | value, basis, base?, alternative?,
walk_away_delta_aed?} | null, analyst_action, detected_by: rule|model|rule+model}`. A source with
`doc: "engine"` is an engine calculation; `data/mandate.yaml` or `data/market/areas.yaml` mark reference data.

## Costs

Prices in `config.PRICES_USD_PER_MTOK` are assumptions to update. Each call's tokens and cost are in
`meta.calls`; `runs/_ledger.json` keeps the running total (file-locked, safe for parallel runs) and a
run refuses to start once it exceeds `--budget` (default USD 25).
