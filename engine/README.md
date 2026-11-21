# Underwriting engine

Deterministic underwriting for the Dubai residential-building deal screen. The engine is pure Python (standard library plus PyYAML for the loaders). It makes no LLM calls, uses no network and has no randomness: the same inputs always give the same output. Every rule and number comes from `data/mandate.yaml` and `data/market/areas.yaml`, which are passed in as dicts. A few modelling conventions are engine constants, listed under "Engine constants" below.

The screen decides on **unlevered, pre-tax** value. Debt is sized to cover, not to lift returns, so levered returns are secondary outputs. Post-tax returns are indicative only.

```python
from engine import underwrite, mandate_fit, recompute_stated_yield, load_mandate, load_market

mandate, market = load_mandate(), load_market()          # default paths: data/...
result = underwrite(deal_inputs, mandate, market)        # dict, JSON-serialisable
fit = mandate_fit(deal_facts, result, mandate)           # Pursue / Needs work / Decline
```

```
python -m engine tests/engine/fixtures/jvc_60_units.json          # readable summary
python -m engine tests/engine/fixtures/jvc_60_units.json --json   # full result + mandate fit
python -m pytest tests/engine                                      # tests
```

The CLI accepts a plain `deal_inputs` file, or `{"deal_inputs": {...}, "deal_facts": {...}}` to include a full mandate fit.

## Changes in v2 (engine 2.0.0)

This section lists every change a caller must handle. The rest of this README describes v2 as it stands.

### Mandate keys read

| v1 | v2 |
|---|---|
| `underwriting.debt.ltv` | `underwriting.debt.max_ltv`, plus `sizing_dscr`. `amortisation_years_sensitivity` and `rate_note` are read if present. |
| `buy_box.hard.min_dscr_year1` | No longer required. If a mandate has it, `mandate_fit` still tests it. |
| `buy_box.soft.target_levered_irr`, `target_equity_multiple` | Replaced by `target_unlevered_irr` and `target_unlevered_equity_multiple`. |
| (none) | `buy_box.soft.over_rent_threshold` (a parameter of the over-rent test, not a test of its own). |
| (none) | `underwriting.market_view.exit_yield_rule` (text), `exit_age_premium_bps` and `exit_age_premium_from_years`. |
| `verdict_rules.pass_if_any_hard_fails` | `verdict_rules.decline_if_any_hard_fails` |

Registry names in `result.inputs` follow the mandate paths. `mandate.underwriting.debt.ltv` is now `mandate.underwriting.debt.max_ltv`. New entries: `...debt.sizing_dscr`, `...market_view.exit_age_premium_bps`, `...exit_age_premium_from_years`, `buy_box.soft.target_unlevered_irr` and `buy_box.soft.over_rent_threshold`.

### `deal_inputs`: new optional fields (the rest are unchanged)

| Field | Type | Effect |
|---|---|---|
| `completion_year` | integer year, no later than the analysis start year | Building age. It drives the exit age premium and scales a defaulted sinking fund. If unknown, the premium is applied, the sinking fund takes the highest age band, and both raise warnings. |
| `collection_loss_override` | ratio in [0, 1) | Replaces the mandate's `collection_loss`, for example with the observed gap between collections and rent-roll rent. Provenance `document`. |
| `security_deposits_aed` | number >= 0 | Tenant deposits the buyer assumes. Reported as a closing credit; not in NOI, cost or returns. |

The meaning of some existing fields changes:
- **`units[].status = "legal_case"`:** the unit is not occupied, carries no in-place rent and earns nothing until resolved. It then re-lets at the reference after 6 months, with a leasing fee.
- **`master_lease` with `units`:** at reversion the sub-tenancies novate instead of all turning over (see "Master lease").
- **`opex_aed.marketing_leasing`, when stated:** now offsets modelled turnover leasing fees in the same year.

### `underwrite` result

**Added at the top level:**
- `decision_basis`: always `"unlevered, pre-tax"`.
- `headline`: the metric names to lead with, in order.
- `exit`: the exit yield and its components.
- `debt`: sizing, the binding constraint, the rate note and the amortisation sensitivity.
- `closing_adjustments`: security deposits.

**Renamed** ("market reference" becomes "screen reference", which is a proxy and never the RERA index):

| v1 | v2 |
|---|---|
| `metrics.market_rent_reference_aed` | `metrics.screen_reference_rent_aed` |
| `unit_schedule.units[].market_rent_reference_aed` | `screen_reference_rent_aed` |
| `unit_schedule.units[].rent_vs_market` | `rent_vs_reference` |
| `unit_schedule.units[].market_rent_by_year` | `reference_rent_by_year` |
| `events[].market_rent` | `events[].reference_rent` |
| `events[].blended_rent` | `events[].expected_rent_after` |
| renewal rule `over_rented_reset_to_market` | `over_rented_reset_to_reference` |
| renewal rule `at_market` | `at_reference` |

