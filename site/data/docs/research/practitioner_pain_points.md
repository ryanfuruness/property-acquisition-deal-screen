# First-pass deal screen: practitioner research (residential income, Dubai first)

**How good the sources are.** Wall Street Oasis threads mostly returned errors when fetched, and Reddit could not be reached. Only one WSO thread came through in full ("Life in Acquisitions"). The forum material below therefore leans on BiggerPockets threads, the A.CRE blog, practitioner podcasts and Substacks. Several useful checklists come from vendor blogs (Docsumo, Rets AI, Peony, Apers, HelloData). Treat vendor time and accuracy figures as illustrative.

---

## 1. Pain points in first-pass screening and underwriting (13)

| # | Pain point (paraphrase) | Source |
|---|---|---|
| 1 | Most deals die fast. An MD often decides after about a 10-minute OM read and a broker call. About 1 in 5 or fewer go on to full underwriting. | [WSO: Life in Acquisitions](https://www.wallstreetoasis.com/forum/real-estate/life-in-acquisitions-analystassociate) |
| 2 | Analysts spend 30-60 minutes combing the OM and leases, then rework the broker's Argus model, which posters call "always much rosier" than reality. | [WSO](https://www.wallstreetoasis.com/forum/real-estate/life-in-acquisitions-analystassociate) |
| 3 | Juniors sort email blasts, download OMs and hand seniors a weekly pile. The volume is the job. | [WSO](https://www.wallstreetoasis.com/forum/real-estate/life-in-acquisitions-analystassociate) |
| 4 | Models split across tools. Leasing goes in Argus, then gets exported to Excel for debt, returns and sensitivities, and a lot gets re-keyed by hand. | [WSO](https://www.wallstreetoasis.com/forum/real-estate/life-in-acquisitions-analystassociate) |
| 5 | An initial OM review takes 20-45 minutes, mostly data handling rather than analysis. Ten deals a week works out to about 250 hours a year. | [Rets AI](https://rets.ai/blog/offering-memorandum-data-entry-hidden-tax) (vendor) |
| 6 | Errors enter when figures are copied from the PDF into the model: a mistyped rent or expiry, a T-12 line skipped or put in the wrong category, unit counts that drift. Reviewers challenge assumptions but rarely re-check transcribed inputs. | [Rets AI](https://rets.ai/blog/offering-memorandum-data-entry-hidden-tax) |
| 7 | Numbers with no link back to a source page make review slow and errors hard to find. | [Rets AI](https://rets.ai/blog/offering-memorandum-data-entry-hidden-tax) |
| 8 | Incomplete rent roll rows can "silently corrupt" SUMIF aggregations. Wrong units (bps vs %) give silently wrong answers. | [A.CRE AI Skill](https://www.adventuresincre.com/ai-skill-apartment-acquisition-model/) |
| 9 | Mapping document terms to the firm's own template cells is its own job. A.CRE built an AI skill that only stages inputs and writes nothing until the user confirms. | [A.CRE](https://www.adventuresincre.com/ai-skill-apartment-acquisition-model/) |
| 10 | Every T-12 comes in a different format, so analysts restructure it and map it to their own chart of accounts. Keyway built a whole product around this. | [CRE Daily on Keyway](https://www.credaily.com/briefs/keyway-launches-ai-platform-to-modernize-rent-roll-and-t12-analysis) |
| 11 | Fully underwriting every deal wastes time. Quick heuristics plus local knowledge find the one good deal faster. | [Schnageler Substack](https://schnageler.substack.com/p/cre-lesson-3-false-precision-my-back) |
| 12 | A T-12 that beats the OM is itself a red flag. The analyst has to work out why each figure differs before trusting either document. | [BiggerPockets: T-12 vs OM gap](https://www.biggerpockets.com/forums/32/topics/1291699-the-t-12-vs-om-gap-how-big-is-too-big-before-you-walk) |
| 13 | The OM cap rate can be arithmetically right but rest on an NOI that omits real costs. In one rebuild, a 7.25% cap fell to 4.56%. | [Tyler Cauble ep. 400](https://www.tylercauble.com/podcast/episode400) |

**What this means for the build.** The pain is not the arithmetic. It is (a) volume against a roughly 10-minute attention budget, (b) silent transcription and mapping errors, and (c) numbers that can't be traced to a source. A deterministic engine with per-number citations answers all three.

---

## 2. Discrepancies analysts catch between OM, rent roll and T-12 (18)

| # | Discrepancy | How an analyst detects it |
|---|---|---|
| 1 | **Occupancy mismatch.** The OM headline occupancy differs from the rent roll count. | Recount occupied units from the rent roll rows and compare with the OM figure. ([Peony](https://www.peony.ink/blog/apartment-building-deal-room)) |
| 2 | **Physical vs economic occupancy.** Units are occupied but not paying. | Compare rent roll occupancy with T-12 collections as a % of GPR. A wide gap points to concessions, delinquency or units that don't pay. ([Docsumo](https://www.docsumo.com/blog/rent-roll-automation)) |
| 3 | **Pro-forma rent presented as in-place.** | Separate in-place from projected income and ask for signed leases behind each projected figure. ([Cauble](https://www.tylercauble.com/podcast/episode400)) |
| 4 | **Vacant units priced at asking rent that no tenant pays.** | Compare vacant-unit asking rent with the rents on signed leases for the same unit type. ([Cauble](https://www.tylercauble.com/podcast/episode400)) |
| 5 | **Concessions missing.** Free months inflate gross rent. | Read the rent roll concession field, use net effective rent, and tie it to actual collections. ([A.CRE broker model](https://www.adventuresincre.com/broker-financial-model/); [Docsumo](https://www.docsumo.com/blog/rent-roll-automation)) |
| 6 | **Loss-to-lease ignored or overstated.** | Compare contract rent with market rent by unit type. Above-market rent may not hold at renewal. ([Docsumo](https://www.docsumo.com/blog/rent-roll-automation)) |
| 7 | **Annualized rent roll GPR doesn't tie to T-12 GPR.** | (In-place rent + market rent on vacant units) × 12, compared with T-12 GPR. Large gaps get escalated. ([Docsumo](https://www.docsumo.com/blog/rent-roll-automation)) |
| 8 | **Rent roll totals don't foot.** | Re-sum units, area, rent and occupancy from the rows and compare with the stated totals. ([Docsumo](https://www.docsumo.com/blog/rent-roll-automation)) |
| 9 | **OM unit mix doesn't match the rent roll.** | Reconcile counts, area and rent by unit type. ([Peony](https://www.peony.ink/blog/apartment-building-deal-room)) |
| 10 | **OM "current NOI" doesn't derive from the T-12.** | Rebuild NOI from the T-12 lines and compare with the OM. ([Peony](https://www.peony.ink/blog/apartment-building-deal-room); [Cauble](https://www.tylercauble.com/podcast/episode400)) |
| 11 | **T-3 annualized diverges from the T-12.** Momentum, one-off income, or softening that the annual figure hides. | Multiply T-3 by 4, compare with the T-12 and explain any gap. ([Peony](https://www.peony.ink/blog/apartment-building-deal-room)) |
| 12 | **Non-rent income booked as rent** (forfeited deposits, settlements). | Tie collections to 12 months of bank deposits and to estoppels. ([BiggerPockets](https://www.biggerpockets.com/forums/32/topics/1291699-the-t-12-vs-om-gap-how-big-is-too-big-before-you-walk)) |
| 13 | **Vacancy assumed at zero, or suspiciously low.** | Check for a vacancy line and apply a 5-7% floor. Pull a 24-month roll to test whether the window is unusual. ([Cauble](https://www.tylercauble.com/podcast/episode400); [BiggerPockets](https://www.biggerpockets.com/forums/32/topics/1291699-the-t-12-vs-om-gap-how-big-is-too-big-before-you-walk)) |
| 14 | **Management fee omitted** (self-managing seller). | Look for the line item. If it's missing, apply a market-rate fee. ([Cauble](https://www.tylercauble.com/podcast/episode400)) |
| 15 | **Expense ratio too light for the building's age.** Deferred maintenance or unpaid owner labour. | Benchmark the OpEx ratio against peers of the same vintage (one example: 36.7% against a 40-45% norm). ([BiggerPockets](https://www.biggerpockets.com/forums/32/topics/1291699-the-t-12-vs-om-gap-how-big-is-too-big-before-you-walk); [BiggerPockets 47 OMs](https://www.biggerpockets.com/forums/88/topics/1285165-i-analyzed-47-multifamily-oms-here-are-the-5-numbers-that-actually-matter)) |
| 16 | **Taxes or insurance at the seller's basis.** These reset on sale. | Re-underwrite at the buyer's basis and treat the current insurance premium as a floor. ([Cauble](https://www.tylercauble.com/podcast/episode400); [BiggerPockets](https://www.biggerpockets.com/forums/32/topics/1291699-the-t-12-vs-om-gap-how-big-is-too-big-before-you-walk)) |
| 17 | **No capex reserve, or OM capex doesn't match the schedule.** Personal owner costs sit in OpEx. | Look for a reserve line, tie the OM capex to the line-item schedule, and scan for non-transferable items. ([Cauble](https://www.tylercauble.com/podcast/episode400); [Peony](https://www.peony.ink/blog/apartment-building-deal-room); [BP 47 OMs](https://www.biggerpockets.com/forums/88/topics/1285165-i-analyzed-47-multifamily-oms-here-are-the-5-numbers-that-actually-matter)) |
| 18 | **Lease expiry concentration, many month-to-month tenants, delinquency.** | Group lease end dates by month and request aged receivables (30/60/90 days). ([Docsumo](https://www.docsumo.com/blog/rent-roll-automation)) |

**Dubai-specific versions of these checks.** These are the ones to build first.
- **Rent uplift capped by law.** Under Decree 43 of 2013, renewal increases are banded by how far rent sits below the RERA/Smart Rental Index. Rent up to 10% below the index gets 0%, and rent more than 40% below gets at most 20%. Increases need 90 days' written notice. So an OM "mark-to-market in year 1" is often legally impossible. Detect it by running every unit's rent against the index band and its lease expiry ([Bayut](https://www.bayut.com/mybayut/rent-increase-rules-dubai/)).
- **Cheque-count pricing.** Landlords charge more as the number of cheques rises, so headline rents on 4- or 12-cheque leases overstate comparable single-cheque rent ([Khaleej Times](https://www.khaleejtimes.com/business/property/dubai-rents-single-or-12-cheque-payment-how-to-save-big-during-price-negotiations)). Normalize to a cheque basis.
- **Service charges.** RERA-approved service charges are typically AED 15-20/sq ft for apartments (Mollak budgets, reset every year). Arrears are not in the index. Check the T-12 charge against the index ([Engel & Völkers](https://www.engelvoelkers.com/ae/en/resources/rera-service-charge-index)). For a single-owner whole building, look for master-community fees instead.
- **Gross yield presented as net.** Dubai OMs often quote gross yield. Rebuild the net figure after service charges, management, vacancy and DLD fees in the purchase basis ([dp.ae](https://dp.ae/blog/post/183/cost-of-ownership-in-dubai-how-fees-service-charges-and-maintenance-impact-net-returns/); [Property Finder](https://help.propertyfinder.ae/hc/en-us/articles/37816732289042-How-much-does-it-actually-cost-to-buy-property-in-Dubai)).
- **Ejari.** Rent roll leases should match the registered Ejari contracts. That is the Dubai equivalent of an estoppel check (inferred, not sourced).

---

## 3. Screening memo contents, IC's first questions, buy box

**Screening memo versus final IC memo.** A screening (pre-IC) memo only decides whether to spend on full diligence. It is short and leaves out full diligence detail, final scenario tables and final loan terms. The final memo is "the complete record" ([Apers](https://apers.app/learn/transaction-lifecycle/ic-process/how-to-write-an-investment-committee-memo)).

**Typical section order** ([Apers](https://apers.app/learn/transaction-lifecycle/ic-process/how-to-write-an-investment-committee-memo); [HelloData](https://www.hellodata.ai/help-articles/what-is-typically-included-in-a-multifamily-investment-committee-memo)):
1. Recommendation and decision requested
2. Executive summary
3. Property and market
4. Business plan
5. Historical operations (T-12)
6. Underwriting assumptions
7. Returns and capital structure
8. Sensitivities and downside
9. Risks and mitigants
10. Diligence status and open items
11. Appendix

**What IC reads first.** The verdict and the request, then the returns, then the risks. Other sections get consulted only when a question comes up. The verdict is one of approve, approve with conditions, defer or decline ([Apers](https://apers.app/learn/transaction-lifecycle/ic-process/how-to-write-an-investment-committee-memo)). Good ICs also ask ([Bisnow / IPF](https://www.bisnow.com/news/london/investment/your-investment-committee-might-suck-at-making-good-decisions-and-you-probably-dont-even-realise-109149)):
- Does the deal meet our checklist?
- What would make it fail (a premortem)?
- What is our pre-set walk-away price?

Screening quality shapes outcomes before a deal ever reaches IC.

**Buy box dimensions** ([Rets AI](https://rets.ai/blog/the-buy-box-as-a-queryable-filter-from-memo-to-machine-readable-criteria)):

| Dimension | What it covers |
|---|---|
| Asset type | Subtype, vintage, condition |
| Size | Units, area, total deal size, equity cheque |
| Location | Markets, submarkets, exclusion zones |
| Financial thresholds | Going-in cap or yield floor, levered and unlevered IRR, equity multiple, DSCR |
| Capital structure | Leverage, debt assumption |
| Hold period | Length of hold, exit cap assumption |
| Other | Tenancy, business plan, sponsor, process |

**How screening against the box works.** It runs in three tiers:
- **Hard filters** auto-decline the deal with no model built.
- **Soft filters** deduct from the score without excluding the deal.
- **Weights** combine the dimensions into a composite score, which is "a sort key", not a decision.

In the worked example, a 15.2% IRR against a 16% target is a soft deduction, and the deal still goes to a principal.

Sanity heuristics practitioners use: rent × 100 per door, and roughly a 2× sale on basis within about 7 years for value-add ([Schnageler](https://schnageler.substack.com/p/cre-lesson-3-false-precision-my-back)). An exit cap should sit above the entry cap ([BP 47 OMs](https://www.biggerpockets.com/forums/88/topics/1285165-i-analyzed-47-multifamily-oms-here-are-the-5-numbers-that-actually-matter)).

---

## 4. Existing products (one line each)

| Product | What it does |
|---|---|
| **Smart Bricks** | Applied-AI "intelligence layer" with firm-specific "Company Brain" plus agents for source, underwrite, diligence and monitor. Has a UAE focus ([site](https://smart-bricks.com/)). |
| **Dealpath** | Deal pipeline management. AI Extract pulls OM and flyer data into deal records and compares underwriting across deals ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools); [Build](https://build.inc/insights/best-ai-agent-platforms-real-estate)). |
| **Cherre** | CRE data unification and knowledge graph. Agent.STUDIO lets firms build custom agents on that data ([Build](https://build.inc/insights/best-ai-agent-platforms-real-estate)). |
| **Archer** | Multifamily underwriting. Parses rent rolls and T-12s, pairs them with rent and expense comps, and works through an Excel add-in ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **Keyway** | Multifamily acquisitions. Its T12 Analyzer maps statements to the client's chart of accounts, and its Rent Roll Analyzer flags anomalies, with audit-ready output ([CRE Daily](https://www.credaily.com/briefs/keyway-launches-ai-platform-to-modernize-rent-roll-and-t12-analysis)). |
| **Clik.ai** | Lender-side spreading of T-12s and rent rolls from PDF, Excel or scans, plus underwriting and servicing ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **Blooma** | CRE lending: intake, credit analysis and portfolio monitoring from loan packages ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **Smart Capital Center** | Lender and investor AI underwriting from financials, rent rolls, OMs and leases ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **PropRise Primer** | Fills the firm's own Excel model from OM, rent roll and T-12, links each figure to its source page, and flags conflicts between documents. This is the closest analogue to this build ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **Cactus** | Extracts P&Ls, T-12s, rent rolls and OMs into Excel models with working formulas ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **Docsumo** | Generic document extraction with validation, delivered via API. Does not build the pro forma ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **ARGUS Enterprise** | The incumbent valuation and cash-flow platform, with rent roll upload ([Docsumo](https://docsumo.com/blog/best-cre-automation-tools)). |
| **Diald AI** | Generates investor-ready due-diligence memos from many data sources ([Build](https://build.inc/insights/best-ai-agent-platforms-real-estate)). |
| **Prophia** | Lease abstraction across portfolios, with human quality checks ([Build](https://build.inc/insights/best-ai-agent-platforms-real-estate)). |
| **A.CRE AI Skill** | Claude skill that stages OM, T-12 and rent roll inputs into A.CRE's apartment model and flags input errors ([A.CRE](https://www.adventuresincre.com/ai-skill-apartment-acquisition-model/)). |

**Where this build fits.** Most tools either stop at extraction (Docsumo, Clik.ai), serve lenders (Blooma, Clik.ai), manage the pipeline (Dealpath) or are US multifamily-centric (Archer, Keyway). The gap is: three-document reconciliation, a deterministic engine, mandate fit with hard and soft filters, and a short screening memo with per-number citations, built on Dubai rules (RERA index caps, service charges, cheque normalization, DLD costs).

---

## 5. What the Smart Bricks pages show

**Homepage** ([smart-bricks.com](https://smart-bricks.com/))

The architecture splits the work in two:
- **AI** for document interpretation, research and risk identification.
- **Deterministic "Financial Engines"** for cash flows, debt, waterfalls and returns.

The intelligence layers are:
- **"Company Brain"**: the firm's mandates, models, methodology and past IC decisions.
- **Real Estate Intelligence**: 19 asset classes.
- **Market Intelligence**: 207 countries.
- **Specialist agents**: assembled per deal.

Workflow modules: Source (screen and score against the mandate), Underwrite (base and downside cases), Diligence (check evidence, flag assumptions), Monitor (re-underwrite, covenants).

How output looks in their own examples:
- IC memos that lead with a recommendation ("Proceed to IC"), then key metrics, thesis and risks.
- An investment score out of 100 with "evidence confidence".
- Scenario comparisons, and material changes flagged for review.
- **Every figure links to a specific spreadsheet cell or PDF page and to the methodology rule applied.** Tagline: "Every number sourced. Every decision remembered."
- Exports to Excel, Word, PowerPoint and PDF.

Users are investment firms first, then lenders, developers and advisors. The UAE is one of four market pages, alongside the US, UK and KSA, and there are Dubai examples. Performance claims are self-reported.

**Forward Deployed RE Investor** ([link](https://smart-bricks.com/careers/forward-deployed-real-estate-investor))
- The job is to break down how institutional investors underwrite and decide, and to define the reasoning and outputs agents should produce.
- They design underwriting methods and evaluation benchmarks, and review AI-generated analysis.
- They need IC-process fluency. In other words, output must pass review by a senior investor and show its reasoning explicitly.

**RE Investment Associate** ([link](https://smart-bricks.com/careers/real-estate-investment-associate))
- Underwrites across markets and builds and reviews models in Excel, including scenarios and sensitivities.
- Grades agent outputs and creates "investment reasoning benchmarks".
- Domain experts are the quality gate. AI output is held to the same standard as human work.

**Research and Intelligence Analyst** ([link](https://smart-bricks.com/careers/real-estate-research-intelligence-analyst))
- Builds market intelligence "country by country": regulation, tax, transaction process and authoritative local datasets.
- Validates AI-generated market intelligence and structures research into frameworks agents can use.
- Monitors changes that matter to investment decisions.
- For Dubai, this means DLD/RERA rules belong in structured, versioned data, not in prompts.

**PM, AI Products** ([link](https://smart-bricks.com/careers/product-manager-ai-products))
- "Agents perform work rather than simply expose software features."
- The PM decides which tasks are automated, which are assisted and which stay with human judgment, and sets evaluation criteria alongside product metrics.
- The posting does not specify an output format.

**What to take from this for the build.**
- Make the memo lead with the verdict.
- Cite every number to a page or cell and to the rule applied.
- Keep the maths deterministic, and keep the LLM for extraction and narrative.
- Encode the mandate as data, and show confidence and open items.
- Mark clearly where a human must decide.
- Ship an evaluation set: seeded OM, rent roll and T-12 discrepancies with expected flags. That mirrors the "benchmarks" both investor roles are hired to build.
