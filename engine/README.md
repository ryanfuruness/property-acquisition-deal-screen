# Underwriting engine

Deterministic underwriting for the Dubai residential-building deal screen. The engine is pure Python (standard library plus PyYAML for the loaders). It makes no LLM calls, uses no network and has no randomness: the same inputs always give the same output. Every rule and number comes from `data/mandate.yaml` and `data/market/areas.yaml`, which are passed in as dicts. The engine hard-codes only the analysis settings that DESIGN.md fixes: the sensitivity axes, the AED 10,000 walk-away grid and the 12-month expiry window.

```python
from engine import underwrite, mandate_fit, recompute_stated_yield, load_mandate, load_market

mandate, market = load_mandate(), load_market()          # default paths: data/...
result = underwrite(deal_inputs, mandate, market)        # dict, JSON-serialisable
fit = mandate_fit(deal_facts, result, mandate)           # Pursue / Needs work / Pass
```

```
python -m engine tests/engine/fixtures/jvc_60_units.json          # readable summary
python -m engine tests/engine/fixtures/jvc_60_units.json --json   # full result + mandate fit
python -m pytest tests/engine                                      # tests
```

The CLI accepts a plain `deal_inputs` file, or `{"deal_inputs": {...}, "deal_facts": {...}}` to include a full mandate fit.

## `deal_inputs` schema

All money is in AED, all areas in sq ft, and every rate is a ratio (0.05 means 5%). Fields not listed here are rejected.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `deal_id` | str | no | Echoed back in the result. |
| `price_aed` | number > 0 | **yes** | Price being underwritten (usually the asking price). |
| `area` | str | **yes** | Must match a key of `areas` in areas.yaml (case-, space- and `-`/`_`-insensitive). An unknown area raises `MarketDataError`. |
| `nsa_sqft` | number > 0 | **yes** | Net saleable/leasable area. Opex defaults are priced on it. |
| `bua_sqft` | number > 0 or null | no | Built-up area. Used only for price per sq ft BUA. |
| `units` | list | **yes**, unless `master_lease` is given | Rent-roll rows; see below. Under a master lease they are used only after reversion, and may be omitted. |
| `opex_aed` | dict | no | Annual operating costs by chart-of-accounts category (below). A missing key or `null` means not stated. `0` means stated as zero. |
| `opex_includes_vat` | bool | no, default `false` | Set `true` if the stated opex already includes VAT. Input VAT is then added only to the costs the engine computes (management and leasing fees). |
| `other_income_aed` | number | no, default 0 | Annual non-rent income (parking and similar), Year-1 amount. Grows at `other_income_growth` from Year 2. |
| `chiller_landlord_pays` | bool or null | no, default `null` | `true` means a chiller-free building where the landlord pays cooling. `null` (unstated) applies the cooling default conservatively, with a warning. |
| `om_stated` | dict | no | The OM's own income and yield, for the yield check (below). |
| `master_lease` | dict or null | no | A lease of the whole building to one tenant (below). |
| `provenance` | dict | no | Overrides the default `document` tag for a field, for example `{"price_aed": "default"}` or `{"opex_aed.insurance": "default"}`. Values must be `document`, `default`, `mandate` or `market`. |

**`units[]`** (field names match the rent-roll extraction fields in DESIGN.md):

| Field | Type | Required | Meaning |
|---|---|---|---|
| `unit` | str | no | Unit number; defaults to the row position. |
| `unit_type` | str | **yes** | A key of `unit_type_factors`: `studio`, `1br`, `2br`, `3br` or `retail`. Case, spaces, `-` and `_` are ignored, so `"1 BR"` is accepted. |
| `area_sqft` | number > 0 | **yes** | Unit area. |
| `status` | str | **yes** | `occupied`, `under_renewal`, `notice_served`, `vacant` or `legal_case`. |
| `annual_rent_aed` | number or null | for occupied, under-renewal and notice-served units | Contract rent. It is ignored for vacant units, so a rent roll that carries asking rent on vacant units cannot inflate income. For a legal-case unit it is optional and counts in rent-roll statistics only, never in the cash flow. |
| `lease_end` | `YYYY-MM-DD` or null | no | Lease expiry. If an occupied unit has none, the unit rolls at the analysis start and a warning is raised. |

