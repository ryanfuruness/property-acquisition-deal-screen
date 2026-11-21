# Independent tie-out: underwriting engine v2.0.0, deal `jvc-60-smoke`

**Result: 143 of 143 checks pass. I found no arithmetic error in the engine.** The largest difference on any figure is AED 0.0000001 on money amounts and 8e-13 on IRRs. That is floating-point noise.

## What was tied out

- **Deal.** `tests/engine/fixtures/jvc_60_units.json`: 60 units in JVC at AED 47.0m. 57 units are let, one of them with notice served, and 3 are vacant.
- **Engine run.** `python -m engine tests/engine/fixtures/jvc_60_units.json --json`. The output is saved as `engine_output_jvc_60_units.json`.
- **How the workbook was built.** `tieout_jvc_60_units.xlsx` was written from the method text in `engine/README.md` (v2) and from the raw inputs: the fixture, `data/mandate.yaml` and `data/market/areas.yaml`.
- **Independence from the engine.** No engine code was read into or copied into the workbook. Engine numbers appear only on the `EngineOutput` sheet, as pasted data, and are used only by the comparison cells.

| Sheet | Contents |
|---|---|
| `TieOut` | Each figure as workbook formula vs engine value, with the difference, relative difference, tolerance and PASS/FAIL. The summary is in cell B3. |
| `Inputs` | Every deal, mandate and market input, each with its source file and key. They are named ranges, for example `Price`, `RenewProb` and `BandUpTo`. It also holds three engine constants taken from the README (sinking-fund age multipliers, walk-away step). |
| `Units` | One row per unit: rent, lease end, screen reference rent, status, roll month. Then six expiry blocks and six year blocks (described below). |
| `CashFlow` | Years 1-6: potential rent, downtime, other income, vacancy top-up, collection loss, EGI, management fee, nine opex categories (stated or defaulted, grown at 2.5%), leasing fees net of any stated marketing line, input VAT (gross, recovered, net) and NOI. |
| `Debt` | DLD 4%, admin, trustee fee, broker fee and its VAT, then mortgage registration. Loan sized as min(45% LTV, NOI₁ / (1.40 × loan constant)) at 6.80% over 15 years. Annuity debt service (Excel `PMT`), the schedule, DSCR, ICR and debt yield. |
| `Returns` | Exit yield = max(area 6.50%, entry yield) + 25 bps + age premium. Forward NOI over the exit yield, 2% selling costs, unlevered and levered cash flows, Excel `IRR`, equity multiples. It also re-tests the walk-away price. |
| `EngineOutput` | Engine values as data, each labelled with its JSON path. |

**How the `Units` sheet works.**
- **Expiry blocks (1-6).** Each block holds the month and year of the expiry, that year's reference rent, the renewal probability and the notice-window flag. It then holds the rent and weight of each possible tenant "chain": the current tenant, plus a tenant who arrived by turnover at each earlier expiry.
- **Renewal.** A tenant above the reference resets to it. Otherwise the rent rises by the RERA band on that tenant's own gap, capped at the reference. There is no increase inside the 90-day notice window.
- **Turnover.** The unit re-lets at that year's reference.
- **Expected rent.** The probability-weighted sum of the chains.
- **Year blocks (1-6).** Each year's potential rent is the months before the expiry at the old blend plus the months after at the new blend. The year blocks also give downtime (it spills into the next year for December expiries), the leasing fee (booked in the re-let month) and expected rent net of downtime.
- **Per-unit check.** The last column compares each unit's expected rent with the engine's `expected_rent_by_year` for all six years.
- **Rent-roll statistics** are below the unit table: occupancy, in-place rent, over-rent and expiry windows.

**Tolerances.**
- **AED amounts:** |diff| ≤ AED 1,000 and ≤ 0.1% of the engine value.
- **Ratios:** ≤ 0.1 bp.
- **IRR:** ≤ 1 bp.
- **Multiples and DSCR:** ≤ 0.001x.

All of these are far looser than the differences actually found.

**Recalculation.** LibreOffice headless, through the xlsx skill's `recalc.py`: 10,116 formulas and 0 errors. The workbook uses no functions that LibreOffice cannot evaluate.

## Result table (headline figures)

