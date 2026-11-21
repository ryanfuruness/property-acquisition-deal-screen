// Router and the light views: landing, inbox, evals, brief, research notes.
// The deal view lives in deal.js.

import * as data from "./data.js";
import { esc, aed, pct, mult, int, chip, sev, usd, duration, words, sentence, verdictClass, date } from "./format.js";
import { renderMarkdown } from "./md.js";
import { renderDeal } from "./deal.js";

const app = document.getElementById("app");
let current = null; // cleanup hook of the current view
let firstRoute = true;

const NOTES = {
  dubai_conventions: "Dubai conventions",
  practitioner_pain_points: "Practitioner pain points",
};

function setNav(route) {
  for (const a of document.querySelectorAll(".nav a")) {
    const on = a.dataset.route === route;
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

function setTitle(t) {
  document.title = t ? `${t} | Deal Screen` : "Deal Screen: first-pass screen for Dubai residential acquisitions";
}

function parseHash() {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const [path, query] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query || "");
  return { parts, params };
}

async function route() {
  if (current?.cleanup) current.cleanup();
  current = null;
  const { parts, params } = parseHash();
  const view = parts[0] || "";
  const m = await data.manifest();
  document.getElementById("fixture-banner").hidden = !m.dev_fixture;
  try {
    if (view === "") { setNav("home"); setTitle(""); await landing(m); }
    else if (view === "inbox") { setNav("inbox"); setTitle("Deal inbox"); inbox(m); }
    else if (view === "deal" && parts[1]) { setNav("inbox"); current = await renderDeal(app, m, parts[1], parts[2] || "memo", params); }
    else if (view === "evals") { setNav("evals"); setTitle("Evals"); await evals(m); }
    else if (view === "brief") { setNav("brief"); setTitle("Brief"); await brief(m, parts[1]); }
    else if (view === "notes" && parts[1]) { setNav("brief"); await note(m, parts[1]); }
    else notFound();
  } catch (e) {
    console.error(e);
    app.innerHTML = `<div class="page narrow"><div class="error-box"><b>This view could not load.</b><p>${esc(e.message)}</p><p>Run <code>python tools/build_site_data.py</code> to refresh site/data, then reload.</p></div></div>`;
  }
  if (!["deal"].includes(view)) window.scrollTo(0, 0);
  const h1 = app.querySelector("h1");
  // move focus to the new view's heading on navigation (not on first load), for keyboard and screen-reader users
  if (h1 && !firstRoute && !app.contains(document.activeElement)) { h1.setAttribute("tabindex", "-1"); h1.focus({ preventScroll: true }); }
  firstRoute = false;
}

function notFound() {
  setTitle("Not found");
  app.innerHTML = `<div class="page narrow"><h1>That page does not exist</h1><p><a href="#/inbox">Open the deal inbox</a> or <a href="#/">go to the overview</a>.</p></div>`;
}

// ---------------------------------------------------------------- shared

const SYNTH = `All deals are synthetic: the buildings, brokers, tenants and figures are fictional, generated with known answers for evaluation.`;

function runStats(m) {
  const deals = m.deals || [];
  const costs = deals.map((d) => d.cost_usd).filter((x) => typeof x === "number");
  const times = deals.map((d) => d.duration_s).filter((x) => typeof x === "number");
  const memos = deals.filter((d) => d.memo_status);
  const avg = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null);
  return {
    n: deals.length,
    cost: avg(costs), time: avg(times),
    memosPassed: memos.filter((d) => d.memo_status === "passed").length, memos: memos.length,
    flags: deals.reduce((s, d) => s + (d.discrepancy_count || 0), 0),
  };
}