**`master_lease`:**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `tenant` | str or null | no | Master tenant name. |
| `related_party` | bool or null | no | `true` if the master tenant is related to the seller. `null` means unknown. `mandate_fit` reads this flag. |
| `annual_rent_aed` | number > 0 | **yes** | Master-lease rent, held flat until expiry. |
| `lease_end` | `YYYY-MM-DD` | **yes** | Master-lease expiry. It is rounded to a roll month like any lease. |
| `cheques` | number or null | no | Number of cheques a year. Recorded only. |

Unit statuses and rents in a rent roll supplied with a master lease are the operator's sub-tenancies. The engine does not use them; it uses only each unit's type and area after reversion, so `annual_rent_aed` and `lease_end` are not required there.

**`opex_aed` categories:** `service_charge`, `district_cooling`, `utilities_common`, `property_management`, `maintenance_repairs`, `insurance`, `security_cleaning`, `marketing_leasing`, `admin_other`, `sinking_fund`.

**`om_stated`:** `{"annual_rent_aed": number|null, "net_income_aed": number|null, "yield": ratio|null, "yield_basis": {"measure": "gross"|"net"|"unstated", "on": "asking_price"|"total_cost"|"unstated"}}`. A string such as `"gross_on_price"` is also accepted for `yield_basis`. The yield is reproduced from `net_income_aed` when the basis is net and that field is given, and from `annual_rent_aed` otherwise.

## `mandate_fit(deal_facts, uw_result, mandate)`

`deal_facts`: `asset_type`, `area`, `title_type` (for example `freehold_single_title`), `unit_count`, `price_aed`, `completion_year`, `lease_structure` (`direct_leases` or `master_lease`), and `master_lease_related_party`, a bool that is `true` if income depends on a master lease to a related party. A missing or `null` value is unknown. `unit_count` and `price_aed` fall back to the underwriting result when absent. The related-party test combines three sources, and any `true` wins: `master_lease_related_party`, the `related_party` flag of the underwriting result's `master_lease`, and `lease_structure: direct_leases` (which means no master lease, a pass). With none of these the test is unknown. `uw_result` can be `None` (the deal could not be underwritten, for example out-of-area); every engine-based test is then unknown.

It returns `{"verdict", "reason", "hard_fails", "soft_fails", "unknown", "tests"}`. `tests` has one record per filter in `buy_box`:

```json
{"name": "min_dscr_year1", "kind": "hard", "threshold": 1.3, "actual": 1.046,
 "passed": false, "status": "fail", "source": "engine",
 "reason": "Year-1 DSCR 1.05x misses the at least 1.30x requirement."}
```

`status` is `pass`, `fail` or `unknown`, and `passed` is `true`, `false` or `null`. An unknown counts as a soft fail, never a pass, even for a hard filter. The verdict follows `verdict_rules`: any hard fail gives **Pass**; soft fails plus unknowns of at most `pursue_if_soft_fails_at_most` give **Pursue**; anything else gives **Needs work**. A filter in the mandate with no implemented test raises `ValueError`, so the code and the mandate cannot drift apart. The engine metrics tested are `dscr_year1`, `going_in_net_yield_on_cost`, `levered_irr_pre_tax`, `levered_equity_multiple_pre_tax`, `occupancy_by_units`, `max_expiry_share_quarter` and `over_rent_share_of_income`.

## Result shape

