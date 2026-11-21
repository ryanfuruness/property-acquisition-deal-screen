Task: extract the offering memorandum fields. Call the tool `record_om_fields` exactly once.

Documents in this package:
$document_list

The offering memorandum is `$om_doc`. Extract from it only. $scan_note

Field guidance:
- `area`: the location exactly as written, including the sub-area (for example "Barsha Heights (TECOM), Al Barsha" or "Al Barsha 1").
- `market_area`: choose from the listed market areas only if the OM's location text names that exact area (or an obvious synonym such as "Jumeirah Village Circle" for JVC). Sub-areas matter: Al Barsha 1, 2 and 3 and Barsha Heights (TECOM) are not Al Barsha South; for them choose none_of_these. Quote the location text.
- `title_type`: record tenure (freehold / non-freehold) and ownership (single title / strata) only as the OM states them, with the quote that states them. "Single ownership", "one owner" or "whole building for sale" do not say whether the building is on one title deed or many; if that is all it says, ownership is "unstated". One title deed for the land and building (for example "Title deed in the name of the Seller (land and building)") is single_title; tenure stays "unstated" unless the OM says freehold. Statements about who may buy (purchaser eligibility, nationality) are tenure evidence: quote them under title_type only if they state the tenure.
- `unit_count` and `unit_mix`: as the OM states them, even if they look inconsistent with other pages.
- `occupancy_stated`: the occupancy figure and the date the OM gives for it (as_of); null as_of if the OM gives none.
- `annual_rent_stated`: the headline annual rental income the OM presents as the building's income (the figure its yield is built on, if it shows the calculation), with basis from the OM's own wording.
- `yield_stated`: the headline yield / ROI / cap rate. basis.measure is "gross" or "net" only if the OM uses that word for this figure; basis.on is "total_cost" only if the OM says acquisition costs or DLD fees are included in the denominator.
- `net_income_stated_aed`, `opex_stated_aed`: only if the OM prints these figures.
- `price_psf_stated`: only if the OM prints a price per square foot; basis is the area it says the figure is on ("on BUA", "per sq ft NSA"), else "unstated".
- `chiller_arrangement`: "chiller-free" or "AC included in rent" means the landlord pays; "tenants pay Empower/DEWA cooling directly" means tenant pays.
- `lease_structure`: master_lease if the OM says the building is let to one operator / master tenant / under a guaranteed or fixed-return lease; give the master tenant's name if stated.
- `upside_claims`: every sentence claiming rental upside, reversion, mark-to-market or rent growth, verbatim, with the uplift figure if one is printed in that sentence.