// Eval headline numbers, from evals/summary.json (written by `python -m evals score`):
// latest.headline_detail[key] = {value, k, n, label}. Older or hand-written shapes fall back to a `headline` list.
function evalHeadlines(summary) {
  if (!summary) return null;
  if (Array.isArray(summary.headline)) return summary.headline.map((h) => ({ value: h.display || fmtEval(h.value, h.unit), label: esc(h.label), detail: h.detail }));
  const hd = summary.latest?.headline_detail;
  if (!hd) return null;
  const rows = [];
  const kn = (h) => (h && h.k != null && h.n != null ? `${h.k} of ${h.n}` : null);
  const v = hd.verdict_agreement;
  if (v?.n) rows.push({ value: kn(v), label: "<b>Verdicts</b> match the mandate outcome computed on the true building" });
  const rc = hd.discrepancy_recall;
  if (rc?.n) rows.push({ value: kn(rc), label: "<b>Planted discrepancies</b> caught", detail: `${fmtEval(rc.value, "ratio")} recall; ${fmtEval(hd.discrepancy_precision?.value, "ratio")} of all flags were planted` });
  const ff = hd.false_flags_on_clean_deals;
  if (ff && ff.value != null) rows.push({ value: int(ff.value), label: `<b>False flags</b> on the ${ff.n ?? ""} clean control deal${ff.n === 1 ? "" : "s"}` });
  const om = hd.om_trusted_accuracy;
  if (om?.n) rows.push({ value: fmtEval(om.value, "ratio"), label: "<b>OM fields</b> extracted correctly and verified against the page", detail: `${om.k} of ${om.n}` });
  const g = hd.memo_grounding;
  if (g?.n) rows.push({ value: fmtEval(g.value, "ratio"), label: "<b>Memo numbers</b> grounded in the fact sheet", detail: `${g.k} of ${g.n}` });
  return rows.length ? rows : null;
}

function countOf(v) {
  if (Array.isArray(v)) return v.length;
  if (v && typeof v === "object") return Object.keys(v).length;
  return v ?? 0;
}

function fmtEval(v, unit) {
  if (v == null) return "n/a";
  if (typeof v === "string") return v;
  if (unit === "count") return int(v);
  if (unit === "ratio") return pct(v, v === 1 || v === 0 ? 0 : 1);
  return String(v);
}

// ---------------------------------------------------------------- landing

async function landing(m) {
  let summary = null;
  if (m.evals?.summary) summary = await data.evalFile("summary.json").catch(() => null);
  const heads = evalHeadlines(summary);
  const st = runStats(m);
  const proofRows = heads
    ? heads.slice(0, 4).map((h) => `<div class="proof-row"><div class="v">${esc(h.value)}</div><div class="l">${h.label}${h.detail ? ` <span class="muted small">${esc(h.detail)}</span>` : ""}</div></div>`).join("")
    : [
        ["Verdicts", "matching the expected mandate outcome"],
        ["Planted discrepancies", "caught, out of those planted the way brokers plant them"],
        ["False flags", "raised on the two clean control deals"],
        ["Fields", "extracted correctly, each backed by a verified quote"],
      ].map(([b, l]) => `<div class="proof-row"><div class="v pending">pending</div><div class="l"><b>${b}</b> ${l}</div></div>`).join("");
  const runLine = st.n
    ? `${heads ? "" : `<div class="proof-row"><div class="v">${st.memosPassed} of ${st.memos}</div><div class="l"><b>Memos</b> passed the number check: every figure matched a fact-sheet value. A memo that fails is withheld, not shipped.</div></div>`}
       <div class="proof-row"><div class="v">${esc(usd(st.cost))}</div><div class="l"><b>Model cost</b> per deal, about ${esc(duration(st.time))} end to end, against 20 to 45 minutes of re-keying by hand.</div></div>`
    : "";

  app.innerHTML = `
  <div class="landing">
    <div class="landing-grid">
      <div>
        <h1>Monday's broker packages, screened before the first meeting, with every figure traced to its page.</h1>
        <p class="lede">Deal Screen reads an offering memorandum, rent roll and operating statement for a Dubai residential building, checks them against each other, underwrites the deal on the firm's own assumptions and drafts the screening memo: verdict and walk-away price first.</p>
        <div class="cta">
          <a class="btn" href="#/inbox">Open Monday's deal inbox</a>
          <a href="#/brief">Read the product brief</a>
        </div>
        <section class="proof" aria-labelledby="proof-h">
          <div class="proof-head"><h2 id="proof-h" class="small" style="font-weight:600">${heads ? `Evaluation on ${esc(String(countOf(summary?.latest?.deals_scored)))} scored synthetic deals` : "Evaluation results, once the eval run is recorded"}</h2><a class="small" href="#/evals">How this is measured</a></div>
          ${proofRows}
          ${runLine}
        </section>
      </div>
      <div class="landing-right">
      <figure class="walkthrough">
        <div class="frame">${m.walkthrough_gif
          ? `<img src="${esc(m.walkthrough_gif)}" alt="90-second walkthrough: opening the deal inbox, reading a memo, clicking a figure to see the highlighted source page, and resolving a discrepancy.">`
          : await specimen(m)}</div>
        <figcaption>${m.walkthrough_gif ? "90-second walkthrough of one deal, from inbox to discrepancy decision." : "A memo figure and the OM page it came from. The 90-second walkthrough recording goes here."}</figcaption>
      </figure>
      <div class="how" aria-label="How the screen works">
      <div><h3>Read</h3><p>The model extracts each field with its page and a verbatim quote. Code checks the quote is really on that page.</p></div>
      <div><h3>Reconcile</h3><p>Code compares the three documents and flags what brokers do: potential rent as income, gross yields called net, missing costs.</p></div>
      <div><h3>Underwrite</h3><p>A deterministic engine applies RERA bands, DLD fees, debt and the house market view. No model does arithmetic.</p></div>
      <div><h3>Decide</h3><p>The mandate gives Pursue, Needs work or Pass. The analyst accepts, overrides or queries each flag.</p></div>
      </div>
      </div>
    </div>
    <p class="notice-line" style="margin-top:28px">${SYNTH}</p>
  </div>`;
}

