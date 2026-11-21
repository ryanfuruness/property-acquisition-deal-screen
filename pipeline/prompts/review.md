Task: review the deal package for problems the deterministic checks cannot test. Call the tool `record_review_findings` exactly once.

Code has already parsed the rent roll and the operating statement and run rule-based checks. Their results are below. Your job is judgement on language and structure, backed by quotes:

1. `master_lease_related_party`: does the building's income depend on a master lease, bulk lease, guaranteed or fixed-return arrangement with one operator? Set `related_party` to true if the documents show a connection between the master tenant and the seller: same group, subsidiary, common ownership or management, or the same group name in both the seller's and the operator's names (quote both names). False if a document says it is independent; null if the documents say nothing either way. Related-party status is for the analyst to confirm; say so in `analyst_action`.
2. `title_check`: anything in the OM suggesting the title is not a single freehold title deed: several title deeds, strata or jointly owned property, an owners' association, Mollak service charges, a non-freehold or nationality-restricted plot, or an area where freehold is doubtful while the OM is silent on tenure. Flag for legal review only; do not decide title. Master-community charges and a sinking or reserve fund are normal for a single-title building and are not evidence of strata. If the OM states a freehold single title deed and nothing in the package contradicts it, that is not a finding: the screen already lists the title deed as a standard diligence check.
3. `upside_exceeds_rera_cap`: rental-upside, reversion or mark-to-market claims that ignore Dubai's RERA rent-increase caps (increases only at renewal, banded by the gap to the RERA index, with 90 days' notice) or the 2026 fall in market rents.
4. `potential_rent_as_income`: language presenting projected, pro-forma or potential rent as current income.
5. `other_om_claim`: any other OM statement a careful buyer would challenge (e.g. "fully let" contradicted elsewhere, "net" figures without costs, guarantees). Only material points.

Rules:
- Every finding needs at least one `evidence` item with a verbatim quote: from the OM with its page, or from a spreadsheet cell shown below with its `Sheet!A1` cell. Findings without a quote that code can find are discarded.
- Do not report a problem the rule-based findings already cover unless you add new evidence.
- Do not report absences of information as findings except under `title_check`.
- Prefer no finding to a speculative one. `severity`: high if it could change whether the deal fits the mandate or its price; medium if it moves value; low otherwise.
- `lease_structure_conclusion`: what the documents together say about how the building earns its income.

$context
