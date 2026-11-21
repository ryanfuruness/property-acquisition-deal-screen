# Deal Screen: technical design

This document is the contract between the parts of the system. Every component reads and writes the shapes defined here.

## Principle

The model reads, maps and judges. Code computes and verifies. No number reaches the memo unless code can trace it to a page, cell or calculation.

## Layout

```
data/
  mandate.yaml                 firm buy box and underwriting assumptions
  market/                      area reference data (rent index, yields), labelled by source
  deals/<deal_id>/
    package/                   what an analyst receives: om.pdf, rent_roll.xlsx, t12.pdf (names vary)
    truth.json                 ground truth, never read by the pipeline
engine/                        deterministic underwriting, no LLM, fully unit-tested
pipeline/                      ingest, extract, verify, reconcile, underwrite, mandate fit, memo
evals/                         scoring against truth.json, run history, failure log
site/                          static demo replaying recorded runs
runs/<deal_id>/run.json        recorded pipeline output used by the site
docs/                          product brief, design, research notes
```

## Pipeline stages

1. **Ingest** (code). PDFs to per-page text (pdfplumber) and per-page PNG (PyMuPDF, for the site). Spreadsheets to a cell grid with sheet and A1 addresses.
2. **Extract** (model). Each document is sent with a field list. Every field returns `{value, unit, as_of, source: {doc, page | cell}, quote}`. Missing fields return `null` with a reason; the model must not infer a value that is not stated.
3. **Verify** (code). For each extracted field: the quote must appear on the cited page (whitespace- and case-normalised), and the value must parse from the quote. Fields that fail are marked `unverified` and cannot feed the engine without analyst override.
4. **Rent roll** (model maps, code computes). The model identifies the header row, column meanings, unit-of-measure and any summary rows to exclude. Code parses every unit row and computes in-place rent, occupancy (by units and by area), expiry profile, average rent per sq ft by unit type, missing Ejari numbers, and vacant units carried at asking rent.
5. **Operating statement** (model maps, code totals). The model maps each line item to the standard chart of accounts below, with citations. Code totals the categories and flags standard costs that are absent.
6. **Reconcile** (code rules, then model review). A base underwriting runs first so each discrepancy's impact can be priced by re-running the engine. Deterministic checks compare the same quantity across sources. A model pass then reads the OM language for claims the rules cannot test (pro-forma rents presented as in-place, "potential" yields). Every discrepancy carries severity, the sources compared, the value the screen relies on and why, and the analyst action.
7. **Underwrite** (code). Trusted inputs plus mandate assumptions go into the engine.
8. **Mandate fit** (code). Rules from `mandate.yaml` give Pursue / Needs work / Pass with reasons.
9. **Memo** (model writes, code checks). The model writes prose from the fact sheet only. Code checks that every number in the prose matches a fact-sheet value; any that does not fails the run.

## Chart of accounts (operating statement)

Income: `rental_income`, `other_income`. Recoverables and losses: `vacancy_loss`, `collection_loss`.
Expenses: `service_charge`, `district_cooling`, `utilities_common`, `property_management`, `maintenance_repairs`, `insurance`, `security_cleaning`, `marketing_leasing`, `admin_other`, `sinking_fund`.

## Discrepancy record

```json
{
  "id": "occupancy_mismatch",
  "severity": "high | medium | low",
  "title": "OM occupancy higher than rent roll",
  "sources": [{"doc": "om.pdf", "page": 3, "value": 0.96, "quote": "..."},
              {"doc": "rent_roll.xlsx", "cell": "Rent Roll!A1:K90", "value": 0.89}],
  "relied_on": "rent_roll",
  "why": "The rent roll is unit-level and dated; the OM figure is undated marketing copy.",
  "impact": {"metric": "noi", "delta_aed": -412000},
  "analyst_action": "Request the Ejari export to confirm occupied units.",
  "detected_by": "rule | model"
}
```

## Run record (`runs/<deal_id>/run.json`)

`deal`, `documents` (with page images), `extracted` (fields with verification status), `rent_roll_summary`, `opex`, `discrepancies`, `underwriting` (inputs with provenance, outputs, sensitivities), `mandate_fit`, `memo` (markdown with citation anchors), `meta` (model, tokens, cost, duration, pipeline version).

## Reference data

`data/mandate.yaml` holds the buy box (hard and soft filters), verdict rules and all underwriting assumptions, including Dubai rules (DLD fees, RERA increase bands, VAT, corporate tax). `data/market/areas.yaml` holds area reference rents (exit yields are house view, in the mandate); it stands in for the RERA Smart Rental Index and a comps database. Nothing in the engine or pipeline hard-codes a Dubai number: rules are data, versioned with the repo.

## Extraction fields

**Offering memorandum.** `building_name`, `asset_type` (residential building, mixed-use with ground-floor retail, other), `area`, `plot_number`, `title_type` (freehold/non-freehold, single title/strata), `completion_year`, `floors`, `unit_count`, `unit_mix` (count by type), `bua_sqft`, `nsa_sqft` (convert from sq m when stated in sq m; record the original), `parking_spaces`, `occupancy_stated` with `as_of`, `annual_rent_stated` with its `basis` (in-place, potential, or unstated), `yield_stated` with its `basis` (gross or net; on asking price or on total cost), `asking_price_aed`, `chiller_arrangement` (tenant pays, landlord pays / chiller-free, unstated), `opex_stated_aed`, `lease_structure` (direct leases or master lease, and the master tenant), `upside_claims` (verbatim claims of rental upside).