// A crop of a real recorded page around a real cited quote, used until the walkthrough GIF exists.
async function specimen(m) {
  const deals = m.deals || [];
  const pick = deals.find((d) => d.memo_status === "passed" && !d.scanned_om) || deals.find((d) => d.memo_status === "passed") || deals[0];
  if (!pick) return `<div class="specimen"><p class="muted">No recorded runs yet.</p></div>`;
  try {
    const r = await data.run(pick.deal_id);
    const f = r.fact_sheet?.["deal.asking_price_aed"];
    const wa = r.fact_sheet?.["uw.walk_away_price_aed"];
    const s = f?.source;
    const d = s && data.findDoc(r, s.doc);
    const p = d?.pages?.find((x) => x.number === s.page);
    const b = s?.bbox?.[0];
    if (!p || !b) throw new Error("no bbox");
    // Crop: the page image scaled so the quote fills ~60% of the crop width, centred on the quote.
    const ar = p.height_pt / p.width_pt;     // page height / width
    const boxAr = 0.42;                      // crop height / width
    const zoom = Math.min(3.0, Math.max(1.15, 0.8 / (b[2] - b[0])));
    const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    const left = 50 - cx * zoom * 100;
    const top = 50 - (cy * zoom * ar / boxAr) * 100;
    const hl = {
      l: 50 + (b[0] - cx) * zoom * 100, w: (b[2] - b[0]) * zoom * 100,
      t: 50 + ((b[1] - cy) * zoom * ar / boxAr) * 100, h: ((b[3] - b[1]) * zoom * ar / boxAr) * 100,
    };
    return `<div class="specimen">
      <div class="memo-snip">
        <h4>${esc(pick.building_name)}: screening memo, synthetic deal</h4>
        <p>Re-engage only at or below a walk-away price of <span class="cite" style="cursor:default">${esc(aed(wa?.value))}</span>, against the <span class="cite" style="cursor:default;background:var(--hl);color:#1a1a00;text-decoration:none;box-shadow:0 0 0 2px var(--hl)">${esc(aed(f.value))}</span> asking price.</p>
      </div>
      <div class="crop" style="aspect-ratio:${(1 / boxAr).toFixed(3)}" role="img" aria-label="Crop of ${esc(s.doc)} page ${s.page}, with the quote “${esc(s.quote)}” highlighted. Synthetic document.">
        <img src="${esc(data.pageSrc(r, p.image))}" alt="" style="width:${(zoom * 100).toFixed(2)}%;left:${left.toFixed(2)}%;top:${top.toFixed(2)}%">
        <span class="hl" style="left:${hl.l.toFixed(2)}%;width:${hl.w.toFixed(2)}%;top:${(hl.t - 1.5).toFixed(2)}%;height:${(hl.h + 3).toFixed(2)}%"></span>
        <span class="crop-tag">${esc(s.doc)}, page ${s.page}</span>
      </div>
      <p class="small muted" style="margin:0">Click any figure in a memo and the evidence panel opens the source: the page with the quoted words highlighted, the spreadsheet cells, or the engine calculation.</p>
    </div>`;
  } catch {
    return `<div class="specimen"><p class="muted">Walkthrough recording to come.</p></div>`;
  }
}

// ---------------------------------------------------------------- inbox