**Added metrics:**
- `entry_yield_on_price` (the same value as `going_in_net_yield_on_price`)
- `ltv` (the actual loan / price)
- `over_rent_excess_at_expiry_aed`
- `commercial_income_share_year1`
- `input_vat_recovered_year1`
- `security_deposits_aed`

`unlevered_irr_post_tax`, `unlevered_equity_multiple_post_tax`, `levered_irr_post_tax` and `levered_equity_multiple_post_tax` now carry `"indicative": true`, with the mandate's `tax.model` text in `note`.

**Changed meaning:**
- **`loan_aed`:** the lower of max LTV x price and what Year-1 NOI covers at `sizing_dscr`. It was LTV x price. As a result `dscr_year1` >= `sizing_dscr`.
- **`exit_yield`:** max(area house view, entry yield on price) + expansion + age premium. It was area + expansion.
- **`occupancy_by_units`, `occupancy_by_area`, `in_place_rent_aed`:** exclude legal-case units.
- **`over_rent_share_of_income`:** counts only units more than `over_rent_threshold` above the reference.
- **`cash_flow.lines.input_vat`:** the irrecoverable VAT cost, net of recovery on commercial income.
- **`cash_flow.lines.leasing_fees`:** modelled fees above a stated `marketing_leasing` line.

**Added cash-flow lines:** `leasing_fees_modelled`, `commercial_income_share` (a ratio, not AED), `input_vat_gross` and `input_vat_recovered`.

**`walk_away`:**
- The target is now `target_unlevered_irr`, and `binding_constraint` is always `"unlevered_irr"`.
- Removed: `target_levered_irr`, `dscr_floor`, `levered_irr_one_step_above` and `dscr_one_step_above`.
- Added: `target_unlevered_irr`, `unlevered_irr_at_price`, `unlevered_irr_one_step_above`, `exit_yield_at_price` and `loan_at_price`. `dscr_at_price` and `levered_irr_at_price` are kept, with debt re-sized at that price.
- Added the walk-away sensitivity: `sensitivity.cases` (four cases), `most_sensitive_assumption` (`exit_yield` or `reference_rent_path`), `most_sensitive_label` and `largest_swing_aed`.

**Other result changes:**
- **`sensitivity.cells[]`:** adds `unlevered_equity_multiple_pre_tax`, and debt is re-sized in each cell.
- **`master_lease`:** adds `reversion_basis` (`novation` or `all_turnover`).
- **`unit_schedule.units[].events[]`:** an expiry event adds `tenant_states` (one record per possible tenant: `weight`, `current_rent`, `renewal_rent`, `renewal_rule`). `renewal_rule` is null when there is more than one state, and `renewal_rent` is then the weighted average.
- **Warnings:** text says "Screen reference rent" where it said "Market reference rent".

### `mandate_fit` result

- **Verdict values:** `Pursue`, `Needs work` and `Decline`. `Decline` replaces `Pass`.
- **`blocked_on`:** a list of the names of hard tests whose status is `unknown`, for example `["title"]`. An unknown hard test now makes the verdict `Needs work` (unless another hard test fails) and is **not** counted in `soft_fails`.
- **`stop_reason`:** null, or (when a hard test fails) a sentence such as "Declined on hard filter(s): areas. Returns are shown for reference but are not decisive."
- **`tests[].decisive`:** `false` for every soft test when a hard test fails; `true` otherwise.
- **Soft tests:** `target_levered_irr` and `target_equity_multiple` are replaced by `target_unlevered_irr` (on `unlevered_irr_pre_tax`) and `target_unlevered_equity_multiple` (on `unlevered_equity_multiple_pre_tax`). `min_dscr_year1` is tested only if the mandate has it.
- **Unknown reason text:** "...unknown; blocks the verdict until known." for hard tests, and "...unknown; counts as a soft miss." for soft tests.

## `deal_inputs` schema

