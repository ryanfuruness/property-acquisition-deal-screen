# Failure log

Each failure the evals found, what caused it, what was done about it and what that did to the numbers, newest first. Labels and figures refer to the history in `evals/summary.json`; how entries are written is in [evals/README.md](README.md#failure-log).

The v0.1.0 labels were scored on an earlier build of the deal packages (before prices were recalibrated and rent-roll dates added to ground truth). Extraction, rent-roll and discrepancy metrics are comparable across labels; verdicts and returns are not. Labels v0.2.2 to v0.2.4 reused cached model responses for unchanged requests while fixes were tested, so their cost and time lines understate a real run; the final label is a full run with no cache.

### Held-out set, first and only blind run
- Run label: v0.4.0-final (held-out deals h01 to h08, run once, never used for tuning)
- Deals / items: across the held-out set: planted discrepancies found 12 of 22 (55%) against 28 of 28 on development deals; verdicts 6 of 8; OM fields verified against the page 65% against 99%; four deals not underwritten.
- What failed, by root cause:
  1. **Figures inside images.** One new brokerage design puts its key tables in images on pages that otherwise have a text layer, and h07's OM is a poor photocopy. The model read the values, but code could not verify the quotes, so the asking price stayed unverified and h02, h05 and h07 were not underwritten. Everything downstream followed: no returns, title "not stated" flagged where the image said freehold, and h07's completion-year hard fail left unknown instead of a Decline.
  2. **A rent roll split across two sheets plus a summary sheet** (h03) was not parsed, so h03 was not underwritten and its over-rent and yield checks could not run.
  3. **A statement mixing eight months of actuals with four months of budget** (h05) was not parsed, so its annualisation, collections and unit-mix checks did not run.
  4. **New related-party wording** (h06: a seller-affiliate "income assurance agreement") did not establish the tie to the seller, so the related-party hard filter read "unknown" and h06 came out Needs work instead of Decline.
  5. **Square metres under a "sq ft" header** in a PDF rent roll (h04) was not caught.
- Root cause: ingest and verify (OCR runs only on pages without a text layer), rent-roll mapping (one sheet assumed), operating-statement mapping (actual and budget columns not distinguished), review (related-party evidence rule tied to the phrasings seen in development).
- Fix: none yet, deliberately. These numbers are the honest measure of generalisation and stay published as they are. The failures are safe in kind: where the screen could not verify a figure it refused to underwrite and said why, rather than guessing. The fixes are general (OCR image regions on text pages; multi-sheet rent rolls; actual and budget columns; broader related-party evidence), and a fresh held-out set is needed to measure them, because these eight deals are no longer blind.
- Effect on metrics: baseline for the next round.

### Changes from the domain review
- Run label: v0.3.0-final-uncached -> v0.4.0-final
- Deals / items: all development deals
- What changed: an independent reviewer and a red team playing a Dubai acquisitions director found underwriting and wording problems rather than extraction errors: exits below the entry yield, debt sized at a fixed loan-to-value instead of to cover, a proxy rent presented like the RERA index, a RERA flag that ignored uncapped re-letting, Al Barsha 1 treated as freehold, double-counted impacts and leasing costs, and "Pass" read as approval.
- Fix: engine v2 (debt sized to 1.40x cover, unlevered returns lead, exit never below entry, per-tenant RERA bands, novation at master-lease expiry), mandate v2 (Al Barsha South only, Decline label), pipeline v0.3 (area mapping, linked duplicate gaps, notices, diligence list, fixed memo structure) and recalibrated deals.
- Effect on metrics: verdicts and returns are not comparable across this change. On development deals: planted discrepancies 28 of 28, verdicts 12 of 12, memos 12 of 12 passed.

### Related-party flag lost when the model left its yes/no blank (d11)
- Run label: v0.3.0-final-uncached (first scoring of the uncached run)
- Deals / items: d11-silverline-dso, verdict
- What failed: Needs work against Pass. The review quoted "The operator is a Silverline Group company." and the quote verified, but the model left the finding's related-party field empty, so the hard filter saw "unknown".
- Root cause: reconcile stage. The mandate fact depended on one model-filled boolean; run-to-run variance in that field changed the verdict.
- Fix: the flag is now also set from the model's lease-structure conclusion, or from affiliation wording in verified quotes; a regression test covers the blank-field case. d11 re-run. Superseded in v0.3: after the domain review, a related party must be shown by a verified quote that ties the master tenant to the seller, not by a shared group name alone.
- Effect on metrics: verdict agreement 83.3% -> 91.7% on the final label; nothing else changed.

### Accepted: an ambiguous cost line (d04)
- Run label: v0.3.0-final-uncached
- Deals / items: d04-kestrel-bb, operating statement categories utilities_common and security_cleaning
- What failed: a AED 11,233 "Waste" line went to common utilities; ground truth files it under security and cleaning.
- Root cause: genuine ambiguity in the chart of accounts; both readings are defensible and total costs and NOI are unchanged.
- Fix: none, accepted.
- Effect on metrics: statement categories 125 of 127 within tolerance; no effect on underwriting.

### Accepted: the screen underwrites the seller's annualised statement (d05)
- Run label: v0.2.4
- Deals / items: d05-larkspur-barsha, underwriting levered IRR
- What failed: levered IRR 1.86% against 1.25% on the true building; Year-1 NOI within 1.4%.
- Root cause: by design. The operating statement covers nine months annualised, with items billed in the fourth quarter missing. The screen flags this (`annualised_partial_period`) and tells the analyst to request the full-year statement, but it does not invent the missing costs; ground truth uses the real full-year costs.
- Fix: none, accepted. Filling the gap with defaults would hide the issue the flag exists to raise.
- Effect on metrics: underwriting within tolerance stays at 47 of 48 checks.

### Accepted: the screen never decides title (d10)
- Run label: v0.1.0-first-9-deals onwards
- Deals / items: d10-almehrab-barsha, verdict
- What failed: Needs work against Pass on the true building, which sits on a plot restricted to UAE and GCC nationals.
- Root cause: by design. The OM never states tenure and mentions purchaser eligibility. Title is a legal question, so an unstated title is "unknown", which the mandate treats as a soft fail, not a hard one.
- Fix: none to the rule. From v0.2.0 the verdict reads "Needs work, blocked on title", the title test says "title not stated; legal check required before any further work", and the memo lists the legal check as the first open item.
- Effect on metrics: verdict agreement carries this one miss in every label.

### Memo drafts with unanchored or derived numbers
- Run label: v0.1.0-after-reruns (d03, d06 memos failed); v0.2.0 (2 of 12 failed)
- Deals / items: memo status and grounding
- What failed: first drafts contained numbers with no fact behind them: arithmetic done in prose, counts such as "30, 60 and 90 day buckets", dates written inline; and prose leaked internal identifiers such as `no_master_lease_to_related_party`.
- Root cause: memo stage. The writer saw facts as JSON and was free to derive numbers; the checker correctly rejected them.
- Fix: the writer now receives a table of citable facts (id, value as written, meaning) and may use only those numbers; dates, window bounds and sensitivity steps became facts; code rejects identifiers in prose; the prompt lists the mistakes the checker catches most.
- Effect on metrics: memo pass rate 77.8% (v0.1.0-after-reruns) -> 83.3% (v0.2.0) -> 100% (v0.2.1 onwards); first-draft pass rate 0 of 12 -> 7 of 12; grounding 99.5% -> 100%.

### Model review flags contradicted by the documents
- Run label: v0.1.0-after-reruns, v0.2.0
- Deals / items: `title_check` on d07 and d11; `potential_rent_as_income` on d06 and d10; `missing_opex_items` on d11 (master lease) and d09 (strata)
- What failed: findings not planted and not true: tenure doubts inferred from master-community charges and sinking-fund lines; "income includes vacant units" where OM income equalled in-place rent; costs flagged missing that the master-lease operator or the owners' association bears.
- Root cause: review and reconcile stages. The model judged from wording without checking figures, and the missing-cost rule ignored who bears costs under a master lease or a strata service charge.
- Fix: code rejects model findings its own figures contradict; a title finding against verified freehold wording needs quoted tenure or eligibility language; the missing-cost rule knows master-lease and strata cost-bearing.
- Effect on metrics: discrepancy precision 78.1% (v0.1.0-first-9-deals) -> 83.9% -> 96.7% (v0.2.0) -> 100% (v0.2.3); recall unchanged at 100%.

### Rent-roll date not found
- Run label: v0.1.0-after-reruns
- Deals / items: d08-jade-ic, d10-almehrab-barsha; rent-roll date, expiry test, verdict
- What failed: no date found ("Oct 26" only in d08's file name; "Tenancy list as on 30/09/2026" in d10's PDF), so expiry windows started at the analysis date, the expiry test failed wrongly and d08 came out Needs work instead of Pursue.
- Root cause: rent-roll stage read the date only from the cell the model named.
- Fix: a fallback chain (named cell, dated line in the sheet or page text, dated title, file name; a bare month reads as month end) with the source recorded.
- Effect on metrics: verdict agreement 77.8% -> 91.7% (v0.2.0; the remaining miss is d10, above).

### Asking rents and notices written in remarks
- Run label: v0.1.0-after-reruns
- Deals / items: d01 vacant asking rents (8 checks); d08 unit 122 status
- What failed: d01's asking rents for six vacant units sit only in a Remarks column ("Asking AED 76,500"), which the mapping ignored, so potential rent equalled in-place rent; d08's "Vacating on expiry" was not read as notice served.
- Root cause: rent-roll stage parsed only mapped columns.
- Fix: code reads remarks columns whether mapped or not, for asking rent and notice wording; each unit keeps the status as printed.
- Effect on metrics: rent-roll totals 95.6% -> 99.2% (v0.2.0) -> 100% (v0.2.1).

### Parsing failures found on the first runs
- Run label: v0.1.0-first-9-deals
- Deals / items: d04 rent-roll date; d11 master lease; d07 price per sq ft
- What failed: d04's "20261031" read as 2031-10-26, raising two false flags; d11's master-lease sheet not parsed, so NOI was 19% low and the verdict wrong; d07's price-per-sq-ft quote failed verification, so `area_basis_confusion` was missed.
- Root cause: ingest date parsing (ISO compact dates), rent-roll mapping (a second sheet holding lease terms), verifier (label and value in separate layout boxes).
- Fix: compact ISO dates parsed first; the mapping can name master-lease term cells; the verifier matches quotes split across line breaks in order.
- Effect on metrics: discrepancy recall 96.2% -> 100%; precision 78.1% -> 83.9%; underwriting within tolerance 86.1% -> 97.2% (v0.1.0-after-reruns).