function inbox(m) {
  const deals = m.deals || [];
  const th = m.mandate || {};
  const screened = new Set(deals.map((d) => d.deal_id));
  const pending = (m.package_index || []).filter((d) => !screened.has(d.deal_id));
  const groups = ["Pursue", "Needs work", "Pass"].map((v) => [v, deals.filter((d) => d.verdict === v)]);
  const other = deals.filter((d) => !["Pursue", "Needs work", "Pass"].includes(d.verdict));
  if (other.length) groups.push(["Not decided", other]);
  const desc = { Pursue: "meets every mandate test", "Needs work": "soft fails or unknowns for the analyst to resolve", Pass: "fails a hard filter", "Not decided": "" };
  const yocT = th.min_going_in_net_yield_on_cost, irrT = th.target_levered_irr;
  const cmp = (v, t, text) => (v == null || t == null ? esc(text) : v >= t ? `<span>${esc(text)}</span>` : `<span class="miss" title="Below the mandate's ${esc(pct(t))}">${esc(text)}<span class="visually-hidden"> (below mandate)</span></span>`);
  const rows = groups.filter(([, l]) => l.length).map(([v, list]) => `
    <tr class="verdict-break"><td colspan="8"><b>${esc(v)}</b>, ${list.length} deal${list.length === 1 ? "" : "s"}${desc[v] ? `: ${desc[v]}` : ""}</td></tr>
    ${list.map((d) => {
      const gap = d.walk_away_discount_to_asking;
      const sevs = d.discrepancy_severity || {};
      return `<tr data-href="#/deal/${esc(d.deal_id)}">
        <td class="hide-xs">${chip(d.verdict)}</td>
        <td class="name"><a href="#/deal/${esc(d.deal_id)}">${esc(d.building_name)}</a><span class="sub">${esc(d.market_area || "")}${d.units ? `, ${int(d.units)} units` : ""}${d.scanned_om ? ", scanned OM" : ""}</span></td>
        <td class="n">${esc(aed(d.asking_price_aed))}</td>
        <td class="n">${d.walk_away_price_aed != null ? esc(aed(d.walk_away_price_aed)) : '<span class="muted">n/a</span>'}${gap != null ? `<span class="gap">${gap > 0 ? `${esc(pct(gap, 1))} below asking` : gap < 0 ? `${esc(pct(-gap, 1))} above asking` : "at asking"}</span>` : ""}</td>
        <td class="n hide-xs">${cmp(d.going_in_net_yield_on_cost, yocT, pct(d.going_in_net_yield_on_cost))}</td>
        <td class="n">${cmp(d.levered_irr_pre_tax, irrT, pct(d.levered_irr_pre_tax))}</td>
        <td class="top-disc hide-xs">${d.top_discrepancy ? `${sev(d.top_discrepancy.severity)}${esc(d.top_discrepancy.title)}` : '<span class="muted">None found</span>'}</td>
        <td class="n hide-sm hide-xs">${int(d.discrepancy_count || 0)}${sevs.high ? `<span class="gap">${sevs.high} high</span>` : ""}</td>
      </tr>`;
    }).join("")}`).join("");
  const pend = pending.length ? `<tr class="verdict-break"><td colspan="8"><b>Not yet screened</b>, ${pending.length} package${pending.length === 1 ? "" : "s"} received, run not recorded</td></tr>` +
    pending.map((d) => `<tr class="missing"><td class="hide-xs"></td><td class="name">${esc(d.building_name)}<span class="sub">${esc(d.area)}, ${int(d.units)} units</span></td><td class="n">${esc(aed(d.asking_price_aed))}</td><td colspan="5" class="small">Package: ${(d.documents || []).length} documents</td></tr>`).join("") : "";
  const total = deals.length + pending.length;
  app.innerHTML = `
  <div class="page">
    <div class="page-head">
      <div>
        <h1>Deal inbox</h1>
        <p>${total} broker packages received this week, screened and sorted by verdict. Asking price against the most the firm should pay, then the returns that decide it.</p>
        <p class="notice-line">Synthetic deals. ${SYNTH.replace("All deals are synthetic: the", "The")}</p>
      </div>
      <div class="small muted" style="text-align:right">Mandate: yield on cost at least ${esc(pct(yocT))}, levered IRR ${esc(pct(irrT))}, DSCR ${esc(mult(th.min_dscr_year1))}<br>${esc(th.firm || "")}</div>
    </div>
    <div class="tbl-wrap">
    <table class="tbl inbox">
      <caption class="visually-hidden">Deal inbox, synthetic deals, sorted by verdict</caption>
      <thead><tr>
        <th scope="col" class="hide-xs">Verdict</th><th scope="col">Building</th><th scope="col" class="n">Asking</th>
        <th scope="col" class="n">Walk-away</th><th scope="col" class="n hide-xs">Yield on cost</th><th scope="col" class="n">Levered IRR</th>
        <th scope="col" class="hide-xs">Top discrepancy</th><th scope="col" class="n hide-sm hide-xs">Flags</th>
      </tr></thead>
      <tbody>${rows}${pend}${!deals.length && !pending.length ? `<tr><td colspan="8">No runs recorded yet. Run the pipeline, then <code>python tools/build_site_data.py</code>.</td></tr>` : ""}</tbody>
    </table></div>
    <p class="small muted" style="margin-top:10px">Walk-away: the highest price that still meets the ${esc(pct(irrT))} levered IRR target and the ${esc(mult(th.min_dscr_year1))} DSCR floor. Yield on cost: Year-1 NOI over price plus DLD fee and acquisition costs. Red figures miss the mandate.</p>
  </div>`;
  const tbody = app.querySelector(".inbox tbody");
  tbody.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a")) location.hash = tr.dataset.href;
  });
}