All money is in AED, all areas in sq ft, and every rate is a ratio (0.05 means 5%). Fields not listed here are rejected.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `deal_id` | str | no | Echoed back in the result. |
| `price_aed` | number > 0 | **yes** | Price being underwritten (usually the asking price). |
| `area` | str | **yes** | Must match a key of `areas` in areas.yaml, ignoring case, spaces, `-` and `_` (for example `Al Barsha South`). An unknown area raises `MarketDataError`. |
| `nsa_sqft` | number > 0 | **yes** | Net saleable/leasable area. Opex defaults are priced on it. |
| `bua_sqft` | number > 0 or null | no | Built-up area. Used only for price per sq ft BUA. |
| `units` | list | **yes**, unless `master_lease` is given | Rent-roll rows; see below. |
| `opex_aed` | dict | no | Annual operating costs by chart-of-accounts category (below). A missing key or `null` means not stated; `0` means stated as zero. |
| `opex_includes_vat` | bool | no, default `false` | Set `true` if the stated opex already includes VAT. Input VAT is then added only to the costs the engine computes (management and leasing fees). |
| `other_income_aed` | number | no, default 0 | Annual non-rent income (parking and similar), Year-1 amount. Grows at `other_income_growth` from Year 2. |
| `chiller_landlord_pays` | bool or null | no, default `null` | `true` means a chiller-free building where the landlord pays cooling. `null` (unstated) applies the cooling default conservatively, with a warning. |
| `completion_year` | integer or null | no, but recommended | Year of completion; see "Building age". |
| `collection_loss_override` | ratio or null | no | Replaces the mandate's collection loss. |
| `security_deposits_aed` | number or null | no | Total tenant deposits; see "Closing adjustments". |
| `rent_roll_date` | `YYYY-MM-DD` | no, but recommended | Date of the rent roll. The expiry-concentration windows start here; without it they start at `analysis_start`, with a warning. |
| `om_stated` | dict | no | The OM's own income and yield, for the yield check (below). |
| `master_lease` | dict or null | no | A lease of the whole building to one tenant (below). |
| `provenance` | dict | no | Overrides the default `document` tag for a field, for example `{"price_aed": "default"}` or `{"opex_aed.insurance": "default"}`. Values must be `document`, `default`, `mandate` or `market`. |

**`units[]`** (field names match the rent-roll extraction fields in DESIGN.md):

| Field | Type | Required | Meaning |
|---|---|---|---|
| `unit` | str | no | Unit number; defaults to the row position. |
| `unit_type` | str | **yes** | A key of `unit_type_factors`: `studio`, `1br`, `2br`, `3br` or `retail`. Case, spaces, `-` and `_` are ignored, so `"1 BR"` is accepted. `retail` units are commercial: they set the share of input VAT that is recoverable. |
| `area_sqft` | number > 0 | **yes** | Unit area. |
| `status` | str | **yes** | `occupied`, `under_renewal`, `notice_served`, `vacant` or `legal_case`. |
| `annual_rent_aed` | number or null | for occupied, under-renewal and notice-served units (direct leases) | Contract rent. It is ignored for vacant and legal-case units, so a rent roll that carries asking rent on vacant units cannot inflate income. |
| `lease_end` | `YYYY-MM-DD` or null | no | Lease expiry. If an occupied unit has none, it rolls at the analysis start and a warning is raised. |

**`master_lease`:**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `tenant` | str or null | no | Master tenant name. |
| `related_party` | bool or null | no | `true` if the master tenant is related to the seller; `null` means unknown. `mandate_fit` reads this flag. |
| `annual_rent_aed` | number > 0 | **yes** | Master-lease rent, held flat until expiry. |
| `lease_end` | `YYYY-MM-DD` | **yes** | Master-lease expiry, rounded to a roll month like any lease. |
| `cheques` | number or null | no | Number of cheques a year. Recorded only. |

With a master lease, the rent roll holds the operator's sub-tenancies. Their rents and lease ends are used only from reversion (see "Master lease"), so they are not required.

**`opex_aed` categories:** `service_charge`, `district_cooling`, `utilities_common`, `property_management`, `maintenance_repairs`, `insurance`, `security_cleaning`, `marketing_leasing`, `admin_other`, `sinking_fund`.

**`om_stated`:** `{"annual_rent_aed": number|null, "net_income_aed": number|null, "yield": ratio|null, "yield_basis": {"measure": "gross"|"net"|"unstated", "on": "asking_price"|"total_cost"|"unstated"}}`. A string such as `"gross_on_price"` is also accepted for `yield_basis`. The yield is reproduced from `net_income_aed` when the basis is net and that field is given, and from `annual_rent_aed` otherwise.

## `mandate_fit(deal_facts, uw_result, mandate)`

**`deal_facts`:** `asset_type`, `area`, `title_type`, `unit_count`, `price_aed`, `completion_year`, `lease_structure` and `master_lease_related_party`.
- `asset_type` is for example `residential_building` or `mixed_use_residential`; `title_type` is for example `freehold_single_title`; `lease_structure` is `direct_leases` or `master_lease`.
- A missing or `null` value is unknown.
- `unit_count` and `price_aed` fall back to the underwriting result when absent.
- The related-party test combines three sources, and any `true` wins:
  - `master_lease_related_party`;
  - the `related_party` flag of the underwriting result's `master_lease`;
  - `lease_structure: direct_leases`, which means no master lease (a pass).

  With none of these the test is unknown.
- `uw_result` can be `None` (the deal could not be underwritten, for example out-of-area). Every engine-based test is then unknown.