| Key | Contents |
|---|---|
| `engine_version`, `deal_id`, `analysis_start`, `hold_years` | Run identification. |
| `inputs` | Every input the run used, by dotted name: `{"value", "unit", "provenance", "note"?}`. |
| `metrics` | Headline numbers, each a **metric** (below), listed under "Metrics" below. |
| `acquisition_costs` | Metrics for `dld_transfer_fee`, `dld_admin`, `trustee_fee`, `broker_fee`, `broker_fee_vat`, `mortgage_registration`, `transfer_costs` and `total`. |
| `cash_flow` | Years 1 to hold+1: `years`, `period_start`, `period_end`, `in_hold`, and `lines` (`potential_rental_income`, `downtime_loss`, `gross_rental_income`, `other_income`, `gross_income`, `structural_vacancy`, `collection_loss`, `effective_gross_income`, `management_fee`, `operating_expenses`, `leasing_fees`, `input_vat`, `total_operating_costs`, `noi`), with `master_lease_income` after `gross_rental_income`, plus `opex_by_category`. `potential_rental_income` includes master-lease rent. Each line is a **series**. |
| `debt_schedule` | Years 1 to hold: `opening_balance`, `interest`, `principal`, `debt_service`, `closing_balance`. |
| `returns_cash_flows` | Years 0 to hold: `unlevered_pre_tax`, `unlevered_post_tax`, `levered_pre_tax`, `levered_post_tax`, `tax_unlevered`, `tax_levered`. |
| `sensitivity` | `rent_shifts`, `exit_yield_shifts_bps`, `units`, `depends_on` and nine `cells`, each with `rent_shift`, `exit_yield_shift_bps`, `exit_yield`, `noi_year1`, `dscr_year1`, `levered_irr_pre_tax`, `unlevered_irr_pre_tax` and `levered_equity_multiple_pre_tax`. |
| `walk_away` | `price_aed`, `binding_constraint` (`levered_irr`, `dscr_year1` or `both`), `target_levered_irr`, `dscr_floor`, the IRR and DSCR at the price and one AED 10,000 step above it, `discount_to_asking`, and `going_in_net_yield_on_cost_at_price`. |
| `om_yield_check` | `null`, or `summary` ("The OM says X; on a buyer's basis it is Y"), `om_basis`, `reproduces_stated`, and metrics `stated_yield`, `reproduced_on_om_basis`, `gross_on_price`, `gross_on_total_cost`, `buyer_net_on_price`, `buyer_net_on_total_cost` and `gap_vs_stated`. |
| `master_lease` | `null` for direct leases, or `tenant`, `related_party`, `annual_rent_aed` (a metric), `lease_end`, `cheques`, `reversion_month` and `reversion_date` (first month the units revert to the owner). |
| `expiry_by_quarter` | `depends_on`, `unit`, and `quarters`, one per calendar quarter of the next 12 months, each with `quarter` (for example `2027-Q3`), `expiring_rent_aed` and `share`. |
| `unit_schedule` | Per unit: in-place and reference rent, `rent_vs_market`, `expiry_month`, `market_rent_by_year`, `expected_rent_by_year` and `events` (each expiry with the renewal rule applied). |
| `warnings` | Plain-text data-quality warnings (unit areas not footing to NSA, unverified market data, unstated chiller). |

**Metric:** `{"value": number|null, "unit": str, "depends_on": [{"input": name, "provenance": tag}], "note"?: str}`. **Series:** the same, with `values` (a list, one per year) in place of `value`. Every `depends_on` entry names a key of `inputs`. Provenance tags are `document` (the deal package), `default` (filled from a mandate default because the package lacked it), `mandate` (a firm assumption or rule) and `market` (areas.yaml). Units are `AED`, `AED/yr`, `AED/sqft`, `ratio`, `ratio/yr`, `x` and `units`. A `null` value means undefined (for example IRR when cash flows never change sign, or price per sq ft BUA with no BUA).

