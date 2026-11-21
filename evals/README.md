# Evals

Scores each recorded pipeline run (`runs/<deal_id>/run.json`) against the deal's ground truth (`data/deals/<deal_id>/truth.json`). The harness is independent of the pipeline: it reads run.json, truth.json, the deal documents and the engine, and imports one pipeline function (the memo number checker, see metric 7). It never calls a model.

```
python -m evals score [--runs runs/] [--label NAME] [--deal ID ...] [--no-write] [--json]
python -m evals report [evals/results/<file>.json]     # reprint a saved result
python -m pytest tests/evals
```

`score` prints a plain-text report and writes:

| File | Contents |
|---|---|
| `evals/results/<UTC timestamp>_<label>.json` | Everything: headline, per-deal detail, every check (`checks`) and every failed check (`misses`). |
| `evals/summary.json` | `latest` (headline with counts, per-deal brief, deals not scored) and `history`: one entry per label, oldest first, with the headline values. Re-scoring a label replaces its entry. Without `--label` the run is written as `unlabelled` and history is not touched. The site reads this file to show improvement across iterations. |
| `evals/REPORT.md` | Generated from the latest results: headline, history, per-deal table, OM fields, discrepancies by id, then every miss with deal, item, expected and got. Do not edit it. |
| `evals/FAILURES.md` | Hand-maintained log: what failed, root cause, fix, effect on metrics. |

A deal with no run.json, or an unreadable one, is listed under "not scored" and left out of every aggregate (never counted as zero or as a pass).

## How scoring works

Every comparison is a **check**: `{section, deal_id, item, expected, got, ok, outcome, note}`. Headline numbers are counts of checks, so every number can be traced to the checks behind it, and the report lists every failed check.

**Tolerances** (set in `evals/common.py`):
- Numbers: relative 0.5% (`|got - expected| <= 0.005 x |expected|`). Ratios such as occupancy and yields use the same relative rule (0.946 vs 0.95 passes; 0.0893 vs 0.089, printed "8.9%", passes).
- Counts (units, parking, year): exact.
- Categorical values: exact after normalisation (case, spaces, `-`/`_`). One spelling alias maps the generator's vocabulary to the pipeline's enum: `mixed_use_ground_floor_retail` = `mixed_use_residential_retail`.
- Text: case-, punctuation- and whitespace-insensitive equality. Codes (plot number, floors, unit ids) compare letters and digits only (`G+P+7` = `G + P + 7`, `G-01` = `G01`, `101.0` = `101`). Company names also drop legal suffixes (L.L.C, LLC, FZE, Ltd).

**Null versus stated.** Each field has one of five outcomes:

| Outcome | Truth | Run | Counts as |
|---|---|---|---|
| `correct` | value | same value within tolerance | right |
| `correct_null` | not stated in the document | no value (`null`, `"unstated"`, empty) | right |
| `wrong` | value | different value | wrong |
| `missed` | value | no value | wrong |
| `spurious` | not stated | a value | wrong (the run asserted something the document does not say) |

**What a careful reader could know.** truth.json is generated from the true building, and in a few places it holds facts the broker's documents never print. The scorer expects only what the documents show, and says where it departs from truth.json:
- *Asking rent of vacant units* is expected only where the rent roll prints it in that unit's row (checked by reading the document itself with openpyxl, csv or pdfplumber, in `evals/docs.py`). Vacant asking rent and potential rent totals are reduced by the unprinted amounts, with a note on the check. In the current set only d01 (Remarks column), d08 and d12 print asking rents.
- *Rent basis label.* The generator writes `basis_as_labelled: in_place` whenever the rent is not potential, even when the OM prints a bare "Annual Rental Income". For `annual_rent_stated.basis` the scorer accepts the true basis, and also `unstated` when the OM's own text for the figure (truth `quote`) carries no basis word (in-place, passing, contracted, current, potential, projected, asking).
- *Yield measure label.* The pipeline schema says "'ROI' or 'yield' with no qualifier is unstated". For `yield_stated.basis` the scorer accepts the true measure or the measure the OM's label claims (`Net ...` -> net, `Gross ...` -> gross, `ROI` -> unstated). The denominator (`on`) must match truth.
- *Occupied versus under renewal.* The engine treats them identically (`engine/leases.py`), and a rent roll without a status column cannot tell them apart, so unit status compares them as one class. Notice served, legal case and vacant are distinct.