It returns `{"verdict", "reason", "hard_fails", "soft_fails", "unknown", "blocked_on", "stop_reason", "tests"}`. `tests` has one record per filter in `buy_box` (`over_rent_threshold` is a parameter, not a filter):

```json
{"name": "target_unlevered_irr", "kind": "soft", "threshold": 0.075, "actual": 0.0516,
 "passed": false, "status": "fail", "source": "engine", "decisive": true,
 "reason": "Unlevered IRR (pre-tax) 5.16% misses the at least 7.50% requirement."}
```

`status` is `pass`, `fail` or `unknown`, and `passed` is `true`, `false` or `null`. `source` is `deal_facts` or `engine`.

**Verdict**, from `verdict_rules`, in order:
1. Any hard test fails: **Decline**. `stop_reason` names the failed tests, and every soft test is marked `decisive: false`; returns are still computed and reported.
2. Otherwise, any hard test is unknown: **Needs work**, with those tests in `blocked_on`. Unknown hard tests do not count as soft misses.
3. Otherwise, soft misses (soft fails plus soft unknowns) number at most `pursue_if_soft_fails_at_most`: **Pursue**.
4. Otherwise: **Needs work**.

`hard_fails` counts failed hard tests, `soft_fails` counts soft fails plus soft unknowns, and `unknown` counts every unknown test. A filter in the mandate with no implemented test raises `ValueError`, so the code and the mandate cannot drift apart.

The engine metrics tested are `going_in_net_yield_on_cost`, `unlevered_irr_pre_tax`, `unlevered_equity_multiple_pre_tax`, `occupancy_by_units`, `max_expiry_share_quarter`, `over_rent_share_of_income` and, if the mandate has `min_dscr_year1`, `dscr_year1`.

## Result shape

| Key | Contents |
|---|---|
| `engine_version`, `deal_id`, `analysis_start`, `hold_years` | Run identification. |
| `decision_basis` | `"unlevered, pre-tax"`. |
| `headline` | Metric names to lead with: `unlevered_irr_pre_tax`, `unlevered_equity_multiple_pre_tax`, `entry_yield_on_price`, `exit_yield`, `going_in_net_yield_on_cost`, `noi_year1`, `walk_away_price_aed`. |
| `inputs` | Every input the run used, by dotted name: `{"value", "unit", "provenance", "note"?}`. |
| `metrics` | Numbers, each a **metric** (below), listed under "Metrics". |
| `exit` | `rule` (mandate text) and `entry_yield_on_price`, `area_house_view` and `exit_yield` as metrics. Also `base_source` (`area_house_view` or `entry_yield`, whichever is higher), `expansion_bps`, `age_premium_bps` (applied), `age_premium_rule` (`{premium_bps, from_years}`), `building_age_at_exit` (null if unknown), and `summary` ("Buy at X (Year-1 NOI on price); exit at Y = max(area A, entry X) + 25 bps expansion + 0 bps age premium."). |
| `debt` | `sizing_constraint` (`ltv` or `dscr`); `max_ltv`, `sizing_dscr`, `loan_at_max_ltv_aed`, `loan_at_sizing_dscr_aed` and `loan_constant` as metrics; `amortisation_years`; `rate_note` (mandate text); and `amortisation_sensitivity` (`depends_on`, `cases`). Each case has `amortisation_years`, `base`, `loan_aed`, `sizing_constraint`, `annual_debt_service_aed`, `dscr_year1`, `levered_irr_pre_tax` and `levered_equity_multiple_pre_tax`, at the base term and at `amortisation_years_sensitivity`. |
| `acquisition_costs` | Metrics for `dld_transfer_fee`, `dld_admin`, `trustee_fee`, `broker_fee`, `broker_fee_vat`, `mortgage_registration`, `transfer_costs` and `total`. |
| `closing_adjustments` | `security_deposits_aed` (a metric; value null if not stated) and `note`. |
| `cash_flow` | Years 1 to hold+1: `years`, `period_start`, `period_end`, `in_hold`, `lines` and `opex_by_category`. Each line is a **series**, listed under "Cash-flow lines" below. |
| `debt_schedule` | Years 1 to hold: `opening_balance`, `interest`, `principal`, `debt_service`, `closing_balance`. |
| `returns_cash_flows` | Years 0 to hold: `unlevered_pre_tax`, `unlevered_post_tax`, `levered_pre_tax`, `levered_post_tax`, `tax_unlevered`, `tax_levered`. Post-tax and tax lines are indicative. |
| `sensitivity` | `rent_shifts`, `exit_yield_shifts_bps`, `note`, `units`, `depends_on` and nine `cells`. Each cell has `rent_shift`, `exit_yield_shift_bps`, `exit_yield`, `noi_year1`, `unlevered_irr_pre_tax`, `unlevered_equity_multiple_pre_tax`, `dscr_year1`, `levered_irr_pre_tax` and `levered_equity_multiple_pre_tax`. |
| `walk_away` | `price_aed` (a metric; null with a `reason` if no price works). Also `binding_constraint` (`unlevered_irr`), `target_unlevered_irr`, `unlevered_irr_at_price`, `unlevered_irr_one_step_above`, `exit_yield_at_price`, `discount_to_asking`, `going_in_net_yield_on_cost_at_price`, `loan_at_price`, `dscr_at_price` and `levered_irr_at_price` (all metrics). Then `sensitivity` (`depends_on`, `unit`, and `cases`, each with `assumption`, `case`, `shift`, `price_aed` and `delta_aed`), `most_sensitive_assumption`, `most_sensitive_label` and `largest_swing_aed`. |
| `om_yield_check` | `null`, or `summary` ("The OM says X; on a buyer's basis it is Y"), `om_basis`, `reproduces_stated`, and metrics `stated_yield`, `reproduced_on_om_basis`, `stated_income_on_price`, `stated_income_on_total_cost`, `buyer_net_on_price`, `buyer_net_on_total_cost` and `gap_vs_stated`. |
| `master_lease` | `null` for direct leases, or `tenant`, `related_party`, `annual_rent_aed` (a metric), `lease_end`, `cheques`, `reversion_month`, `reversion_date`, `reversion_basis` (`novation` or `all_turnover`) and `note`. |
| `expiry_windows` | `depends_on`, `unit`, `basis_date` (the rent roll date, or the analysis start if none was given), and `windows`: four consecutive 3-month windows, each with `window` (1-4), `start`, `end` (inclusive), `expiring_rent_aed` and `share`. |
| `unit_schedule` | `depends_on`, `note` and `units`. Each unit has `unit`, `unit_type`, `area_sqft`, `status`, `in_place_rent_aed`, `screen_reference_rent_aed`, `rent_vs_reference`, `expiry_month`, `reference_rent_by_year`, `expected_rent_by_year` (net of downtime) and `events`. A `lease_up` event has `month`, `reference_rent`, `new_rent` and `downtime_months`. An `expiry` event has `month`, `reference_rent`, `renewal_probability`, `current_rent`, `renewal_rent`, `renewal_rule`, `tenant_states`, `turnover_rent` and `expected_rent_after`. |
| `warnings` | Plain-text data-quality warnings (unit areas not footing to NSA, unverified reference data, unstated chiller, unknown completion year, missing rent roll date). |