// ---------------------------------------------------------------- evals

const EVAL_GROUPS = [
  ["Reading the OM", ["om_field_accuracy", "om_trusted_accuracy", "om_citation_valid", "om_citation_page_match"]],
  ["Rent roll", ["rent_roll_unit_recall", "rent_roll_unit_precision", "rent_roll_summary_rows_as_units", "rent_roll_unit_field_accuracy", "rent_roll_totals_accuracy", "rent_roll_in_place_rent_ok", "rent_roll_occupancy_ok"]],
  ["Operating statement", ["opex_category_accuracy", "opex_period_ok"]],
  ["Discrepancies", ["discrepancy_recall", "discrepancy_precision", "false_flags_on_clean_deals"]],
  ["Underwriting", ["underwriting_within_tolerance", "noi_mean_abs_rel_error", "walk_away_mean_abs_rel_error", "yield_on_cost_mean_abs_error", "levered_irr_mean_abs_error"]],
  ["Decision and memo", ["verdict_agreement", "memo_grounding", "memo_pass_rate"]],
  ["Cost and time", ["cost_usd_per_deal", "cost_usd_total", "duration_s_per_deal"]],
];

function hlValue(key, h) {
  const v = h?.value;
  if (v == null) return "n/a";
  if (/^cost_usd/.test(key)) return usd(v);
  if (/^duration_s/.test(key)) return duration(v);
  if (/_mean_abs_error$/.test(key)) return `${(v * 100).toFixed(2)} pts`;
  if (/_rel_error$/.test(key)) return pct(v, 2);
  if (key === "deals_scored" || key === "false_flags_on_clean_deals" || key === "rent_roll_summary_rows_as_units") return int(v);
  return pct(v, v === 1 || v === 0 ? 0 : 1);
}