**Rent roll** (per unit). `unit`, `unit_type`, `area_sqft`, `tenant`, `tenant_type`, `ejari_no`, `lease_start`, `lease_end`, `annual_rent_aed`, `cheques`, `deposit_aed`, `status` (occupied, vacant, notice served, under renewal, legal case), `chiller`. Summary rows are recognised and excluded from unit totals.

**Operating statement.** Period covered (months, start, end, whether annualised), and each line item mapped to the chart of accounts with its amount and citation.

## Engine interface

`engine.underwrite(deal_inputs, mandate, market) -> result`, pure and deterministic.

`deal_inputs`: `price_aed`, `area`, `nsa_sqft`, `bua_sqft`, `units` (list of rent-roll units: type, area, status, annual rent, lease end), `opex_aed` by chart-of-accounts category (from the operating statement; missing categories filled from mandate defaults and recorded as such), `other_income_aed`, `chiller_landlord_pays` (bool).

Unit-level lease model, annual periods over the hold, with leases expiring mid-year prorated by month:
- At expiry a tenant renews with `renewal_probability`. On renewal, rent moves toward the market reference: an under-rented unit rises by at most the RERA band for its gap to the index; an over-rented unit is reset to market (landlords cut to retain tenants in a falling market). On turnover, the unit re-lets at market after `downtime_months_on_turnover`, with a leasing fee.
- Market reference rent per unit = area 1BR rent psf x unit-type factor x unit area, grown by the house-view path.
- Vacant units at the start lease up at market after downtime.
- Structural vacancy and collection loss apply to the resulting gross income; management fee on effective gross income; input VAT on opex.

Outputs: year-by-year cash flow; Year-1 NOI; going-in net yield on price and on total cost; the OM's stated yield recomputed on the OM's own basis and on a correct basis; price per sq ft on NSA and BUA; acquisition cost breakdown; loan, debt service, Year-1 DSCR and debt yield; unlevered and levered IRR and equity multiple, pre- and post-tax; sensitivity grid (exit yield -50/0/+50 bps x rent path -5%/base/+5%); breakeven occupancy; and the **walk-away price**: the highest price that meets the target levered IRR and the DSCR floor (solved by bisection). Every output lists the inputs it depends on, with their provenance (`document`, `default`, `mandate`, `market`).

## Discrepancy catalogue

Rule-detected unless marked (model).
1. `occupancy_mismatch`: OM occupancy differs from the rent roll by more than 2 points.
2. `potential_rent_as_income`: OM income includes vacant units at asking rent, or equals rent-roll potential rather than in-place rent.
3. `gross_yield_as_net`: OM "net" yield does not deduct operating costs a buyer will bear.
4. `yield_excludes_acquisition_costs`: OM yield is on asking price, ignoring DLD 4% and fees.
5. `over_rented_vs_market`: a material share of income comes from units let above market reference rent (falling-rent 2026 market).
6. `upside_exceeds_rera_cap` (model + rule): OM claims rental uplift that RERA bands would not allow at renewal.
7. `missing_opex_items`: standard costs absent from the operating statement (district cooling in a chiller-free building, management fee, insurance, sinking fund).
8. `area_basis_confusion`: sq m stated as sq ft, or price per sq ft quoted on BUA without saying so.
9. `rent_roll_does_not_foot`: summary totals differ from the sum of unit rows.
10. `unit_mix_mismatch`: OM unit count or mix differs from the rent roll.
11. `expired_lease_counted_occupied`: units marked occupied with a lease end before the rent roll date, or missing Ejari numbers.
12. `collections_gap`: operating-statement rental income is materially below rent-roll in-place rent (economic vs physical occupancy).
13. `annualised_partial_period`: the operating statement covers fewer than 12 months but is presented as annual.
14. `master_lease_related_party` (model): income depends on a master lease, especially to a related party.
15. `expiry_concentration`: share of income expiring in any 12-month window above the mandate limit.
16. `title_check` (model): title or area suggests a non-freehold or nationality-restricted plot; flagged for legal check, never decided by the screen.

## Synthetic deal set

About 12 packages, generated from a seeded "true" building so ground truth is known by construction. Each true building is rendered into the documents a broker would send, then specific discrepancies are planted. The set covers the five mandate areas plus out-of-mandate cases, sizes from about 30 to 200 units, clean deals (to measure false flags), several layouts per document type (rent rolls with merged headers, summary rows, sq m columns, different column names; operating statements with different line-item names), and at least one scanned-image OM. All documents carry a "synthetic, for demonstration" footer.

`truth.json` per deal: `deal_id`, `true_building` (all facts), `om_fields` (correct extraction answers, including the stated-but-wrong values as stated), `rent_roll` (correct unit rows and totals), `opex` (correct categorised totals and period), `planted_discrepancies` (ids from the catalogue, with the expected values), `expected_verdict` and the reason, and `notes`.

## Evals

Scored against `truth.json` for each deal:
- Extraction: field-level accuracy within tolerance, and citation validity.
- Discrepancies: recall and precision against the planted list, by type.
- Underwriting: NOI and price metrics within tolerance of truth.
- Verdict: matches the expected mandate outcome.
- Memo: share of numbers grounded in the fact sheet (must be 100%).

Each eval run is saved with its pipeline version; `evals/FAILURES.md` records each failure found, its cause and the fix.