**Metric:** `{"value": number|null, "unit": str, "depends_on": [{"input": name, "provenance": tag}], "note"?: str, "indicative"?: true}`. **Series:** the same, with `values` (one per year) in place of `value`. Every `depends_on` entry names a key of `inputs`. Provenance tags are `document` (the deal package), `default` (filled from a mandate default because the package lacked it), `mandate` (a firm assumption or rule) and `market` (areas.yaml). Units are `AED`, `AED/yr`, `AED/sqft`, `ratio`, `ratio/yr`, `x` and `units`. A `null` value means undefined (for example IRR when cash flows never change sign, or price per sq ft BUA with no BUA).

**Metrics:**
- **Decision (unlevered, pre-tax):** `unlevered_irr_pre_tax`, `unlevered_equity_multiple_pre_tax`, `entry_yield_on_price`, `exit_yield`.
- **Rent roll:** `unit_count`, `occupancy_by_units`, `occupancy_by_area`, `in_place_rent_aed`, `screen_reference_rent_aed`, `over_rent_share_of_income`, `over_rent_excess_at_expiry_aed`, `max_expiry_share_quarter`.
- **Year 1:** `potential_rental_income_year1`, `gross_rental_income_year1` (unit-level rent only), `master_lease_income_year1`, `effective_gross_income_year1`, `operating_costs_year1`, `noi_year1`, `opex_ratio_year1`, `commercial_income_share_year1`, `input_vat_recovered_year1`.
- **Pricing:** `price_aed`, `price_per_sqft_nsa`, `price_per_sqft_bua`, `acquisition_costs_aed`, `acquisition_costs_pct_of_price`, `total_cost_aed`, `gross_yield_in_place_on_price`, `going_in_net_yield_on_price`, `going_in_net_yield_on_cost`, `security_deposits_aed`.
- **Debt (secondary):** `loan_aed`, `ltv`, `interest_rate` (its `note` is the mandate `rate_note`), `annual_debt_service_aed`, `arrangement_fee_aed`, `equity_aed`, `dscr_year1`, `icr_year1`, `debt_yield_year1`, `breakeven_occupancy_dscr_1`, `economic_occupancy_year1`.
- **Exit:** `forward_noi_aed`, `gross_exit_value_aed`, `net_sale_proceeds_aed`, `loan_balance_at_exit_aed`, `exit_gain_levered_aed`.
- **Secondary returns:** `levered_irr_pre_tax`, `levered_equity_multiple_pre_tax`; indicative: `unlevered_irr_post_tax`, `unlevered_equity_multiple_post_tax`, `levered_irr_post_tax`, `levered_equity_multiple_post_tax`.
- **Walk-away:** `walk_away_price_aed` (the same metric as `walk_away.price_aed`).