**Metrics:**
- **Rent roll:** `unit_count`, `occupancy_by_units`, `occupancy_by_area`, `in_place_rent_aed`, `market_rent_reference_aed`, `over_rent_share_of_income`, `max_expiry_share_quarter`.
- **Year 1:** `potential_rental_income_year1`, `gross_rental_income_year1` (unit-level rent only), `master_lease_income_year1`, `effective_gross_income_year1`, `operating_costs_year1`, `noi_year1`, `opex_ratio_year1`.
- **Pricing:** `price_aed`, `price_per_sqft_nsa`, `price_per_sqft_bua`, `acquisition_costs_aed`, `acquisition_costs_pct_of_price`, `total_cost_aed`, `gross_yield_in_place_on_price`, `going_in_net_yield_on_price`, `going_in_net_yield_on_cost`.
- **Debt:** `loan_aed`, `interest_rate`, `annual_debt_service_aed`, `arrangement_fee_aed`, `equity_aed`, `dscr_year1`, `icr_year1`, `debt_yield_year1`, `breakeven_occupancy_dscr_1`, `economic_occupancy_year1`.
- **Exit:** `exit_yield`, `forward_noi_aed`, `gross_exit_value_aed`, `net_sale_proceeds_aed`, `loan_balance_at_exit_aed`, `exit_gain_levered_aed`.
- **Returns:** `{unlevered,levered}_irr_{pre,post}_tax`, `{unlevered,levered}_equity_multiple_{pre,post}_tax`, `walk_away_price_aed`.

## Modelling conventions

**Timeline.** Year 1 starts at `underwriting.analysis_start` (1 Jan 2027). The model runs monthly for `hold_years + 1` years and sums the months into annual periods, so a mid-year expiry is prorated by month. The extra year supplies the forward NOI for the exit. A lease's roll month is the day after `lease_end`, rounded to the nearest month start: days 1-15 count from that month, day 16 onwards from the next. A lease that has already expired rolls in month 0.

**Market reference rent** per unit = area `market_rent_aed_psf_1br` x unit-type factor x unit area. This as-of level is the basis for `over_rent_share_of_income` and `rent_vs_market`. For leases starting in year *t* it is multiplied by the cumulative house-view path, Π(1 + g₁…g_t), so year 1 already carries the first year's change (-4% for most areas). The mandate gives hold + 1 values (year 6 is the forward-NOI year). A shorter path has its last value repeated, and the `inputs` entry notes this.

**Expiry (expected-value blend).** At each expiry the renewal share `p = renewal_probability` earns the renewal rent from the expiry month. The turnover share `1 - p` earns market rent after `downtime_months_on_turnover` (fractional months are prorated) and pays a leasing fee of `leasing_fee_months_on_turnover` x the new monthly rent in the month of re-letting. The next lease's rent is the blend `p x renewal + (1 - p) x market`. Each lease runs 12 months from its expiry. Renewal rent follows these rules:
- **Under-rented:** rent rises by the RERA band for the gap `(market - current) / market`, using that year's market level. Band upper bounds are inclusive, and the increase is capped at market. Expiries inside the `notice_days_for_change` window after the analysis start (months 0-2) get no increase, because notice could not have been served.
- **Over-rented:** rent resets to market.
- **Notice served:** the first expiry turns over (`p = 0`).
- **Vacant or legal case:** no rent at the start (rent-roll statistics such as occupancy and in-place rent still count a legal-case unit as let, because the tenant is in place). The unit leases up at year-1 market after the downtime, with a leasing fee, and then rolls like any other. Rent under a legal dispute is assumed not collected.

**Operating statement.**
- **Losses:** gross income (rent after downtime, plus other income) bears `structural_vacancy`. Collection loss then applies to what remains, which gives EGI.
- **Management fee:** `property_management_pct_of_egi` of EGI. A stated management fee is recorded but not used.
- **Opex:** stated categories are taken as given (`document`). A missing category uses the mandate default per sq ft of NSA (`default`). A missing category with no default (service charge, marketing) is 0 (`default`).
- **District cooling:** a stated amount is always used. The default applies only if `chiller_landlord_pays` is `true` or unstated.
- **Leasing fees** are an operating cost inside NOI.
- **Growth:** Year 1 uses the stated or default amounts (the T-12 is the Year-1 budget). Opex grows at `opex_growth` and other income at `other_income_growth` from Year 2. Management, leasing fees and VAT follow the income and costs they are charged on.
- **Input VAT:** `input_vat_on_opex_pct` on every cost except the sinking fund (a reserve, not a purchased service). If `opex_includes_vat` is set, VAT applies only to the management and leasing fees.

