# Deal Screen: product brief

**A first-pass screen for acquiring income-producing residential buildings in Dubai.** It reads the broker's package (offering memorandum, rent roll, operating statement), reconciles the three documents, underwrites the deal on the firm's own assumptions, tests it against the firm's mandate, and drafts a screening memo where every number traces to a page, a cell or a calculation.

## User and job

**User:** an acquisitions analyst or associate at an institutional investor buying whole residential buildings in Dubai. **Reader of the output:** the MD or investment committee deciding whether a deal deserves full diligence.

**Job:** decide quickly, and defensibly, whether a deal is worth underwriting properly, and hand the decision-maker a screen they can trust without re-checking every figure.

## The problem

- **Most deals die fast, so screening is about volume.** A senior often decides after about a ten-minute read of the OM, and perhaps one deal in five goes on to full underwriting. Juniors process the rest.
- **The time goes on data handling, not judgement.** An OM review takes 20 to 45 minutes, most of it re-keying figures from PDFs and spreadsheets into the firm's template.
- **The errors are silent.** A mistyped rent, a skipped operating-statement line, a summary row counted as a unit, square metres read as square feet. Reviewers challenge assumptions; they rarely re-check transcription.
- **Broker math flatters the deal.** Yields quoted gross on asking price and called net, vacant units counted at asking rent, costs the buyer will bear left out.
- **Dubai in late 2026 makes this sharper.** Rents are falling in the main mid-market areas after record supply, so in-place rents can sit above market and "upside" claims can hide downside. RERA's index bands cap how far an under-rented unit can rise at renewal, so mark-to-market upside is often legally out of reach. And a single-title building's owner carries real costs, from district cooling in "chiller-free" buildings to the 4% DLD transfer fee, that broker yields routinely ignore.

Sources for each point are in [docs/research](research/).

## What it does, and who decides

| Automated (code or model, then verified by code) | Assisted (the screen proposes, the analyst decides) | Left to people |
|---|---|---|
| Extracting every field with its page and quote, and checking the quote is really there | Which source to rely on when documents disagree, with the reason shown | Whether to proceed to full diligence |
| Re-summing the rent roll and recategorising the operating statement | Each discrepancy: accept, override or request more information | Anything the screen marks unverified |
| The underwriting arithmetic, mandate tests and walk-away price | The assumptions that fill gaps in the seller's data | Title, nationality restrictions and other legal questions |

## Design decisions

- **The model reads; code computes and verifies.** The model extracts, maps messy layouts and judges language. A deterministic engine does every calculation. Code checks each extracted quote against its source page, and checks every number in the memo against the fact sheet; a memo with an unsupported number fails.
- **The firm's view is data, not code.** The mandate, underwriting assumptions, market view and Dubai rules live in versioned files. A different firm, or a rule change, is a data change.
- **Lead with the decision.** The memo opens with the verdict and the walk-away price, then returns, then what would make the deal fail, which is the order an investment committee reads in.
- **Show the gaps.** Unknown facts count against a deal, never for it. Defaults are labelled as defaults.

## How we know it works

An evaluation set of synthetic deal packages with discrepancies planted the way brokers plant them, so the right answer is known by construction. It measures field-level extraction accuracy, discrepancy recall and false flags, underwriting accuracy against the true building, verdict agreement, and memo grounding.

**Results on twelve packages:** all 29 planted discrepancies caught with no false flags; verdicts matching the true building on 11 of 12; every OM field extracted correctly and 99% verified against its page by code; Year-1 NOI and walk-away price within 0.1% of the true building on average; all 835 memo numbers traced to a fact. Each deal costs about USD 0.45 and 95 seconds. The remaining misses are design choices (the screen never decides title, and it does not invent costs a seller left out) and one ambiguous cost line; the [failure log](../evals/FAILURES.md) traces every miss to its cause and fix.

**Product metrics in use:** analyst review time per screened deal; deals screened per analyst per week; share of flags the analyst overrides (too high means noise, near zero on real deals means people stopped checking); deals the screen passed that later failed diligence.

## Risks

- **Over-trust.** A clean-looking memo invites less scrutiny. Mitigation: unverified fields cannot feed the engine, and the screen says what it did not check.
- **Synthetic data is tidier than reality.** The packages vary layouts and include a scanned OM, but real data rooms are messier. The first real deals are the real test.
- **Rules change.** RERA's index, fees and tax are versioned data with sources, reviewed when the rules move.
- **Confidential documents.** Deal packages are sensitive; a production version runs in-region with no training on client data.

## Deliberately out of scope

Sourcing, legal and technical diligence, full asset-management models, and live DLD transaction data (it sits behind an interactive download with no stated licence, so the market reference here is labelled illustrative). No practitioner interviews informed this version; it is grounded in public practitioner sources, and the next step is putting it in front of analysts.

## Next

Learn from analyst overrides and past investment-committee decisions, so the firm's judgement compounds. Connect real DLD and Ejari data for comps and lease verification. Export into the firm's own model template. Extend to other asset types where the same read-reconcile-underwrite loop applies.