**Cash-flow lines:**
- **Income:** `potential_rental_income` (includes master-lease rent), `downtime_loss`, `gross_rental_income`, `master_lease_income`, `other_income`, `gross_income`.
- **Losses:** `vacancy_allowance`, `structural_vacancy` (the top-up), `collection_loss`, `effective_gross_income`.
- **Costs:** `management_fee`, `operating_expenses`, `leasing_fees_modelled`, `leasing_fees` (beyond a stated marketing/leasing line).
- **VAT:** `commercial_income_share` (a ratio), `input_vat_gross`, `input_vat_recovered`, `input_vat` (the cost in NOI).
- **Totals:** `total_operating_costs`, `noi`.

## Modelling conventions

**Timeline.** Year 1 starts at `underwriting.analysis_start` (1 Jan 2027). The model runs monthly for `hold_years + 1` years and sums the months into annual periods, so a mid-year expiry is prorated by month. The extra year supplies the forward NOI for the exit. A lease's roll month is the day after `lease_end`, rounded to the nearest month start: days 1-15 count from that month, day 16 onwards from the next. A lease that has already expired rolls in month 0.

**Screen reference rent** per unit = area `market_rent_aed_psf_1br` x unit-type factor x unit area. It stands in for the RERA Smart Rental Index, which has no bulk download. It is a proxy, never "the RERA index", and the screen makes no RERA claim about a specific building. The as-of level is the basis for over-rent tests and `rent_vs_reference`. For leases starting in year *t* it is multiplied by the cumulative house-view path, Π(1 + g₁…g_t), so year 1 already carries the first year's change. The mandate gives hold + 1 values (year 6 is the forward-NOI year); a shorter path has its last value repeated.

**Renewal and turnover (expected value).** Each unit carries a small set of possible tenants in place, each with a probability weight and its own rent. At each expiry every one of them renews with probability `p = renewal_probability` or turns over with `1 - p`:
- **Renewal**, from the renewing tenant's **own** rent:
  - *Below the reference:* the rent rises by the RERA band for its own gap `(reference - rent) / reference`, using that year's reference level, capped at the reference. Band upper bounds are inclusive. Expiries inside the `notice_days_for_change` window after the analysis start (months 0-2) get no increase, because notice could not have been served. The window blocks increases only: an over-rented unit expiring in it is still reset down to the reference.
  - *Above the reference:* the rent resets to the reference at renewal.
- **Turnover:** re-lets at the reference, uncapped, after `downtime_months_on_turnover` (fractional months prorated), with a leasing fee of `leasing_fee_months_on_turnover` x the new monthly rent, booked in the month after expiry (expiry month + floor(downtime)).
- Expected rent is the probability-weighted sum. States with equal rent merge, so a unit carries at most one state per past expiry. Each lease runs 12 months from its expiry. Because each renewing tenant's band is set from its own rent, a renewed tenant 11% below the reference still gets its 5% increase. A blended expected rent might fall under 10% and wrongly get none.
- **Notice served:** the first expiry turns over (`p = 0`).
- **Vacant:** leases up at the year-1 reference after the downtime, with a leasing fee, then rolls like any other.
- **Legal case:** not occupied and no rent until resolved. The case is assumed resolved after `LEGAL_CASE_RESOLUTION_MONTHS` (6) months; the unit then re-lets at the reference with a leasing fee and rolls like any other.

**Operating statement.**
- **Losses:** `structural_vacancy` is a general vacancy allowance that already includes the modelled turnover, lease-up and legal-case downtime, so the two are not stacked.
  - The allowance is `structural_vacancy` x (unit rent after downtime + other income). A master lease is excluded.
  - The deduction is only the top-up: the `structural_vacancy` line = max(0, allowance - `downtime_loss`), each year.
  - Collection loss (`collection_loss`, or `collection_loss_override` if given) then applies to gross income less the top-up, which gives EGI.
- **Management fee:** `property_management_pct_of_egi` of EGI. A stated management fee is recorded but not used.
- **Opex:**
  - Stated categories are taken as given (`document`).
  - A missing category uses the mandate default per sq ft of NSA (`default`); a missing category with no default (service charge, marketing) is 0 (`default`).
  - A defaulted sinking fund is scaled by building age (see "Building age"); a stated one is used as stated.
