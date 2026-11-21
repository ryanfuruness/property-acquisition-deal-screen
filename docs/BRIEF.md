# Deal Screen: product brief

**A first-pass screen for acquiring income-producing residential buildings in Dubai.** It reads a broker's package (offering memorandum, rent roll, operating statement), reconciles the three documents, underwrites the deal on the firm's own assumptions, tests it against the mandate, and drafts a screening memo in which every number traces to a page, a cell or a calculation.

## User and job

An acquisitions analyst at an institutional buyer of whole residential buildings, and the MD or investment committee who reads the result. The job: decide quickly and defensibly whether a deal deserves full underwriting, and at what price it would.

## Problem

- **Screening is a volume game.** Most deals die after a short read of the OM; the time goes on re-keying figures from PDFs and spreadsheets, not on judgement.
- **The errors are silent.** A mistyped rent, a summary row counted as a unit, square metres read as square feet. Reviewers challenge assumptions; they rarely re-check transcription.
- **Broker math flatters, and late-2026 Dubai makes it expensive.** Rents are falling in the main mid-market areas, RERA's bands cap how fast under-rented units can rise at renewal, and a single-title owner carries costs (district cooling in chiller-free buildings, the 4% DLD fee) that broker yields leave out.

## What it does, and who decides

| Automated, then verified by code | Proposed by the screen, decided by the analyst | Left to people |
|---|---|---|
| Extraction with page and quote; quotes checked on the page | Which source to rely on when documents disagree, with the reason | Whether to proceed to diligence |
| Re-summing the rent roll; recategorising the statement | Each discrepancy: accept, override with a reason, or request information | Anything unverified; title, eligibility and other legal questions |
| Underwriting, mandate tests, walk-away price | Assumptions that fill gaps in the seller's data | Price negotiation |

**Design choices.** The model reads and judges; a deterministic engine computes. Code checks every quote against its page and every memo number against a fact; a memo with an unsupported number is withheld. The firm's mandate, house view and Dubai rules are versioned data. The memo leads with the verdict and the walk-away price, says which single assumption moves that price most, and labels returns as resting on the house view. Unknowns count against a deal; the screen blocks on title rather than deciding it.

## Evidence

Twenty synthetic broker packages with known answers: twelve used during development and eight held out, generated later with new layouts and phrasings and run once, without tuning. Results for both sets, repeated-run stability and every miss with its cause and fix are in the [eval report](../evals/REPORT.md) and [failure log](../evals/FAILURES.md). The engine's arithmetic is tied out separately to an [independent Excel model](../evals/tieout/README.md).

## Product metrics and targets

| Metric | Target |
|---|---|
| Analyst review time per screened deal | under 15 minutes, against 20 to 45 for reading the OM alone, before any reconciliation or modelling |
| Planted-discrepancy recall on new packages | at least 95%, with under one false flag per deal |
| Share of flags the analyst overrides | 5 to 20%: higher is noise, near zero means nobody is checking |
| Deals the screen passed that later failed diligence for a reason in scope | none |

## Risks

- **Over-trust.** A clean memo invites less scrutiny; unverified fields cannot feed the engine, and the memo lists what it did not check.
- **Unproven fit to how Dubai deals arrive.** Institutional whole-building deals are fewer and often off-market; whether packages arrive in this form, and whether first-pass screening is the bottleneck, needs practitioners to confirm. No interviews informed this version.
- **Synthetic data is tidier than a data room.** The held-out set tests generalisation within the generator's range, not real-world mess.
- **Rules and market view drift.** RERA, fees and tax are versioned with sources; the house view needs an owner.
- **Confidential documents.** A production version runs in-region with no training on client data.

## Out of scope

Sourcing, legal and technical diligence, full asset-management models, and live DLD data (no bulk download or stated licence; the screen's reference rents are labelled a proxy).

## How it generalises

The loop is read, reconcile, underwrite, test against the mandate, cite. Market rules are data, so another regime (Abu Dhabi, Riyadh, London) is a new rules file, not new code; another asset class adds document types and engine modules. Agents extend it at both ends: chasing brokers for missing documents before the screen, and assembling the diligence pack after it. Analyst overrides and investment-committee outcomes, captured with reasons, become the firm's own benchmark and memory.
