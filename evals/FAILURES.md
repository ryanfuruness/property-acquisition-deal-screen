# Failure log

One entry per failure found by the evals, kept by hand. The point is the chain from a miss in `evals/REPORT.md` to a fix and its measured effect, so the history in `evals/summary.json` can be explained line by line.

## How to use it

1. Score a labelled run: `python -m evals score --label <label>` (for example `v0.1.0-baseline`). Labels should say what changed (`v0.1.1-asking-rent-remarks`).
2. Open `evals/REPORT.md`, section "Misses". Pick one miss, or a group with the same cause.
3. Confirm it is real before logging it: open `data/deals/<deal>/truth.json`, `runs/<deal>/run.json` and the document itself. If the scorer is wrong (a rule that expects something the document does not show, a normalisation bug), fix the scorer instead, and log that too, with "scorer" as the component.
4. Add an entry below with the fields in the template. *Root cause* names the stage (ingest, extract, verify, rent roll, opex, reconcile, review, underwriting inputs, memo, scorer) and the mechanism, not the symptom.
5. After the fix, re-score under a new label and fill in *Effect on metrics* with before and after numbers from the two results files (the headline in `evals/summary.json` history, plus the specific checks). Note any metric that got worse.
6. A miss that is accepted, not fixed (for example a design decision such as "the screen never decides title"), gets an entry with *Fix: none, accepted* and the reason.

Newest entries first.

## Template

```
### <short title>
- Run label: <label the failure was seen in> (results file: evals/results/<file>.json)
- Deals / items: <deal ids and check items, as in REPORT.md>
- What failed: <expected vs got, in one or two lines>
- Root cause: <stage and mechanism; how it was confirmed>
- Fix: <change, file(s), commit or PR>; or "none, accepted: <reason>"
- Effect on metrics: <label before -> label after: metric a x -> y, metric b x -> y; any regressions>
```

## Entries

(none yet)