- **District cooling:** a stated amount is always used. The default applies only if `chiller_landlord_pays` is `true` or unstated.
- **Leasing costs, without double counting:** the engine models turnover leasing fees. If the statement states `marketing_leasing`, that line covers the modelled fees up to its amount each year. Only the excess, max(0, modelled - stated), is added as `leasing_fees`. Total leasing cost in a year is therefore the larger of the two. If `marketing_leasing` is not stated, the modelled fees apply in full.
- **Growth:** Year 1 uses the stated or default amounts (the T-12 is the Year-1 budget). Opex grows at `opex_growth` and other income at `other_income_growth` from Year 2. Management, leasing fees and VAT follow the income and costs they are charged on.
- **Input VAT:**
  - **Base:** `input_vat_on_opex_pct` on every cost (management fee, leasing fees and opex lines) except the sinking fund, a reserve rather than a purchased service. If `opex_includes_vat` is set, VAT is added only to the management and leasing fees.
  - **Recovery:** residential rent is VAT-exempt, so its share of input VAT is a cost. Rent from `retail` units carries output VAT, so input VAT is recoverable in proportion to the commercial share of rent: `input_vat_recovered = input_vat_gross x retail rent / (unit rent + master rent)`, each year.
  - **What is excluded:** master-lease rent counts as residential, and other income is left out of the ratio.

**Building age.** Age at the analysis start = start year - `completion_year`; age at exit = start year + hold - `completion_year` (2032 - completion year for the current mandate).
- **Sinking fund (defaulted only):** the mandate default per sq ft is scaled by `SINKING_FUND_AGE_MULTIPLIERS`: x1.0 under 10 years, x1.5 for 10-19 years, x2.0 for 20 years and over, by age at the start.
- **Exit:** `exit_age_premium_bps` is added if the age at exit is at least `exit_age_premium_from_years`.
- **Unknown age:** the conservative case applies (x2.0 and the premium), with a warning for each.

