// Router and the light views: landing, inbox, evals, brief, research notes.
// The deal view lives in deal.js.

import * as data from "./data.js";
import { esc, aed, pct, mult, int, chip, sev, usd, duration, words, sentence, verdictClass, verdictName, date, hv } from "./format.js";
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
    else if (view === "evals") { setNav("evals"); setTitle("Evals"); await evals(m, parts[1]); }
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

// Headline rows for dev and held-out side by side, read from summary.json (never hard-coded).
const LANDING_KEYS = [
  ["verdict_agreement", "Verdicts", "match the mandate outcome on the true building"],
  ["discrepancy_recall", "Planted discrepancies", "caught"],
  ["discrepancy_precision", "Flags", "that were planted (precision)"],
  ["om_trusted_accuracy", "OM fields", "correct and verified against the page"],
  ["memo_grounding", "Memo numbers", "grounded in the fact sheet"],
];

function setCell(h, key) {
  if (!h || h.value == null) return '<span class="muted">n/a</span>';
  if (key === "verdict_agreement" || key === "discrepancy_recall") return h.k != null ? `${int(h.k)} of ${int(h.n)}` : esc(pct(h.value, 0));
  return esc(pct(h.value, h.value === 1 ? 0 : 1));
}

async function landing(m) {
  let summary = null;
  if (m.evals?.summary) summary = await data.evalFile("summary.json").catch(() => null);
  const st = runStats(m);
  const bySet = summary?.latest?.headline_detail_by_set;
  const sets = m.sets || {};
  let proof;
  if (bySet && (bySet.dev || bySet.heldout)) {
    const dn = bySet.dev?.deals_scored?.value, hn = bySet.heldout?.deals_scored?.value;
    proof = `<table class="proof-tbl">
      <caption>Scored against ground truth, run “${esc(summary.latest.label)}”. <a href="#/evals">How this is measured</a></caption>
      <thead><tr><th scope="col"></th><th scope="col" class="n">Development<span>${dn != null ? `${int(dn)} deals` : ""}</span></th><th scope="col" class="n">Held-out<span>${hn ? `${int(hn)} unseen deals` : "not scored yet"}</span></th></tr></thead>
      <tbody>${LANDING_KEYS.filter(([k]) => bySet.dev?.[k] || bySet.heldout?.[k]).map(([k, b, l]) => `<tr><th scope="row"><b>${b}</b> ${l}</th><td class="n">${setCell(bySet.dev?.[k], k)}</td><td class="n">${setCell(bySet.heldout?.[k], k)}</td></tr>`).join("")}
      <tr><th scope="row"><b>Model cost</b> per deal, about ${esc(duration(st.time))} end to end</th><td class="n" colspan="2">${esc(usd(st.cost))}</td></tr></tbody>
    </table>
    <p class="small muted" style="margin-top:6px">${esc(sets.heldout ? `Held-out: ${sets.heldout}.` : "Held-out deals were never used to build or tune the screen.")}</p>`;
  } else {
    const heads = evalHeadlines(summary);
    proof = `<div class="proof"><div class="proof-head"><h2 class="small" style="font-weight:600">${heads ? "Evaluation results" : "Evaluation results, once the eval run is recorded"}</h2><a class="small" href="#/evals">How this is measured</a></div>
      ${(heads || []).slice(0, 4).map((h) => `<div class="proof-row"><div class="v">${esc(h.value)}</div><div class="l">${h.label}</div></div>`).join("") || '<p class="muted">pending</p>'}</div>`;
  }
  const w = m.walkthrough || (m.walkthrough_gif ? { path: m.walkthrough_gif } : null);
  const dur = w?.duration_s ? `${Math.round(w.duration_s)} seconds` : "";
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
      </div>
      <section class="proof-wrap" aria-label="Evaluation results">${proof}</section>
    </div>
    <figure class="walkthrough wide">
      ${w ? `<a class="frame" href="${esc(w.path)}" target="_blank" rel="noopener" title="Open the walkthrough at full size"><img src="${esc(w.path)}" ${w.width ? `width="${w.width}" height="${w.height}"` : ""} alt="Walkthrough${dur ? `, ${dur}` : ""}: the deal inbox, opening a deal, clicking memo figures to see the highlighted source page and cells, reviewing a discrepancy, and the underwriting tab."></a>`
        : `<div class="frame">${await specimen(m)}</div>`}
      <figcaption>${w ? `Walkthrough, ${dur || "about half a minute"}, recorded from this site: inbox, a deal's memo, figures traced to the page, a discrepancy decision, the underwriting. Click to open full size.` : "A memo figure and the OM page it came from. The walkthrough recording goes here."}</figcaption>
    </figure>
    <div class="how four" aria-label="How the screen works">
      <div><h3>Read</h3><p>The model extracts each field with its page and a verbatim quote. Code checks the quote is really on that page.</p></div>
      <div><h3>Reconcile</h3><p>Code compares the three documents and flags what brokers do: potential rent as income, gross yields called net, missing costs.</p></div>
      <div><h3>Underwrite</h3><p>A deterministic engine applies RERA bands, DLD fees, debt and the house market view. No model does arithmetic.</p></div>
      <div><h3>Decide</h3><p>The mandate gives Pursue, Needs work or Decline. The analyst accepts, overrides or queries each flag.</p></div>
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

let inboxFilter = "all";

function inbox(m) {
  const all = (m.deals || []).map((d) => ({ ...d, verdict: verdictName(d.verdict) }));
  const th = m.mandate || {};
  const sets = m.sets || {};
  const screenedIds = new Set(all.map((d) => d.deal_id));
  const pendingAll = (m.package_index || []).filter((d) => !screenedIds.has(d.deal_id));
  const nSet = (s) => (m.package_index || []).filter((d) => (d.set || "dev") === s).length;
  const yocT = th.min_going_in_net_yield_on_cost, irrT = th.target_unlevered_irr;
  const cmp = (v, t, text) => (v == null || t == null ? esc(text) : v >= t ? `<span>${esc(text)}</span>` : `<span class="miss" title="Below the mandate's ${esc(pct(t))}">${esc(text)}<span class="visually-hidden"> (below mandate)</span></span>`);
  const desc = { Pursue: "meets every mandate test", "Needs work": "soft misses, unknowns or a blocking check for the analyst", Decline: "fails a hard filter; returns shown for context only", "Not decided": "" };

  const render = () => {
    const keep = (d) => inboxFilter === "all" || (d.set || "dev") === inboxFilter;
    const deals = all.filter(keep);
    const pending = pendingAll.filter(keep);
    const groups = ["Pursue", "Needs work", "Decline"].map((v) => [v, deals.filter((d) => d.verdict === v)]);
    const other = deals.filter((d) => !["Pursue", "Needs work", "Decline"].includes(d.verdict));
    if (other.length) groups.push(["Not decided", other]);
    const rows = groups.filter(([, l]) => l.length).map(([v, list]) => `
      <tr class="verdict-break"><td colspan="8"><b>${esc(v)}</b>, ${list.length} deal${list.length === 1 ? "" : "s"}${desc[v] ? `: ${desc[v]}` : ""}</td></tr>
      ${list.map((d) => {
        const gap = d.walk_away_discount_to_asking;
        const sevs = d.discrepancy_severity || {};
        const declined = d.verdict === "Decline";
        const stmt = declined && d.stop_reason ? `<span class="stmt stop">${esc(d.stop_reason)}</span>`
          : (d.blocked_on_statements || []).length ? `<span class="stmt blocked">Blocked: ${esc(d.blocked_on_statements.join(" "))}</span>` : "";
        const wa = d.walk_away_price_aed != null
          ? (declined ? `<span class="context" title="Context only: a declined deal has no buy price">${esc(aed(d.walk_away_price_aed))}<span class="gap">context only</span></span>`
            : `${esc(aed(d.walk_away_price_aed))}<span class="gap">${gap > 0 ? `${esc(pct(gap, 1))} below asking` : gap < 0 ? `${esc(pct(-gap, 1))} above asking` : "at asking"}</span>`)
          : '<span class="muted">n/a</span>';
        const irr = d.unlevered_irr_pre_tax;
        return `<tr data-href="#/deal/${esc(d.deal_id)}">
          <td class="hide-xs">${chip(d.verdict)}</td>
          <td class="name"><a href="#/deal/${esc(d.deal_id)}">${esc(d.building_name)}</a>${d.set === "heldout" ? '<span class="set-tag" title="Held-out deal: not used to build or tune the pipeline">held-out</span>' : ""}<span class="sub">${esc(d.market_area || "")}${d.units ? `, ${int(d.units)} units` : ""}${d.scanned_om ? ", scanned OM" : ""}</span>${stmt}</td>
          <td class="n">${esc(aed(d.asking_price_aed))}</td>
          <td class="n">${wa}</td>
          <td class="n hide-xs">${declined ? `<span class="context">${esc(pct(d.going_in_net_yield_on_cost))}</span>` : cmp(d.going_in_net_yield_on_cost, yocT, pct(d.going_in_net_yield_on_cost))}</td>
          <td class="n">${declined ? `<span class="context">${esc(pct(irr))}</span>` : cmp(irr, irrT, pct(irr))}</td>
          <td class="top-disc hide-xs">${d.top_discrepancy ? `${sev(d.top_discrepancy.severity)}${esc(d.top_discrepancy.title)}` : '<span class="muted">None found</span>'}</td>
          <td class="n hide-sm hide-xs">${int(d.discrepancy_count || 0)}${sevs.high ? `<span class="gap">${sevs.high} high</span>` : ""}</td>
        </tr>`;
      }).join("")}`).join("");
    const pend = pending.length ? `<tr class="verdict-break"><td colspan="8"><b>Not yet screened</b>, ${pending.length} package${pending.length === 1 ? "" : "s"} received, run not recorded</td></tr>` +
      pending.map((d) => `<tr class="missing"><td class="hide-xs"></td><td class="name">${esc(d.building_name)}${d.set === "heldout" ? '<span class="set-tag">held-out</span>' : ""}<span class="sub">${esc(d.area)}, ${int(d.units)} units</span></td><td class="n">${esc(aed(d.asking_price_aed))}</td><td colspan="5" class="small">Package: ${(d.documents || []).length} documents</td></tr>`).join("") : "";
    app.querySelector(".inbox tbody").innerHTML = rows + pend + (!deals.length && !pending.length ? `<tr><td colspan="8">No deals in this set.</td></tr>` : "");
    for (const b of app.querySelectorAll(".seg button")) b.setAttribute("aria-pressed", b.dataset.set === inboxFilter);
  };

  const total = (m.package_index || []).length || all.length;
  app.innerHTML = `
  <div class="page">
    <div class="page-head">
      <div>
        <h1>Deal inbox</h1>
        <p>${total} broker packages received this week, screened and sorted by verdict: asking price against the most the firm should pay, then the returns that decide it.</p>
        <p class="notice-line">Synthetic deals. ${SYNTH.replace("All deals are synthetic: the", "The")}</p>
      </div>
      <div class="small muted" style="text-align:right">Mandate: unlevered IRR ${esc(pct(irrT, 1))}, yield on cost ${esc(pct(yocT, 1))}<br>${esc(th.firm || "")}</div>
    </div>
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Deal set">
        <button type="button" data-set="all">All ${total}</button>
        <button type="button" data-set="dev">Development ${nSet("dev")}</button>
        <button type="button" data-set="heldout">Held-out ${nSet("heldout")}</button>
      </div>
      <p>Held-out deals come from unseen brokers, layouts and phrasings and were never used to build or tune the screen, so they show how it does on packages it has not seen.</p>
    </div>
    <div class="tbl-wrap">
    <table class="tbl inbox">
      <caption class="visually-hidden">Deal inbox, synthetic deals, sorted by verdict</caption>
      <thead><tr>
        <th scope="col" class="hide-xs">Verdict</th><th scope="col">Building</th><th scope="col" class="n">Asking</th>
        <th scope="col" class="n">Walk-away ${hv()}</th><th scope="col" class="n hide-xs">Yield on cost</th><th scope="col" class="n">Unlevered IRR ${hv()}</th>
        <th scope="col" class="hide-xs">Top discrepancy</th><th scope="col" class="n hide-sm hide-xs">Flags</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
    <p class="small muted" style="margin-top:10px">Walk-away: the highest price at which the deal still meets the ${esc(pct(irrT, 1))} unlevered IRR target, on the firm's house view of rents and exit yields. Yield on cost: Year-1 NOI over price plus DLD fee and acquisition costs. Red figures miss the mandate. Declined deals have no buy price; their figures are context only.</p>
  </div>`;
  render();
  app.querySelector(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-set]");
    if (b) { inboxFilter = b.dataset.set; render(); }
  });
  app.querySelector(".inbox tbody").addEventListener("click", (e) => {
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
  ["Underwriting inputs (engine on extracted vs true inputs)", ["underwriting_within_tolerance", "noi_mean_abs_rel_error", "walk_away_mean_abs_rel_error", "yield_on_cost_mean_abs_error", "unlevered_irr_mean_abs_error", "levered_irr_mean_abs_error"]],
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

function knCell(key, h) {
  if (!h) return '<td class="n"><span class="muted">n/a</span></td>';
  const kn = h.k != null && h.n != null ? `<span class="kn">${int(h.k)} of ${int(h.n)}</span>` : h.n != null && !/^cost|^duration/.test(key) ? `<span class="kn">n = ${int(h.n)}</span>` : "";
  return `<td class="n">${esc(hlValue(key, h))}${kn}</td>`;
}

const STAB_ROWS = [
  ["verdict_unanimous", "Deals with the same verdict on every run", "frac"],
  ["verdict_correct_runs", "Runs with the right verdict", "frac"],
  ["discrepancy_sets_identical", "Deals with identical discrepancy sets", "frac"],
  ["discrepancy_jaccard_mean", "Discrepancy-set agreement (mean Jaccard)", "ratio"],
  ["walk_away_spread_rel_mean", "Walk-away spread, mean (max - min) / median", "ratio"],
  ["walk_away_spread_rel_max", "Walk-away spread, worst deal", "ratio"],
  ["memo_pass_rate", "Memos passing the number check, all runs", "frac"],
];

function stabCell(h, kind) {
  if (!h || h.value == null) return '<td class="n"><span class="muted">n/a</span></td>';
  const kn = h.k != null && h.n != null ? `<span class="kn">${int(h.k)} of ${int(h.n)}</span>` : "";
  return `<td class="n">${esc(pct(h.value, kind === "ratio" && h.value < 0.1 ? 2 : 1))}${kn}</td>`;
}

async function evals(m, sub) {
  if (sub === "tieout") return tieout(m);
  const summary = m.evals?.summary ? await data.evalFile("summary.json").catch(() => null) : null;
  const failures = m.evals?.failures ? await data.evalText("FAILURES.md").catch(() => null) : null;
  const latest = summary?.latest;
  const names = new Map([...(m.deals || []), ...(m.package_index || [])].map((d) => [d.deal_id, d.building_name]));
  const sets = m.sets || {};
  let body = "";
  if (latest?.headline_detail) {
    const bySet = latest.headline_detail_by_set || { combined: latest.headline_detail };
    const cols = [["dev", "Development"], ["heldout", "Held-out"], ["combined", "All deals"]].filter(([k]) => bySet[k]);
    const n = (k) => bySet[k]?.deals_scored?.value;
    body += `<section class="section"><h2>Results by set</h2>
      <p class="note">Run “${esc(latest.label)}”, scored ${esc(date((latest.scored_at || "").slice(0, 10)))}; pipeline ${esc([].concat(latest.pipeline_versions || []).join(", "))}. Development deals were used to build and tune the screen; held-out deals were not, so the gap between the two columns is the honest estimate of how much of the development score comes from tuning. A set with no scored deal shows n/a, never zero.</p>
      <div class="tbl-wrap"><table class="tbl dense sets-tbl"><thead><tr><th scope="col">Metric</th>${cols.map(([k, l]) => `<th scope="col" class="n${k === "heldout" ? " ho" : ""}">${l}<span class="kn">${n(k) != null ? `${int(n(k))} deals` : ""}</span></th>`).join("")}</tr></thead><tbody>
      ${EVAL_GROUPS.map(([g, keys]) => {
        const present = keys.filter((k) => cols.some(([c]) => bySet[c]?.[k]));
        if (!present.length) return "";
        return `<tr class="group"><td colspan="${cols.length + 1}">${esc(g)}</td></tr>` + present.map((k) => {
          const lab = (cols.map(([c]) => bySet[c]?.[k]?.label).find(Boolean) || k).replace(/^Underwriting inputs(?: \(engine on extracted vs true inputs\))?:\s*/, "");
          return `<tr><td>${esc(sentence(lab))}</td>${cols.map(([c]) => knCell(k, bySet[c]?.[k])).join("")}</tr>`;
        }).join("");
      }).join("")}
      </tbody></table></div>
      <p class="small muted" style="margin-top:8px">Underwriting inputs: the engine run on the screen's extracted inputs against the engine run on the true building's inputs. It measures how far reading errors move the numbers, not whether the house view is right. The engine itself is tied out separately: <a href="#/evals/tieout">independent Excel model, every check listed</a>.</p>
    </section>`;

    const stab = summary.stability;
    body += `<section class="section" id="stability"><h2>Stability across repeated runs</h2>`;
    if (stab?.aggregate) {
      const sb = stab.aggregate_by_set || {};
      const scols = [["dev", "Development"], ["heldout", "Held-out"]].filter(([k]) => sb[k] && sb[k].deals).concat([["__all", "All deals"]]);
      const get = (c) => (c === "__all" ? stab.aggregate : sb[c]);
      body += `<p class="note">The same packages run ${esc(String(stab.run_dirs?.length || "several"))} times (“${esc(stab.label)}”). Stability says nothing about correctness on its own, which is why runs with the right verdict are counted too.</p>
        <div class="tbl-wrap"><table class="tbl dense sets-tbl"><thead><tr><th scope="col">Measure</th>${scols.map(([c, l]) => `<th scope="col" class="n">${l}<span class="kn">${int(get(c)?.deals)} deals, ${int(get(c)?.runs)} runs</span></th>`).join("")}</tr></thead><tbody>
        ${STAB_ROWS.map(([k, l, kind]) => `<tr><td>${esc(l)}</td>${scols.map(([c]) => stabCell(get(c)?.[k], kind)).join("")}</tr>`).join("")}</tbody></table></div>`;
      const pd = Object.entries(stab.per_deal || {}).filter(([, d]) => !d.verdict_unanimous || (d.walk_away_spread_rel || 0) > 0.01 || (d.discrepancy_jaccard_mean ?? 1) < 1);
      if (pd.length) body += `<p class="small" style="margin-top:8px">Deals that moved between runs: ${pd.map(([id, d]) => `${esc(names.get(id) || id)} (${esc((d.verdicts || []).join(" / "))}${d.walk_away_spread_rel ? `, walk-away spread ${esc(pct(d.walk_away_spread_rel, 1))}` : ""})`).join("; ")}.</p>`;
    } else {
      body += `<div class="placeholder"><h3>No stability comparison recorded yet</h3><p>When <code>python -m evals stability</code> has compared repeated runs, this shows verdict agreement across runs, discrepancy-set agreement and the spread of the walk-away price, by set.</p></div>`;
    }
    body += `</section>`;

    const hist = summary.history || [];
    if (hist.length) {
      const hcols = [["verdict_agreement", "Verdicts"], ["discrepancy_recall", "Recall"], ["discrepancy_precision", "Precision"], ["om_trusted_accuracy", "OM fields"], ["underwriting_within_tolerance", "Underwriting inputs"], ["memo_pass_rate", "Memos passed"], ["cost_usd_per_deal", "Cost"]];
      body += `<section class="section"><h2>How it improved</h2><p class="note">One row per labelled scoring run, oldest first, on development deals (all deals for runs before the held-out set existed). The failure log below explains each change. Early labels used an earlier build of the packages, so their verdicts and returns are not comparable.</p>
        <div class="tbl-wrap"><table class="tbl dense"><thead><tr><th scope="col">Run</th>${hcols.map(([, l]) => `<th scope="col" class="n">${l}</th>`).join("")}</tr></thead><tbody>
        ${hist.map((h) => { const hd = h.headline_by_set?.dev || h.headline || {}; return `<tr><td>${esc(h.label)} <span class="muted xs">${esc(date((h.scored_at || "").slice(0, 10)))}</span></td>${hcols.map(([k]) => `<td class="n">${esc(hlValue(k, { value: hd[k] }))}</td>`).join("")}</tr>`; }).join("")}
        </tbody></table></div></section>`;
    }

    const pd = Object.entries(latest.per_deal || {});
    if (pd.length) {
      const tick = (ok) => (ok ? '<span class="status pass"><span class="ico" aria-hidden="true">✓</span><span class="visually-hidden">match</span></span>' : '<span class="status fail"><span class="ico" aria-hidden="true">✗</span><span class="visually-hidden">no match</span></span>');
      const row = ([id, d]) => `<tr>
          <td><a href="#/deal/${esc(id)}">${esc(names.get(id) || id)}</a></td>
          <td>${tick(verdictName(d.verdict?.expected) === verdictName(d.verdict?.got))} ${esc(verdictName(d.verdict?.expected) || "?")} / ${esc(verdictName(d.verdict?.got) || "?")}</td>
          <td class="n">${esc(pct(d.om_accuracy, 0))}</td>
          <td class="n">${esc(pct(d.rent_roll_recall, 0))}</td>
          <td class="n">${int(d.discrepancies?.tp)} / ${int(d.discrepancies?.fn)} / ${int(d.discrepancies?.fp)}</td>
          <td class="n">${d.noi_rel_error == null ? "n/a" : esc(pct(d.noi_rel_error, 1))}</td>
          <td class="n">${d.walk_away_rel_error == null ? "n/a" : esc(pct(d.walk_away_rel_error, 1))}</td>
          <td class="n">${d.memo?.status === "passed" ? "" : '<span class="miss">withheld</span> '}${esc(pct(d.memo?.grounding, 0))}</td>
          <td class="n">${esc(usd(d.cost_usd))}</td></tr>`;
      const group = (setId, label) => {
        const rows = pd.filter(([, d]) => (d.set || "dev") === setId);
        return rows.length ? `<tr class="group"><td colspan="9">${esc(label)}</td></tr>${rows.map(row).join("")}` : "";
      };
      body += `<section class="section"><h2>Per deal</h2>
        <p class="note">Discrepancies: found (planted and flagged) / missed / flagged but not planted. Errors are the engine on extracted inputs against the engine on true inputs.</p>
        <div class="tbl-wrap"><table class="tbl dense"><thead><tr><th scope="col">Deal</th><th scope="col">Verdict, expected / screen</th><th scope="col" class="n">OM fields</th><th scope="col" class="n">Units found</th><th scope="col" class="n">Found / missed / extra</th><th scope="col" class="n">NOI error</th><th scope="col" class="n">Walk-away error</th><th scope="col" class="n">Memo grounded</th><th scope="col" class="n">Cost</th></tr></thead><tbody>
        ${group("dev", `Development: ${sets.dev || "used to build and tune the screen"}`)}${group("heldout", `Held-out: ${sets.heldout || "never used for tuning"}`)}
        </tbody></table></div>
        ${Object.keys(latest.deals_not_scored || {}).length ? `<p class="small muted" style="margin-top:8px">Not scored (left out of every aggregate): ${Object.entries(latest.deals_not_scored).map(([id, why]) => `${esc(names.get(id) || id)} (${esc(why)})`).join(", ")}.</p>` : ""}
      </section>`;
    }
  } else if (summary) {
    body += renderEvalAggregate(summary) + renderEvalPerDeal(summary);
  } else {
    body += `<div class="placeholder"><h3>No eval run recorded yet</h3><p>When <code>evals/summary.json</code> exists, this page shows the scores for development and held-out deals side by side, stability across repeated runs, and one row per deal.</p></div>`;
  }
  app.innerHTML = `
  <div class="page">
    <div class="page-head"><div>
      <h1>Evals</h1>
      <p>Synthetic packages generated from seeded true buildings, with discrepancies planted the way brokers plant them, so the right answer is known by construction. Twelve development deals, plus held-out deals with unseen brokers, layouts and phrasings.</p>
      <p class="notice-line">${SYNTH}</p>
    </div></div>
    <div class="brief-layout">
      <div>
        ${body}
        <section class="section"><h2>Failure log</h2>
          <p class="note">Each failure the evals found: what went wrong, the root cause, the fix and its effect on the numbers. The generated report in the repository lists every miss: <a href="${esc(m.repo_url)}/blob/main/evals/REPORT.md" target="_blank" rel="noopener">evals/REPORT.md</a>.</p>
          ${failures ? `<div class="prose">${renderMarkdown(failures.replace(/^\s*#\s+[^\n]*\n/, ""), { shiftHeadings: 1, link: linkRewrite(m) })}</div>` : `<div class="placeholder"><h3>No failure log yet</h3><p><code>evals/FAILURES.md</code> is rendered here once it exists.</p></div>`}
        </section>
      </div>
      <aside><div class="aside-box">
        <h2>What is measured</h2>
        <dl class="metric-defs">
          <dt>Extraction</dt><dd>Each OM field against the truth file, and whether its citation is valid: quote found on the page, and the page or value right.</dd>
          <dt>Rent roll and statement</dt><dd>Units found, summary rows wrongly counted as units, unit fields, totals, statement categories and period.</dd>
          <dt>Discrepancies</dt><dd>Recall and precision against the planted list, by catalogue id. Clean deals measure false flags.</dd>
          <dt>Underwriting inputs</dt><dd>The engine on extracted inputs against the engine on the true building's inputs.</dd>
          <dt>Engine arithmetic</dt><dd>Tied out to an independent Excel model. <a href="#/evals/tieout">Tie-out</a></dd>
          <dt>Verdict</dt><dd>Matches the mandate outcome computed on the true building.</dd>
          <dt>Memo grounding</dt><dd>Share of memo numbers that match a fact-sheet value. A memo below 100% is withheld.</dd>
          <dt>Stability</dt><dd>The same deals run repeatedly: verdicts, discrepancy sets and walk-away prices.</dd>
        </dl>
        <p class="small"><a href="${esc(m.repo_url)}/blob/main/evals/README.md" target="_blank" rel="noopener">Scoring rules in full</a></p>
      </div></aside>
    </div>
  </div>`;
}

async function tieout(m) {
  setTitle("Engine tie-out");
  const md = (m.evals?.files || []).includes("tieout/README.md") ? await data.evalText("tieout/README.md").catch(() => null) : null;
  const link = (url) => {
    const u = url.trim();
    if (/^(https?:|mailto:|#)/i.test(u)) return u;
    if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return null;
    return `${m.repo_url}/blob/main/evals/tieout/${u.replace(/^\.\//, "")}`;
  };
  app.innerHTML = `<div class="page"><div class="brief-layout">
    <article class="prose"><p class="small"><a href="#/evals">Evals</a> / engine tie-out</p>
      ${md ? renderMarkdown(md, { link }) : "<h1>Engine tie-out</h1><p>The tie-out README is not in site/data yet.</p>"}
      <p class="small"><a href="${esc(m.repo_url)}/tree/main/evals/tieout" target="_blank" rel="noopener">The workbook and engine output in the repository</a></p>
      <p class="notice-line">${SYNTH}</p></article>
    <aside><div class="aside-box"><h2>Why it matters</h2><p class="small">The eval scores measure reading and reconciling. This checks the arithmetic underneath: a workbook built from the engine's written method, with no engine code, recomputes every figure for one deal.</p></div></aside>
  </div></div>`;
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