async function evals(m) {
  const summary = m.evals?.summary ? await data.evalFile("summary.json").catch(() => null) : null;
  const failures = m.evals?.failures ? await data.evalText("FAILURES.md").catch(() => null) : null;
  const heads = evalHeadlines(summary);
  const latest = summary?.latest;
  const names = new Map([...(m.deals || []), ...(m.package_index || [])].map((d) => [d.deal_id, d.building_name]));
  let body = "";
  if (latest?.headline_detail) {
    const hd = latest.headline_detail;
    body += `<section class="section"><h2>Headline</h2>
      <p class="note">Run “${esc(latest.label)}”, scored ${esc(date((latest.scored_at || "").slice(0, 10)))}; pipeline ${esc([].concat(latest.pipeline_versions || []).join(", "))}; ${int(countOf(latest.deals_scored))} deals scored.</p>
      <div class="proof" style="margin-top:4px">${(heads || []).slice(0, 4).map((h) => `<div class="proof-row"><div class="v">${esc(h.value)}</div><div class="l">${h.label}${h.detail ? ` <span class="muted small">${esc(h.detail)}</span>` : ""}</div></div>`).join("")}</div></section>
      <section class="section"><h2>All metrics</h2>
      <p class="note">Every number is a count of checks against the deal's truth file, so each one traces to the checks behind it. Tolerances: 0.5% on figures from the documents; 2% on NOI and walk-away price, 0.10 points on yield on cost and 0.50 points on IRR against the engine run on the true building.</p>
      <div class="tbl-wrap"><table class="tbl dense"><thead><tr><th scope="col">Metric</th><th scope="col" class="n">Value</th><th scope="col" class="n">Checks</th></tr></thead><tbody>
      ${EVAL_GROUPS.map(([g, keys]) => `<tr class="group"><td colspan="3">${esc(g)}</td></tr>` + keys.filter((k) => hd[k]).map((k) => `<tr><td>${esc(hd[k].label)}</td><td class="n">${esc(hlValue(k, hd[k]))}</td><td class="n muted">${hd[k].k != null && hd[k].n != null ? `${int(hd[k].k)} of ${int(hd[k].n)}` : hd[k].n != null ? `n = ${int(hd[k].n)}` : ""}</td></tr>`).join("")).join("")}
      </tbody></table></div></section>`;
    const pd = Object.entries(latest.per_deal || {});
    if (pd.length) {
      const tick = (ok) => (ok ? '<span class="status pass"><span class="ico" aria-hidden="true">✓</span><span class="visually-hidden">match</span></span>' : '<span class="status fail"><span class="ico" aria-hidden="true">✗</span><span class="visually-hidden">no match</span></span>');
      body += `<section class="section"><h2>Per deal</h2>
        <p class="note">Discrepancies: found (planted and flagged), missed, and flagged but not planted. Errors are the run against the engine on the true building.</p>
        <div class="tbl-wrap"><table class="tbl dense"><thead><tr><th scope="col">Deal</th><th scope="col">Verdict, expected / screen</th><th scope="col" class="n">OM fields</th><th scope="col" class="n">Units found</th><th scope="col" class="n">Found / missed / extra</th><th scope="col" class="n">NOI error</th><th scope="col" class="n">Walk-away error</th><th scope="col" class="n">Memo grounded</th><th scope="col" class="n">Cost</th></tr></thead><tbody>
        ${pd.map(([id, d]) => `<tr>
          <td><a href="#/deal/${esc(id)}">${esc(names.get(id) || id)}</a></td>
          <td>${tick(d.verdict?.expected === d.verdict?.got)} ${esc(d.verdict?.expected || "?")} / ${esc(d.verdict?.got || "?")}</td>
          <td class="n">${esc(pct(d.om_accuracy, 0))}</td>
          <td class="n">${esc(pct(d.rent_roll_recall, 0))}</td>
          <td class="n">${int(d.discrepancies?.tp)} / ${int(d.discrepancies?.fn)} / ${int(d.discrepancies?.fp)}</td>
          <td class="n">${d.noi_rel_error == null ? "n/a" : esc(pct(d.noi_rel_error, 1))}</td>
          <td class="n">${d.walk_away_rel_error == null ? "n/a" : esc(pct(d.walk_away_rel_error, 1))}</td>
          <td class="n">${d.memo?.status === "passed" ? "" : '<span class="miss">withheld</span> '}${esc(pct(d.memo?.grounding, 0))}</td>
          <td class="n">${esc(usd(d.cost_usd))}</td></tr>`).join("")}
        </tbody></table></div>
        ${Object.keys(latest.deals_not_scored || {}).length ? `<p class="small muted" style="margin-top:8px">Not scored (left out of every aggregate): ${Object.entries(latest.deals_not_scored).map(([id, why]) => `${esc(names.get(id) || id)} (${esc(why)})`).join(", ")}.</p>` : ""}
      </section>`;
    }
    const hist = summary.history || [];
    if (hist.length) {
      const cols = [["verdict_agreement", "Verdicts"], ["discrepancy_recall", "Recall"], ["discrepancy_precision", "Precision"], ["false_flags_on_clean_deals", "False flags"], ["om_trusted_accuracy", "OM fields"], ["underwriting_within_tolerance", "Underwriting"], ["memo_grounding", "Grounding"], ["cost_usd_per_deal", "Cost"]];
      body += `<section class="section"><h2>History</h2><p class="note">One row per labelled scoring run, oldest first. FAILURES.md explains each change.</p>
        <div class="tbl-wrap"><table class="tbl dense"><thead><tr><th scope="col">Run</th>${cols.map(([, l]) => `<th scope="col" class="n">${l}</th>`).join("")}</tr></thead><tbody>
        ${hist.map((h) => `<tr><td>${esc(h.label)} <span class="muted xs">${esc(date((h.scored_at || "").slice(0, 10)))}</span></td>${cols.map(([k]) => `<td class="n">${esc(hlValue(k, { value: h.headline?.[k] }))}</td>`).join("")}</tr>`).join("")}
        </tbody></table></div></section>`;
    }
  } else if (summary) {
    body += renderEvalAggregate(summary) + renderEvalPerDeal(summary);
  } else {
    body += `<div class="placeholder"><h3>No eval run recorded yet</h3><p>When <code>evals/summary.json</code> exists, this page shows the headline scores, every metric with its check counts, one row per deal and the history of scoring runs. Scoring compares each run with the deal's <code>truth.json</code>, which the pipeline never reads.</p></div>`;
  }
  app.innerHTML = `
  <div class="page">
    <div class="page-head"><div>
      <h1>Evals</h1>
      <p>Twelve synthetic packages generated from seeded true buildings, with discrepancies planted the way brokers plant them, so the right answer is known by construction.</p>
      <p class="notice-line">${SYNTH}</p>
    </div></div>
    <div class="brief-layout">
      <div>
        ${body}
        <section class="section"><h2>Failure log</h2>
          <p class="note">Each failure the evals found: what went wrong, the root cause, the fix and its effect on the numbers.${m.evals?.summary ? ` The generated report in the repository lists every miss: <a href="${esc(m.repo_url)}/blob/main/evals/REPORT.md" target="_blank" rel="noopener">evals/REPORT.md</a>.` : ""}</p>
          ${failures ? `<div class="prose">${renderMarkdown(failures.replace(/^\s*#\s+[^\n]*\n/, ""), { shiftHeadings: 1, link: linkRewrite(m) })}</div>` : `<div class="placeholder"><h3>No failure log yet</h3><p><code>evals/FAILURES.md</code> is rendered here once it exists.</p></div>`}
        </section>
      </div>
      <aside><div class="aside-box">
        <h2>What is measured</h2>
        <dl class="metric-defs">
          <dt>Extraction</dt><dd>Each OM field against the truth file, and whether its citation is valid: quote found on the page, and the page or value right.</dd>
          <dt>Rent roll and statement</dt><dd>Units found, summary rows wrongly counted as units, unit fields, totals, statement categories and period.</dd>
          <dt>Discrepancies</dt><dd>Recall and precision against the planted list, by catalogue id. Two clean deals measure false flags.</dd>
          <dt>Underwriting</dt><dd>NOI, yield on cost, levered IRR and walk-away price against the engine run on the true building.</dd>
          <dt>Verdict</dt><dd>Matches the mandate outcome computed on the true building.</dd>
          <dt>Memo grounding</dt><dd>Share of memo numbers that match a fact-sheet value. A memo below 100% is withheld.</dd>
        </dl>
        <p class="small"><a href="${esc(m.repo_url)}/blob/main/evals/README.md" target="_blank" rel="noopener">Scoring rules in full</a></p>
      </div></aside>
    </div>
  </div>`;
}

function evalCell(v) {
  if (v == null) return '<span class="muted">n/a</span>';
  if (typeof v === "boolean") return v ? '<span class="status pass"><span class="ico" aria-hidden="true">✓</span>yes</span>' : '<span class="status fail"><span class="ico" aria-hidden="true">✗</span>no</span>';
  if (typeof v === "number") return esc(Number.isInteger(v) ? int(v) : v >= 0 && v <= 1 ? pct(v, 1) : v.toFixed(3));
  if (Array.isArray(v)) return esc(v.map((x) => (typeof x === "object" ? JSON.stringify(x) : words(x))).join(", ")) || '<span class="muted">none</span>';
  if (typeof v === "object") {
    if ("matched" in v && "total" in v) return esc(`${v.matched} of ${v.total}`);
    if ("value" in v) return evalCell(v.value);
    return esc(Object.entries(v).map(([k, x]) => `${words(k)}: ${typeof x === "number" && x <= 1 && !Number.isInteger(x) ? pct(x, 1) : typeof x === "object" ? JSON.stringify(x) : x}`).join("; "));
  }
  return esc(words(v));
}

function renderEvalAggregate(s) {
  const agg = s.aggregate || s.totals || Object.fromEntries(Object.entries(s).filter(([k, v]) => !["deals", "per_deal", "headline", "runs"].includes(k) && (typeof v !== "object" || !Array.isArray(v))));
  const entries = Object.entries(agg || {});
  if (!entries.length) return "";
  return `<section class="section"><h2>Aggregate</h2><div class="tbl-wrap"><table class="tbl dense"><tbody>${entries.map(([k, v]) => `<tr><th scope="row">${esc(sentence(k))}</th><td>${evalCell(v)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

function renderEvalPerDeal(s) {
  let list = s.deals || s.per_deal || s.runs;
  if (list && !Array.isArray(list) && typeof list === "object") list = Object.entries(list).map(([id, v]) => ({ deal_id: id, ...v }));
  if (!Array.isArray(list) || !list.length) return "";
  const cols = [...new Set(list.flatMap((d) => Object.keys(d)))].filter((k) => !["deal_id", "building_name", "details", "notes"].includes(k)).slice(0, 9);
  return `<section class="section"><h2>Per deal</h2><div class="tbl-wrap"><table class="tbl dense"><thead><tr><th scope="col">Deal</th>${cols.map((c) => `<th scope="col">${esc(sentence(c))}</th>`).join("")}</tr></thead><tbody>${list.map((d) =>
    `<tr><td><a href="#/deal/${esc(d.deal_id)}">${esc(d.building_name || d.deal_id)}</a></td>${cols.map((c) => `<td>${evalCell(d[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

// ---------------------------------------------------------------- brief and notes

function linkRewrite(m) {
  return (url) => {
    const repo = m.repo_url || "";
    const u = url.trim();
    if (/^(https?:|mailto:)/i.test(u)) return u;
    if (u.startsWith("#")) return u;
    const nm = u.match(/(?:^|\/)research\/([a-z_]+)\.md$/);
    if (nm) return `#/notes/${nm[1]}`;
    if (/^research\/?$/.test(u) || /docs\/research\/?$/.test(u)) return "#/brief/research";
    if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return null;
    // other repo-relative paths go to GitHub
    const clean = u.replace(/^\.\//, "").replace(/^\.\.\//, "");
    const path = /^(docs|data|engine|pipeline|evals|tools|site)\//.test(clean) ? clean : `docs/${clean}`;
    return `${repo}/blob/main/${path}`;
  };
}

function briefAside(m) {
  const repo = m.repo_url;
  return `<aside><div class="aside-box" id="research">
    <h2>Research notes</h2>
    <ul>${Object.entries(NOTES).map(([k, v]) => `<li><a href="#/notes/${k}">${esc(v)}</a></li>`).join("")}</ul>
    <h2>Source</h2>
    <ul>
      <li><a href="${esc(repo)}" target="_blank" rel="noopener">GitHub repository</a></li>
      <li><a href="${esc(repo)}/blob/main/docs/DESIGN.md" target="_blank" rel="noopener">Technical design</a></li>
      <li><a href="${esc(repo)}/blob/main/data/mandate.yaml" target="_blank" rel="noopener">Firm mandate and assumptions</a></li>
      <li><a href="${esc(repo)}/tree/main/engine" target="_blank" rel="noopener">Underwriting engine</a></li>
    </ul>
    <p class="small muted">${SYNTH}</p>
  </div></aside>`;
}

async function brief(m, anchor) {
  const md = await data.doc("BRIEF.md").catch(() => null);
  app.innerHTML = `<div class="page"><div class="brief-layout">
    <article class="prose">${md ? renderMarkdown(md, { link: linkRewrite(m) }) : "<h1>Product brief</h1><p>The brief is not in site/data yet. Run <code>python tools/build_site_data.py</code>.</p>"}
      <p class="notice-line">${SYNTH}</p></article>
    ${briefAside(m)}
  </div></div>`;
  if (anchor === "research") document.getElementById("research")?.scrollIntoView();
}

async function note(m, name) {
  if (!NOTES[name]) return notFound();
  setTitle(NOTES[name]);
  const md = await data.doc(`research/${name}.md`).catch(() => null);
  app.innerHTML = `<div class="page"><div class="brief-layout">
    <article class="prose"><p class="small"><a href="#/brief">Brief</a> / Research notes</p>${md ? renderMarkdown(md, { link: linkRewrite(m) }) : `<h1>${esc(NOTES[name])}</h1><p>Not available.</p>`}</article>
    ${briefAside(m)}
  </div></div>`;
}

window.addEventListener("hashchange", route);
route();
export { verdictClass };