## Metrics

### 1. OM field extraction
Compares `run.extracted.om` with `truth.om_fields`, one check per field per deal:
`building_name`, `asset_type`, `area (market_area)` (the run's canonical `market_area` against truth `area`), `plot_number`, `title_type.tenure` and `title_type.ownership` (scored separately; a truth tenure of "unstated (non-freehold indicated)" means the OM does not state it, so the right answer is no value), `completion_year`, `floors`, `unit_count`, `unit_mix` (every type's count must match; missing = 0), `bua_sqft`, `nsa_sqft` (sq ft after conversion), `parking_spaces`, `occupancy_stated`, `annual_rent_stated`, `yield_stated`, `asking_price_aed`, `price_psf_stated` (truth `price_psf`), `chiller_arrangement`, `opex_stated_aed`, `lease_structure` (type, and master tenant name), `upside_claims`, plus three basis checks where truth states the figure: `annual_rent_stated.basis`, `yield_stated.basis` (measure and denominator) and `price_psf_stated.basis` (the truth basis if the OM labels it, else `unstated`).
- `upside_claims` is right when every OM claim is matched by an extracted claim and every extracted claim matches an OM claim (match = at least 60% of the shorter text's words appear in the other). No claims in truth and none extracted is `correct_null`.
- Not scored: `broker` (not in the pipeline schema), the as-written `area` text (the canonical area is scored), `net_income_stated_aed` (truth has no answer).
- **Accuracy** = right checks / checks, overall and per field. **Trusted accuracy** additionally requires the run's own status to be `verified` or `verified_fuzzy` (a correct `correct_null` counts), because only verified fields feed the engine.
- **Citations**, for every field where both truth and run give a value: *page match* = the run's cited document is the OM and its page is truth `page` or one of `also_on_pages`; *run verified* = the run's verifier found the quote on the cited page; *valid* = run verified **and** (page match **or** the value is correct). The second branch exists because truth page lists are not exhaustive: a verified quote on another page that yields the right value is a usable citation. A page match whose quote did not verify is not valid.

### 2. Rent roll
Compares `run.rent_roll_summary` with `truth.rent_roll`.
- Units are matched on normalised unit id. **Recall** = matched / truth units. **Precision** = matched / run unit rows. Each unmatched run row is classified: *summary row counted as a unit* (its sheet row is one of truth `summary_rows`, which include totals, subtotals and group headings, or its unit/tenant text reads Total, Sub-total, Grand, Summary, Average or Occupancy), *duplicate*, or *extra unit*. Each missing unit is a miss.
- Unit fields on matched units: `unit_type`, `area_sqft` (0.5%), `status` (class rule above), and for let units `annual_rent_aed` and `lease_end` (exact date), for vacant units `asking_rent_aed` (visibility rule above). Reported per field and overall.
- Totals: `unit_count`, `let_units`, `in_place_rent_aed`, `occupancy_by_units`, `occupancy_by_area`, `vacant_asking_rent_aed`, `potential_rent_aed` (0.5%; counts exact), the sets `expired_leases_shown_occupied` and `let_units_missing_ejari` (exact), and `as_of` (rent-roll date; same year and month, since some documents give only the month and the engine's expiry windows are three months). The headline shows in-place rent and occupancy by units separately.
- Master lease (when truth or run has one): rent (0.5%), lease end (exact) and tenant, from `run.underwriting.deal_inputs.master_lease`.

### 3. Operating statement
Compares `run.opex` with `truth.opex`. Truth totals are what the statement presents for its period, mapped to the chart of accounts (for an annualised statement, its annualised figures); a category the statement omits is expected to be zero.
- One check per category present in either truth or run (rental and other income, vacancy and collection losses, the ten expense categories): `run.opex.totals_by_category` within 0.5%. A category with a truth amount and none in the run is `missed`; the reverse is `spurious`. Plus `total_opex_aed` against `run.opex.total_expenses_aed`.
- **Period correct** = `period.months_used` equals truth `months_covered` **and** `period.annualised` equals truth `annualised`. Start and end dates are also compared and listed, but do not enter "period correct".

### 4. Discrepancies
Against `truth.planted_discrepancies`, by catalogue id (`data/deals/index.json`). Per deal: TP = planted ids the run flagged, FN = planted not flagged, FP = catalogue ids flagged but not planted. **Recall** = ΣTP / Σplanted, **precision** = ΣTP / Σflagged (micro, over deals), also per id and per deal. **False flags on clean deals** (deals with nothing planted: d01, d02) are reported on their own; FPs on deals with planted items are counted separately. Each FP carries truth's `rule_checks_not_planted` values for that check, so the report shows why the item is not a discrepancy. Findings with ids outside the catalogue (`other_om_claim`) are listed but not scored; rejected model findings are not counted.

Severity is not scored, and a detection counts only if its id is the planted id.

**Alias table: empty.** An alias would credit one id for another; it is justified only where two catalogue entries describe the same finding. Candidates considered and rejected:
- `gross_yield_as_net` / `yield_excludes_acquisition_costs`: different errors (the numerator ignores costs vs the denominator ignores acquisition costs); d04 plants both.
- `potential_rent_as_income` / `occupancy_mismatch`: one is about income, the other about a stated ratio; d03 plants both.
- `master_lease_related_party` / `occupancy_mismatch`: a 100%-leased master lease explains the gap but they are separate findings; d11 plants both.
- `title_check` for a strata title (d09): the catalogue defines `title_check` as non-freehold or nationality-restricted; strata is neither, so it is a false positive against the planted list. The verdict metric is where a strata hard fail is credited.

### 5. Underwriting
For each deal the scorer runs `engine.underwrite(true_building.engine_inputs, mandate, market)` itself (the inputs carry `rent_roll_date`) and compares the run's `underwriting.outputs.metrics` with it: **Year-1 NOI** (`noi_year1`), **yield on cost** (`going_in_net_yield_on_cost`), **levered IRR** (`levered_irr_pre_tax`) and **walk-away price** (`walk_away_price_aed`). Each gets absolute and relative error (run minus truth) and a within-tolerance flag: NOI and walk-away within 2%, yield on cost within 0.10 points, levered IRR within 0.50 points. The headline gives the share within tolerance and the mean absolute error of each. The gap includes legitimate document-versus-truth differences (a statement that omits a cost the owner pays): that is what is being measured, how close the screen lands to the true building from the broker's papers. A run that could not underwrite misses all four.

### 6. Verdict
`expected_verdict` in truth.json is null by design. The scorer computes it with `engine.mandate_fit(true_building.deal_facts, <engine result on truth>, mandate)` and compares the run's `mandate_fit.verdict`. The note lists every mandate test whose status (pass, fail, unknown) differs between truth and run, which is usually the root cause.

### 7. Memo grounding
The scorer re-runs the pipeline's own memo checker (`pipeline.memo.tokens` and `_compare`, the code that decides whether a memo ships) on the run's memo and fact sheet, counting numbers instead of errors: **grounding** = numbers that carry an anchor to a fact-sheet key and match that fact at the precision written / all numbers, summed over deals. For a failed memo the rejected draft is scored. Anchors naming no fact are listed as misses. The checker is the pipeline's code at scoring time, not at run time: if it has changed since the run, the recheck can disagree with the run's recorded status, and the `memo status` miss says so (`agrees_with_run_status` in the results). **Memo pass rate** = runs whose memo status is `passed`. If the pipeline's checker cannot be imported the scorer falls back to the run's recorded check and says so in `method`.

### 8. Cost and time
From `run.meta`: `cost_usd`, `duration_s`, tokens, models, pipeline version, per deal; the headline gives mean per deal and total cost. Costs are the pipeline's own estimate at its assumed list prices.

## Changing the scorer

Tolerance or rule changes change every historical number. Make them in `evals/common.py` or the metric module, say why in FAILURES.md, bump `SCORER_VERSION` in `evals/scorer.py`, and re-score earlier labelled runs if their run files are still available. Tests: `tests/evals` (a perfect fixture for every deal scores 100%, and fixtures with specific errors score exactly as expected).