**Capital.**
- **Loan (sized to cover):** `loan = min(max_ltv x price, Year-1 NOI / (sizing_dscr x loan constant))`. The loan constant is the level annual payment per AED over `amortisation_years` at 3M EIBOR + margin. `debt.sizing_constraint` says which limit binds (`ltv` if max LTV is the lower), so Year-1 DSCR is at least `sizing_dscr`. The rate is held flat and unhedged; the mandate's `rate_note` is carried into `debt.rate_note` and the `interest_rate` note. `debt.amortisation_sensitivity` repeats the sizing and levered returns at `amortisation_years_sensitivity`.
- **Acquisition costs:** DLD 4% plus admin, the trustee fee, and broker fee plus VAT; together these are `transfer_costs`. The total adds mortgage registration (0.25% of the loan plus AED 290), as the mandate lists it with acquisition costs; yield on total cost uses this total. Because the loan depends on NOI, so does mortgage registration.
- **Debt service:** a level annual annuity, paid in arrears. The arrangement fee is paid at closing.
- **Equity:** price + total acquisition costs + arrangement fee - loan.
- **Unlevered outlay:** price + transfer costs.
- **Exit:** at the end of year `hold`.
  - Exit yield = max(area house view, entry yield on price) + `exit_yield_expansion_bps` + age premium (the mandate's `exit_yield_rule`). The entry yield is Year-1 NOI / price, so the exit is never below where the deal was bought.
  - Sale price = year hold+1 NOI / exit yield, less `selling_costs_pct`; the loan balance is repaid from the proceeds.
- **Tax (indicative only):** the mandate's simplified model, 9% of the excess over AED 375,000 each year, with no loss carry-forward and no depreciation. The holding vehicle is ignored.
  - Levered taxable income: NOI - interest - arrangement fee / hold years. In the sale year it adds the exit gain: net sale proceeds - (price + total acquisition costs).
  - Unlevered taxable income: NOI, plus a gain measured against price + transfer costs.
  - A loss on sale reduces that year's taxable income. Post-tax metrics are marked `indicative: true`, and the screen decides on pre-tax returns.
- **IRR and equity multiple:** IRR uses annual flows, by bisection. Equity multiple = total inflows / total outflows.

**Ratios.**
- **DSCR:** Year-1 NOI / Year-1 debt service (interest and principal).
- **Debt yield:** Year-1 NOI / loan.
- **Interest cover:** Year-1 NOI / Year-1 interest.
- **Breakeven occupancy:** the share of Year-1 potential income at which NOI equals debt service. Potential income is every unit let at its scheduled rent all year, plus other income. Management fee and its irrecoverable VAT vary with income; everything else is fixed. Occupancy is the variable here, so the vacancy allowance and downtime do not enter it.

**Walk-away price.** The highest multiple of AED 10,000 at which the pre-tax **unlevered** IRR is at least `target_unlevered_irr`.
- **What moves with price:** the exit yield, through the entry yield. Debt is re-sized at each price for the levered figures reported there, but does not affect the unlevered test.
- **Search:** brackets the boundary by doubling, then bisects on the AED 10,000 grid. The result does not depend on the asking price.
- **Sensitivity:** the walk-away is re-solved under exit yield -50 and +50 bps and under the reference rent path -5% and +5%. `most_sensitive_assumption` names the assumption whose larger absolute change is biggest, and `largest_swing_aed` gives that change.

**Sensitivity grid.** Exit yield -50 / 0 / +50 bps against reference rent -5% / 0 / +5%.
- **Rent shift:** scales every year's reference level, so it reaches renewals, re-lets, RERA tests, the entry yield and the exit NOI. In-place rents are unchanged until they roll.
- **Exit shift:** added on top of the exit yield rule.
- **Debt:** re-sized in each cell.

**Over-rent.** A unit is over-rented only if its rent exceeds its screen reference rent by more than `over_rent_threshold` (10%); the margin allows for the reference being a proxy.
- `over_rent_share_of_income` is the in-place rent of those units / in-place rent.
- `over_rent_excess_at_expiry_aed` is the rent above the reference on those units: the cut if each resets to the reference **at its next renewal or expiry**, not today.
- Under a master lease, the master rent is compared with the reference rent of all units.

**Expiry concentration** (`max_expiry_share_quarter`, tested against `max_lease_expiry_share_in_any_quarter`). The largest share of in-place rent whose `lease_end` falls in one of four consecutive 3-month windows starting at `rent_roll_date`.
- The first window is [rent roll date, +3 months), and so on to 12 months.
- A lease that had already expired at the rent roll date, or an occupied unit with no lease end, counts in the first window.
- A lease ending 12 months or more after the rent roll date counts in no window.
- Under a master lease the whole master rent counts at its `lease_end`.
- Without `rent_roll_date`, the windows start at `analysis_start` and the result carries a warning.

**Master lease.** When `master_lease` is given:
- **Income:** the master rent, flat and prorated by month, until the roll month of `lease_end`. It bears collection loss but no structural vacancy, since one tenant pays for the building.
- **Reversion with unit data (`reversion_basis: novation`):** the sub-tenancies novate to the owner.
  - A let unit with a stated sub-let rent keeps paying it from the reversion month until its own lease end, then rolls normally. A sub-lease that ended before reversion rolls at reversion.
  - A vacant unit, or a let unit with no stated rent, leases up at the reference after the downtime; the second case raises a warning.
  - A legal-case unit re-lets after the 6-month resolution period.
- **Reversion without unit data (`all_turnover`):** every unit is assumed to turn over. The whole NSA is modelled as 1BR-equivalent space, vacant from reversion, and a warning is raised.
- **Opex:** stated lines apply throughout, as the owner's own statement under the lease. Mandate defaults for missing lines apply only from reversion, because the operator bears running costs during the lease.
- **Rent-roll statistics:** occupancy is 100%, and in-place rent is the master rent. All income expires at `lease_end`.

**Closing adjustments.** `security_deposits_aed` is a liability the buyer assumes; the seller credits it at closing. It is reported in `closing_adjustments` and `metrics.security_deposits_aed` only, and does not enter NOI, cost or returns.

**OM yield check** (`recompute_stated_yield`). It divides the OM's income by the OM's own denominator (asking price, or price plus acquisition costs).
- **Unstated denominator:** assumed to be the asking price, and flagged as assumed.
- **Comparison:** the result is compared with the printed figure, with a tolerance of 0.05 points.
- **Buyer's figure:** Year-1 NOI / (price + acquisition costs).
- **Standalone use:** called with a `mandate` and no acquisition costs, the helper sizes the loan as the engine does: min(max LTV x price, NOI / (sizing DSCR x constant)), or max LTV if no NOI is given.

## Engine constants

These are modelling conventions rather than market numbers. Move them into the mandate if the firm wants to own them.

| Constant | Value | Where |
|---|---|---|
| `LEGAL_CASE_RESOLUTION_MONTHS` | 6 | `engine/inputs.py`: months a legal-case unit earns nothing before re-letting. |
| `SINKING_FUND_AGE_MULTIPLIERS` | x1.0 under 10 years, x1.5 for 10-19, x2.0 for 20+ (unknown: x2.0) | `engine/inputs.py`: scale on a defaulted sinking fund. |
| `SENSITIVITY_EXIT_YIELD_SHIFTS_BPS`, `SENSITIVITY_RENT_SHIFTS` | -50/0/+50 bps; -5%/0/+5% | `engine/underwrite.py` (DESIGN.md). |
| `WALK_AWAY_STEP_AED` | 10,000 | `engine/underwrite.py`. |
| `EXPIRY_WINDOWS` | 4 windows of 3 months | `engine/underwrite.py`. |
| `RETAIL_UNIT_TYPE` | `retail` | `engine/underwrite.py`: unit type whose rent counts as commercial for VAT recovery. |