| Figure | Workbook | Engine | Difference | Pass |
|---|---|---|---|---|
| Unlevered IRR, pre-tax | 5.1633% | 5.1633% | 7e-15 | PASS |
| Unlevered equity multiple | 1.2528x | 1.2528x | 0 | PASS |
| Entry yield on price | 6.5103% | 6.5103% | 0 | PASS |
| Exit yield | 6.7603% | 6.7603% | 0 | PASS |
| Net yield on total cost | 6.1292% | 6.1292% | 0 | PASS |
| NOI Year 1 | 3,059,848 | 3,059,848 | 0 | PASS |
| Potential / gross rental income Y1 | 4,099,552 / 3,930,841 | same | 0 | PASS |
| EGI Y1 | 3,920,409 | 3,920,409 | 0 | PASS |
| Operating costs Y1 | 860,562 | 860,562 | 0 | PASS |
| Forward NOI (Y6) | 3,244,810 | 3,244,810 | 0 | PASS |
| Acquisition costs (total) | 2,922,471 | 2,922,471 | 0 | PASS |
| Loan (DSCR-bound; LTV cap 21,150,000) | 20,160,229 | 20,160,229 | 0 | PASS |
| LTV | 42.894% | 42.894% | 0 | PASS |
| Annual debt service | 2,185,605 | 2,185,605 | 0 | PASS |
| DSCR Y1 | 1.400x | 1.400x | 0 | PASS |
| Gross exit value | 47,997,914 | 47,997,914 | 0 | PASS |
| Net sale proceeds | 47,037,956 | 47,037,956 | 0 | PASS |
| Loan balance at exit | 15,493,706 | 15,493,706 | 0 | PASS |
| Levered IRR, pre-tax | 4.0186% | 4.0186% | -8e-13 | PASS |
| Levered equity multiple | 1.2055x | 1.2055x | 0 | PASS |
| Walk-away AED 34,930,000: IRR at price / +10k | 7.50046% / 7.49791% | same | <1e-12 | PASS (it brackets the 7.50% target) |
| Occupancy (units / area) | 95.00% / 94.54% | same | 0 | PASS |
| Max 3-month expiry share | 26.95% | 26.95% | 0 | PASS |
| Per-unit expected rent, 60 units × 6 years | — | — | sum of abs diffs 0 | PASS |

`TieOut` also compares 13 cash-flow lines for each of the six years (78 checks), the acquisition-cost lines, five years of interest, and all six unlevered and six levered cash flows.

## Branches this deal does not exercise: two stress variants

The JVC deal is DSCR-bound and has no retail. It has no age premium, no stated marketing line, a stated chiller arrangement and no collection override, so several README branches go untested. I made two copies of the fixture in `variants/` that change only the inputs. They were run through the engine and through the same workbook builder (`python evals/tieout/build_tieout.py <fixture> <engine json> <out.xlsx>`).

| Variant | Changes | Result |
|---|---|---|
| `jvc_60_stress_dscr.json` | Completion 2010 (age 22 at exit: +25 bps age premium); `chiller_landlord_pays: null` (cooling default 9/sq ft); stated `marketing_leasing` 30,000; `collection_loss_override` 2%; unit 160 retail (VAT recovery); a lease end on the 20th (roll rounds to next month); one `under_renewal` unit; price AED 40m | 143/143 PASS |
| `jvc_60_stress_ltv.json` | As above, plus price AED 33m (the **LTV** limit binds) and `opex_includes_vat: true` | 143/143 PASS |

I also re-ran the engine at prices from AED 30m to 90m. The walk-away stays at AED 34,930,000, which agrees with the README's statement that it does not depend on the asking price.

## Differences and observations

There are no differences to explain. Where the README leaves something to interpretation, the engine behaves as follows; this was confirmed by the tie-out matching to the dirham:

1. **Month of the leasing fee.** The README says the fee is charged "in the month of re-letting". With 1.5 months of downtime the re-let falls mid-month, and the engine books the fee in month m+1, which is `floor(expiry month + downtime)`. Booking it in the expiry month instead would move about AED 3.9k into Year 1 (immaterial). Suggest the README say "month m + floor(downtime)".
2. **Notice window.** The window blocks only increases. Over-rented tenants expiring in months 0-2 (units 124, 129, 141, 160) are still reset down to the reference at renewal. This matches the README wording ("get no increase") but is worth stating explicitly.
3. **`expected_rent_by_year` is net of downtime.** The README does not say so; the per-unit tie-out confirms it.
4. **Cosmetic issue in the engine output.** The notice-served unit 108 reports `renewal_rent` 42,000 under `rera_band_5pct` even though its renewal probability is 0. The figure carries zero weight and does not affect any number.
5. **Lease timing at the end of the horizon.** Leases are modelled through month 71 only. A December Year-6 expiry loses its downtime spill and fee beyond the horizon. This is consistent with the 6-year model, not an error.

## Not covered

- The workbook does not model `legal_case` units or master leases (the deal has neither). Their rows would be wrong if those statuses were used.
- Not tied out: post-tax (indicative) returns, the 3×3 sensitivity grid, the walk-away *search* (only the engine's answer was tested), the amortisation sensitivity, the OM yield check and `mandate_fit`.

## Reproduce

```
python -m engine tests/engine/fixtures/jvc_60_units.json --json > evals/tieout/engine_output_jvc_60_units.json
python evals/tieout/build_tieout.py
python <xlsx skill>/scripts/recalc.py evals/tieout/tieout_jvc_60_units.xlsx 180
```