**Capital.**
- **Loan:** `ltv` x price.
- **Acquisition costs:** DLD 4% plus admin, the trustee fee, and broker fee plus VAT. Together these are `transfer_costs`. The total adds mortgage registration (0.25% of the loan plus AED 290), as the mandate lists it with acquisition costs; yield on total cost uses this total.
- **Debt service:** a level annual annuity at EIBOR + margin over `amortisation_years`, paid in arrears and held flat. The arrangement fee is paid at closing.
- **Equity:** price + total acquisition costs + arrangement fee - loan.
- **Unlevered outlay:** price + transfer costs.
- **Exit:** at the end of year `hold`. Sale price = year hold+1 NOI / (area exit yield + `exit_yield_expansion_bps`), less `selling_costs_pct`; the loan balance is repaid from the proceeds.
- **Tax:** the mandate's simplified model, 9% of the excess over AED 375,000 each year, with no loss carry-forward and no depreciation.
  - Levered taxable income: NOI - interest - arrangement fee / hold years. In the sale year it adds the exit gain: net sale proceeds - (price + total acquisition costs).
  - Unlevered taxable income: NOI, plus a gain measured against price + transfer costs (an unlevered buyer pays no mortgage registration).
  - A loss on sale reduces that year's taxable income.
- **IRR and equity multiple:** IRR uses annual flows, by bisection. Equity multiple = total inflows / total outflows.

**Ratios.**
- **DSCR:** Year-1 NOI / Year-1 debt service (interest and principal).
- **Debt yield:** Year-1 NOI / loan.
- **Interest cover:** Year-1 NOI / Year-1 interest, shown for context.
- **Breakeven occupancy:** the share of Year-1 potential income (every unit let at its scheduled rent all year, plus other income) at which NOI equals debt service. Management fee and its VAT vary with income; everything else is fixed.

**Walk-away price.** The highest multiple of AED 10,000 at which the pre-tax levered IRR is at least `target_levered_irr` and Year-1 DSCR is at least `min_dscr_year1`. The loan scales with price, and NOI does not depend on price. The search brackets the boundary by doubling, then bisects on the AED 10,000 grid. It does not depend on the asking price.

**Sensitivity.** The grid is exit yield -50 / 0 / +50 bps against market rent -5% / 0 / +5%. The rent shift scales every year's market level, so it reaches renewals, re-lets, RERA tests and the exit NOI; in-place rents are unchanged until they roll.

**Expiry concentration.** The largest share of in-place rent whose roll month falls in a single calendar quarter of the next 12 months. Leases already expired roll in month 0, which is in the first quarter. Leases rolling later than 12 months out count in no quarter.

**Master lease.** When `master_lease` is given:
- **Income:** the master rent, flat and prorated by month, until the roll month of `lease_end`. It bears collection loss but no structural vacancy, since one tenant pays for the building.
- **Reversion:** every unit turns over. Each is vacant from the reversion month, lets at that year's market rent after the downtime with a leasing fee, and then rolls annually with the renewal blend. With no rent roll, the whole NSA is modelled as 1BR-equivalent space after reversion, with a warning.
- **Opex:** stated lines apply throughout, as the owner's own statement under the lease. Mandate defaults for missing lines apply only from reversion, because the operator bears running costs during the lease.
- **Management fee:** remains a share of EGI.
- **Rent-roll statistics:** occupancy is 100%, and in-place rent is the master rent. All income expires at `lease_end`. It counts as over-rented if the master rent exceeds the market reference rent of all units.

**OM yield check** (`recompute_stated_yield`). It divides the OM's income by the OM's own denominator (asking price, or price plus acquisition costs). An unstated denominator is assumed to be the asking price and flagged as assumed. The result is compared with the printed figure (tolerance 0.05 points), and the buyer's figure is reported as Year-1 NOI / (price + acquisition costs).
