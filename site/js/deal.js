// The deal view: memo on the left, evidence on the right, and tabs for the working detail.

import * as data from "./data.js";
import { esc, aed, aedFull, k, pct, pctPts, mult, int, num, date, duration, usd, words, sentence, chip, sev, prov, statusMark, byUnit, verdictClass, testName, humanReason } from "./format.js";
import { renderMarkdown } from "./md.js";
import { EvidencePanel, sourceButton, testValue } from "./evidence.js";
import * as store from "./store.js";

const TABS = [
  ["memo", "Memo"],
  ["discrepancies", "Discrepancies"],
  ["underwriting", "Underwriting"],
  ["mandate", "Mandate fit"],
  ["documents", "Documents"],
  ["run", "Run details"],
];

export async function renderDeal(app, manifest, dealId, tab, params) {
  app.innerHTML = `<div class="loading">Loading ${esc(dealId)}…</div>`;
  let r;
  try {
    r = await data.run(dealId);
  } catch {
    const pkg = (manifest.package_index || []).find((d) => d.deal_id === dealId);
    document.title = "Not screened | Deal Screen";
    app.innerHTML = `<div class="page narrow"><h1>${esc(pkg?.building_name || dealId)}</h1>
      <p>${pkg ? "This package has been received but its screening run is not recorded yet." : "No deal with this id."}</p>
      <p><a href="#/inbox">Back to the deal inbox</a></p><p class="notice-line">Synthetic data; the property is fictional.</p></div>`;
    return null;
  }
  if (!TABS.some(([id]) => id === tab)) tab = "memo";
  const out = r.underwriting?.outputs || null;
  const met = (n) => out?.metrics?.[n]?.value ?? null;
  const fit = r.mandate_fit || {};
  const name = r.deal?.building_name || dealId;
  const th = manifest.mandate || {};
  const wa = out?.walk_away?.price_aed?.value ?? null;
  const asking = met("price_aed") ?? r.fact_sheet?.["deal.asking_price_aed"]?.value ?? null;
  const loc = r.fact_sheet?.["deal.location"]?.value || r.deal?.market_area || "";
  const units = met("unit_count") ?? r.rent_roll_summary?.summary?.unit_count;
  document.title = `${name} | Deal Screen`;

  const cmpCls = (v, t) => (v == null || t == null ? "" : v >= t ? "meet" : "miss");
  const counts = { discrepancies: (r.discrepancies || []).length, mandate: (fit.tests || []).filter((t) => t.status !== "pass").length, documents: (r.documents || []).length };

  app.innerHTML = `
  <div class="deal-head">
    <div class="deal-head-in">
      <div>
        <div class="crumbs"><a href="#/inbox">Deal inbox</a> / synthetic deal, fictional property</div>
        <h1>${esc(name)} ${chip(fit.verdict, true)}</h1>
        <div class="where">${esc(loc)}${units ? `, ${int(units)} units` : ""}. Package of ${int((r.documents || []).length)} documents as received from the broker; all names and figures are synthetic.</div>
      </div>
      <dl class="keyline">
        <div><dt>Asking</dt><dd>${esc(aed(asking))}</dd></div>
        <div><dt>Walk-away</dt><dd class="${wa != null && asking != null ? (wa >= asking ? "meet" : "miss") : ""}">${esc(aed(wa))}</dd></div>
        <div><dt>Yield on cost</dt><dd class="${cmpCls(met("going_in_net_yield_on_cost"), th.min_going_in_net_yield_on_cost)}">${esc(pct(met("going_in_net_yield_on_cost")))}</dd></div>
        <div><dt>Levered IRR</dt><dd class="${cmpCls(met("levered_irr_pre_tax"), th.target_levered_irr)}">${esc(pct(met("levered_irr_pre_tax")))}</dd></div>
        <div><dt>DSCR Y1</dt><dd class="${cmpCls(met("dscr_year1"), th.min_dscr_year1)}">${esc(mult(met("dscr_year1")))}</dd></div>
      </dl>
    </div>
    <div class="tabs" role="tablist" aria-label="Deal sections">
      ${TABS.map(([id, label]) => `<button type="button" role="tab" id="tab-${id}" aria-controls="tabpanel" data-tab="${id}" aria-selected="${id === tab}" tabindex="${id === tab ? 0 : -1}">${label}${counts[id] ? `<span class="count">${counts[id]}</span>` : ""}</button>`).join("")}
    </div>
  </div>
  <div class="split">
    <div class="main" id="tabpanel" role="tabpanel" aria-labelledby="tab-${tab}" tabindex="-1"></div>
    <aside class="evidence" id="evidence" aria-label="Evidence panel" aria-live="off"></aside>
  </div>`;

  const main = app.querySelector("#tabpanel");
  const panelEl = app.querySelector("#evidence");
  let lastCite = null;
  const panel = new EvidencePanel(panelEl, r, {
    onTab: (t, focus) => select(t, focus),
    onClose: () => { lastCite?.focus(); },
  });

  bindDecisions(main, dealId);
  const views = { memo: memoView, discrepancies: discView, underwriting: uwView, mandate: mandateView, documents: docsView, run: runView };

  function select(t, focus) {
    tab = t;
    for (const b of app.querySelectorAll('[role="tab"]')) {
      const on = b.dataset.tab === t;
      b.setAttribute("aria-selected", on);
      b.tabIndex = on ? 0 : -1;
    }
    main.setAttribute("aria-labelledby", `tab-${t}`);
    main.innerHTML = views[t](r, { manifest, th, dealId });
    history.replaceState(null, "", `#/deal/${encodeURIComponent(dealId)}${t === "memo" ? "" : "/" + t}`);
    if (focus) {
      const el = main.querySelector(`#${CSS.escape(focus)}`);
      if (el) { el.scrollIntoView({ block: "start" }); el.setAttribute("tabindex", "-1"); el.focus({ preventScroll: true }); }
    } else {
      window.scrollTo({ top: 0 });
    }
  }

  // tabs: click and arrow keys
  const tablist = app.querySelector('[role="tablist"]');
  tablist.addEventListener("click", (e) => {
    const b = e.target.closest('[role="tab"]');
    if (b) select(b.dataset.tab);
  });
  tablist.addEventListener("keydown", (e) => {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    let j = null;
    if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
    if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
    if (e.key === "Home") j = 0;
    if (e.key === "End") j = tabs.length - 1;
    if (j !== null) { e.preventDefault(); tabs[j].focus(); select(tabs[j].dataset.tab); tabs[j].focus(); }
  });

  // anything in the main pane with data-ev drives the evidence panel
  main.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ev]");
    if (!b) return;
    if (b.classList.contains("cite") || b.classList.contains("thumb")) {
      for (const x of main.querySelectorAll('[aria-pressed="true"].cite, [aria-pressed="true"].thumb')) x.setAttribute("aria-pressed", "false");
      b.setAttribute("aria-pressed", "true");
      lastCite = b;
    }
    panel.dispatch(b);
  });

  const onKey = (e) => {
    if (e.key === "Escape" && panelEl.classList.contains("open")) {
      for (const x of main.querySelectorAll('[aria-pressed="true"].cite')) x.setAttribute("aria-pressed", "false");
      panel.empty();
      lastCite?.focus();
    }
  };
  document.addEventListener("keydown", onKey);

  select(tab);
  const f = params.get("f");
  if (f) {
    const btn = main.querySelector(`.cite[data-fact="${CSS.escape(f)}"]`);
    if (btn) btn.click(); else panel.showFact(f);
  }
  return { cleanup: () => document.removeEventListener("keydown", onKey) };
}

// ---------------------------------------------------------------- memo

function citeHtml(r) {
  return (id, label) => {
    const f = r.fact_sheet?.[id];
    const what = f ? f.label : id;
    if (!label) return `<button type="button" class="cite mark" data-ev="fact" data-fact="${esc(id)}" aria-label="Source: ${esc(what)}" aria-pressed="false"></button>`;
    return `<button type="button" class="cite" data-ev="fact" data-fact="${esc(id)}" aria-label="${label}: show source, ${esc(what)}" aria-pressed="false">${label}</button>`;
  };
}

function memoView(r, { th }) {
  const memo = r.memo || {};
  const fit = r.mandate_fit || {};
  const out = r.underwriting?.outputs;
  const wa = out?.walk_away;
  const md = memo.markdown;
  const cite = citeHtml(r);
  const anchors = (md || memo.rejected_draft || "").match(/\[\[[^\]]+\]\]/g) || [];
  const attempts = memo.attempts || [];
  const passedOn = attempts.findIndex((a) => !(a.errors || []).length) + 1;
  const model = r.meta?.model;
  const disc = wa?.discount_to_asking?.value;
  const vb = `<div class="verdict-block">
      ${chip(fit.verdict, true)}
      <span class="wa">${wa?.price_aed?.value != null ? `Walk-away <b>${cite("uw.walk_away_price_aed", esc(aed(wa.price_aed.value)))}</b> against asking <b>${cite("deal.asking_price_aed", esc(aed(r.fact_sheet?.["deal.asking_price_aed"]?.value)))}</b>${disc != null ? `, ${disc >= 0 ? `${esc(pct(disc, 1))} below` : `${esc(pct(-disc, 1))} above`} asking` : ""}. Set by ${esc(constraintText(wa.binding_constraint, th))}.` : "Not underwritten: no walk-away price."}</span>
    </div>`;
  let body;
  if (md) {
    body = `<div class="memo-meta"><span>Drafted by ${esc(model || "the model")} from the fact sheet only.</span><span>${int(anchors.length)} figures, each checked by code against its fact${passedOn > 1 ? ` (passed on attempt ${passedOn})` : ""}.</span></div>
      <article class="memo">${renderMarkdown(md, { cite })}</article>`;
  } else {
    const errs = attempts.at(-1)?.errors || [];
    body = `<div class="error-box" role="status"><b>Memo withheld.</b> The model's draft failed the number check twice, so the screen does not ship it. ${int(errs.length)} figure${errs.length === 1 ? "" : "s"} did not match the fact sheet on the last attempt. The underwriting, discrepancies and mandate fit below are computed by code and are unaffected.</div>
      <details style="margin-top:14px"><summary class="small">Problems the checker found</summary><ul class="small">${errs.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></details>
      ${memo.rejected_draft ? `<details style="margin-top:8px"><summary class="small">Show the rejected draft (not for use)</summary><article class="memo" style="opacity:.8;margin-top:12px">${renderMarkdown(memo.rejected_draft, { cite })}</article></details>` : ""}`;
  }
  return vb + body + `<p class="notice-line" style="margin-top:28px">Synthetic deal: the property, broker, tenants and figures are fictional.</p>`;
}

function constraintText(c, th) {
  if (c === "levered_irr") return `the ${pct(th.target_levered_irr)} levered IRR target`;
  if (c === "dscr_year1") return `the ${mult(th.min_dscr_year1)} Year-1 DSCR floor`;
  if (c === "both") return "both the IRR target and the DSCR floor";
  return words(c || "the mandate");
}

// ---------------------------------------------------------------- discrepancies

const DECISIONS = [["accepted", "Accept"], ["overridden", "Override"], ["info_requested", "Request info"]];
const DECISION_TEXT = { accepted: "Accepted", overridden: "Overridden", info_requested: "Information requested" };

function srcValue(v, s) {
  if (v == null) return "";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return esc(v.map((x) => (typeof x === "object" ? JSON.stringify(x) : words(x))).join(", "));
  if (typeof v === "object") return esc(Object.entries(v).filter(([, x]) => x != null).map(([a, b]) => `${sentence(a)}: ${words(b)}`).join("; "));
  if (typeof v !== "number") return esc(words(v));
  const lbl = (s.label || "").toLowerCase();
  if (/price per sq|psf/.test(lbl)) return esc(`AED ${num(v)} psf`);
  if (/\b(bua|nsa|sq ?ft|sqm)\b/.test(lbl) && !/rent|price/.test(lbl)) return esc(`${num(v)} sq ft`);
  if (/\bunits?\b|count|tenanc/.test(lbl) && Number.isInteger(v) && v < 5000) return esc(int(v));
  if (Math.abs(v) >= 1000) return esc(aedFull(v));
  if (Math.abs(v) <= 1.5 && !Number.isInteger(v)) return esc(pct(v, 1));
  if (/occupancy|share|yield|uplift|change|ratio/.test(lbl) && Math.abs(v) <= 1.5) return esc(pct(v, 1));
  return esc(num(v, Number.isInteger(v) ? 0 : 2));
}

function reliedIndex(r, d) {
  const used = r.deal?.documents_used || {};
  const map = { rent_roll: used.rent_roll, om: used.om, operating_statement: used.operating_statement, engine: "engine" };
  const target = map[d.relied_on];
  if (!target) return -1;
  return (d.sources || []).findIndex((s) => s.doc === target);
}

function impactText(imp) {
  if (!imp) return "Not quantified.";
  const parts = [];
  const metric = imp.metric ? words(imp.metric).replace(/\bnoi\b/i, "NOI") : "";
  if (typeof imp.delta_aed === "number") parts.push(`${metric ? metric + ": " : ""}${imp.delta_aed > 0 ? "+" : ""}${aed(imp.delta_aed)}`);
  if (typeof imp.walk_away_delta_aed === "number") parts.push(`walk-away price ${imp.walk_away_delta_aed > 0 ? "+" : ""}${aed(imp.walk_away_delta_aed)}`);
  if (typeof imp.delta === "number") parts.push(`${metric ? metric + ": " : ""}${pctPts(imp.delta, 1)}`);
  if (typeof imp.value === "number" && !parts.length) parts.push(`${metric}: ${imp.value <= 1.5 ? pct(imp.value, 1) : aed(imp.value)}`);
  let s = parts.join("; ") || metric || "Not quantified";
  if (imp.basis) s += `. ${sentence(imp.basis)}`;
  return s.replace(/\.\s*$/, "") + ".";
}

function discView(r, { dealId }) {
  const list = r.discrepancies || [];
  const dec = store.decisions(dealId);
  if (!list.length) return `<div class="placeholder"><h3>No discrepancies found</h3><p>The three documents agree on every rule-tested quantity, and the model review raised nothing it could back with a verified quote.</p></div>`;
  const reviewed = list.filter((d) => dec[d.id]).length;
  const rejected = r.rejected_model_findings || [];
  return `
  <div class="review-bar" id="review-bar">
    <span><b>${reviewed}</b> of ${list.length} reviewed</span>
    <span class="meter" aria-hidden="true"><i style="width:${(reviewed / list.length) * 100}%"></i></span>
    <span class="muted">Decisions are saved in this browser only.</span>
    ${reviewed ? `<button type="button" class="btn ghost sm" data-reset>Clear my decisions</button>` : ""}
  </div>
  ${list.map((d, i) => discCard(r, d, dec[d.id], i)).join("")}
  ${rejected.length ? `<p class="small muted">${rejected.length} model finding${rejected.length === 1 ? " was" : "s were"} rejected because no quote could be verified on its page; rejected findings are recorded in Run details, never shown as discrepancies.</p>` : ""}
  <p class="notice-line">Synthetic deal: discrepancies were planted in fictional documents to test the screen.</p>`;
}

function discCard(r, d, decision, i) {
  const rel = reliedIndex(r, d);
  const sources = (d.sources || []).map((s, j) => {
    const where = s.doc === "engine" ? "Engine calculation" : `${s.doc}${s.page ? `, page ${s.page}` : ""}${s.cell ? `, ${s.cell}` : ""}`;
    const btn = sourceButton(s, s.page ? `Show page ${s.page}` : s.cell ? "Show cells" : "");
    return `<div class="src${j === rel ? " relied" : ""}">
      <div class="tag"><span>${esc(where)}</span>${j === rel ? '<span class="relied-tag">Relied on</span>' : ""}</div>
      ${s.value != null ? `<div class="val">${srcValue(s.value, s)}</div>` : ""}
      ${s.label && s.label !== "verified quote" ? `<div class="lbl">${esc(sentence(s.label))}</div>` : ""}
      ${s.quote ? `<div class="q">“${esc(s.quote)}”</div>` : ""}
      ${btn ? `<div class="open">${btn}</div>` : ""}
    </div>`;
  }).join("");
  const state = decision?.state;
  const showNote = state === "overridden" || state === "info_requested";
  return `<article class="disc ${esc(d.severity)}" id="${esc(d.id)}" aria-labelledby="dh-${i}">
    <div class="disc-top">${sev(d.severity)}<h3 id="dh-${i}">${esc(d.title)}</h3><span class="by">${esc(sentence(words(d.id)))}, found by ${esc(d.detected_by === "rule" ? "a code rule" : d.detected_by === "model" ? "the model review, quote verified by code" : "a code rule and the model review")}</span></div>
    <div class="vs">${sources}</div>
    <dl>
      <dt>Relied on</dt><dd><b>${esc(sentence(words(d.relied_on)))}</b>. ${esc(d.why)}</dd>
      <dt>Impact</dt><dd>${esc(impactText(d.impact))}</dd>
      <dt>Analyst action</dt><dd>${esc(d.analyst_action)}</dd>
      ${(d.unverified_evidence || []).length ? `<dt>Not verified</dt><dd class="muted">${d.unverified_evidence.length} further quote${d.unverified_evidence.length === 1 ? "" : "s"} from the model could not be found on the cited page and ${d.unverified_evidence.length === 1 ? "was" : "were"} dropped.</dd>` : ""}
    </dl>
    <div class="actions" data-disc="${esc(d.id)}" role="group" aria-label="Decision on: ${esc(d.title)}">
      ${DECISIONS.map(([v, l]) => `<button type="button" class="act" data-decide="${v}" aria-pressed="${state === v}">${l}</button>`).join("")}
      ${showNote ? `<label class="visually-hidden" for="note-${i}">Note</label><input type="text" id="note-${i}" data-note placeholder="${state === "overridden" ? "What you are relying on instead, and why" : "What you asked for, and from whom"}" value="${esc(decision?.note || "")}">` : ""}
      <span class="state" aria-live="polite">${state ? `${DECISION_TEXT[state]} ${esc(fmtWhen(decision.at))}` : "Not reviewed"}</span>
    </div>
  </article>`;
}

function fmtWhen(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function bindDecisions(main, dealId) {
  main.addEventListener("click", (e) => {
    const b = e.target.closest("[data-decide]");
    if (b) {
      const box = b.closest("[data-disc]");
      const id = box.dataset.disc;
      const cur = store.decisions(dealId)[id];
      const next = cur?.state === b.dataset.decide ? null : b.dataset.decide;
      store.setDecision(dealId, id, next, cur?.note);
      rerender(main, dealId, id, next === "overridden" || next === "info_requested");
      return;
    }
    if (e.target.closest("[data-reset]")) {
      store.clearDeal(dealId);
      rerender(main, dealId);
    }
  });
  main.addEventListener("change", (e) => {
    const inp = e.target.closest("[data-note]");
    if (inp) store.setNote(dealId, inp.closest("[data-disc]").dataset.disc, inp.value);
  });
}

function rerender(main, dealId, focusId, focusNote) {
  // re-render only the decision rows and the counter, keeping scroll and focus
  data.run(dealId).then((r) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = discView(r, { dealId });
    main.querySelector("#review-bar").replaceWith(tmp.querySelector("#review-bar"));
    for (const box of main.querySelectorAll("[data-disc]")) {
      const fresh = tmp.querySelector(`[data-disc="${CSS.escape(box.dataset.disc)}"]`);
      if (fresh) box.replaceWith(fresh);
    }
    if (focusId) {
      const box = main.querySelector(`[data-disc="${CSS.escape(focusId)}"]`);
      (focusNote ? box?.querySelector("[data-note]") : null)?.focus() || box?.querySelector('[aria-pressed="true"]')?.focus() || box?.querySelector("[data-decide]")?.focus();
    }
  });
}

// ---------------------------------------------------------------- underwriting

function mcite(name, label, ev = "metric") {
  return `<button type="button" class="cite inline-num" data-ev="${ev}" data-metric="${esc(name)}" aria-label="${esc(label)}: show calculation" aria-pressed="false">${esc(label)}</button>`;
}

const CF_LINES = [
  ["potential_rental_income", "Potential rental income", ""],
  ["downtime_loss", "Downtime on turnover and lease-up", "neg ind"],
  ["gross_rental_income", "Gross rental income", "sub"],
  ["master_lease_income", "Master lease income", ""],
  ["other_income", "Other income", ""],
  ["gross_income", "Gross income", "total"],
  ["structural_vacancy", "Structural vacancy top-up", "neg ind"],
  ["collection_loss", "Collection loss", "neg ind"],
  ["effective_gross_income", "Effective gross income", "total"],
  ["management_fee", "Management fee", "neg ind"],
  ["operating_expenses", "Operating expenses", "neg ind"],
  ["leasing_fees", "Leasing fees", "neg ind"],
  ["input_vat", "Input VAT on costs", "neg ind"],
  ["total_operating_costs", "Total operating costs", "neg sub"],
  ["noi", "Net operating income", "total"],
];

function uwView(r, { th }) {
  const u = r.underwriting || {};
  const o = u.outputs;
  if (!o) return `<div class="error-box"><b>Not underwritten.</b> ${esc(u.error || "")}</div><p class="small">Engine tests in the mandate are marked unknown, which counts against the deal.</p>`;
  const m = (n) => o.metrics?.[n]?.value ?? null;
  const kpi = (label, name, fmt, t, tLabel) => {
    const v = m(name);
    const cls = t == null || v == null ? "" : v >= t ? "meet" : "miss";
    return `<div class="kpi"><dt>${esc(label)}</dt><dd><span class="${cls}">${mcite(name, fmt(v))}</span>${t != null ? `<span class="vs-t">${tLabel} ${esc(fmt(t))}${cls === "miss" ? ", missed" : cls === "meet" ? ", met" : ""}</span>` : ""}</dd></div>`;
  };
  const wa = o.walk_away || {};
  const waP = wa.price_aed?.value, ask = m("price_aed");
  const yc = o.om_yield_check;
  const cf = o.cash_flow || {};
  const years = cf.years || [];
  const inHold = cf.in_hold || years.map(() => true);
  const cfRows = CF_LINES.filter(([key]) => cf.lines?.[key] && !(key === "master_lease_income" && cf.lines[key].values.every((v) => !v))).map(([key, label, cls]) => {
    const vals = cf.lines[key].values;
    const neg = cls.includes("neg");
    return `<tr class="${cls.replace("neg", "").trim()}"><td>${esc(label)}</td>${vals.map((v, i) => `<td class="n${inHold[i] ? "" : " fwd"}">${esc(k(neg ? -v : v))}</td>`).join("")}</tr>`;
  }).join("");
  const ds = o.debt_schedule?.lines || {};
  const rc = o.returns_cash_flows?.lines || {};
  const debtRows = ds.debt_service ? `<tr class="ind"><td>Debt service</td>${years.map((_, i) => `<td class="n${inHold[i] ? "" : " fwd"}">${i < ds.debt_service.values.length ? esc(k(-ds.debt_service.values[i])) : ""}</td>`).join("")}</tr>` : "";
  const levRow = rc.levered_pre_tax ? `<tr class="total"><td>Levered cash flow, pre-tax <span class="muted small">(final year includes sale)</span></td>${years.map((_, i) => `<td class="n${inHold[i] ? "" : " fwd"}">${i + 1 < rc.levered_pre_tax.values.length ? esc(k(rc.levered_pre_tax.values[i + 1])) : ""}</td>`).join("")}</tr>` : "";

  // walk-away price rail
  let rail = "";
  if (waP != null && ask != null) {
    const lo = Math.min(waP, ask) * 0.9, hi = Math.max(waP, ask) * 1.05;
    const x = (v) => ((v - lo) / (hi - lo)) * 100;
    const [a, b] = [Math.min(waP, ask), Math.max(waP, ask)];
    rail = `<div class="price-rail" role="img" aria-label="Walk-away ${esc(aed(waP))} against asking ${esc(aed(ask))}">
      <div class="track"></div>
      <div class="gap${waP >= ask ? " ok" : ""}" style="left:${x(a)}%;width:${x(b) - x(a)}%"></div>
      <div class="pt wa" style="left:${x(waP)}%"><b>${esc(aed(waP))}</b>walk-away</div>
      <div class="pt below" style="left:${x(ask)}%"><b>${esc(aed(ask))}</b>asking</div>
    </div>`;
  }

  // OM yield vs buyer basis ladder
  let ladder = `<p class="muted">The OM states no headline yield, so there is nothing to reconcile.</p>`;
  if (yc) {
    const rows = [
      ["stated_yield", "<b>OM headline</b>, as printed", "om"],
      ["reproduced_on_om_basis", "Reproduced on the OM's own basis", ""],
      ["stated_income_on_price", "OM income on price", ""],
      ["stated_income_on_total_cost", "OM income on price plus costs", ""],
      ["buyer_net_on_price", "Net (Year-1 NOI) on price", ""],
      ["buyer_net_on_total_cost", "<b>Buyer's basis</b>: net on price plus costs", "buyer"],
    ].filter(([key]) => yc[key]?.value != null);
    const max = Math.max(...rows.map(([key]) => yc[key].value), th.min_going_in_net_yield_on_cost || 0) * 1.12;
    const tgt = th.min_going_in_net_yield_on_cost;
    ladder = `<p>${esc(yc.summary || "")}</p>
      <div class="ladder" role="list">${rows.map(([key, label, cls]) => `<div class="lab" role="listitem">${label}</div>
        <div class="barcell" aria-hidden="true"><div class="bar ${cls}" style="width:${(yc[key].value / max) * 100}%"></div>${tgt ? `<div class="target" style="left:${(tgt / max) * 100}%"></div>` : ""}</div>
        <div class="val">${mcite("oy." + key, pct(yc[key].value))}</div>`).join("")}</div>
      ${tgt ? `<div class="ladder-foot"><i></i> mandate minimum yield on cost, ${esc(pct(tgt))}. OM basis: ${esc(words(yc.om_basis?.measure))} on ${esc(words(yc.om_basis?.stated_on || yc.om_basis?.on))}${yc.om_basis?.assumed ? " (denominator assumed: the OM does not say)" : ""}.</div>` : ""}`;
  }

  // sensitivity grid
  const sens = o.sensitivity || {};
  const cell = (rs, eb) => (sens.cells || []).find((c) => c.rent_shift === rs && c.exit_yield_shift_bps === eb);
  const tIrr = th.target_levered_irr;
  const grid = (sens.rent_shifts || []).length ? `<table class="sens">
      <caption>Levered IRR pre-tax, with Year-1 DSCR. Green meets the ${esc(pct(tIrr))} target; the outlined cell is the base case.</caption>
      <thead><tr><th></th>${sens.exit_yield_shifts_bps.map((b) => `<th scope="col">Exit yield ${b === 0 ? "base" : (b > 0 ? "+" : "−") + Math.abs(b) + " bps"}<br><span class="muted xs">${esc(pct(cell(0, b)?.exit_yield, 2))}</span></th>`).join("")}</tr></thead>
      <tbody>${sens.rent_shifts.map((rs) => `<tr><th scope="row" class="row">Market rent ${rs === 0 ? "base" : (rs > 0 ? "+" : "−") + Math.abs(rs * 100) + "%"}</th>${sens.exit_yield_shifts_bps.map((b) => {
        const c = cell(rs, b);
        if (!c) return "<td></td>";
        const ok = tIrr != null && c.levered_irr_pre_tax != null && c.levered_irr_pre_tax >= tIrr;
        return `<td class="${ok ? "ok" : "bad"}${rs === 0 && b === 0 ? " base" : ""}"><span class="irr"><span class="ico" aria-hidden="true">${ok ? "✓" : "✗"}</span>${esc(pct(c.levered_irr_pre_tax, 1))}</span><span class="dscr">DSCR ${esc(mult(c.dscr_year1))}</span><span class="visually-hidden">${ok ? "meets target" : "misses target"}</span></td>`;
      }).join("")}</tr>`).join("")}</tbody></table>` : "";

  // expiry windows
  const ew = o.expiry_windows;
  const lim = 0.4;
  const limit = (r.mandate_fit?.tests || []).find((t) => t.name === "max_lease_expiry_share_in_any_quarter")?.threshold ?? lim;
  const expiry = ew?.windows?.length ? `<div class="expiry">${ew.windows.map((w) => `<div>${esc(date(w.start))} to ${esc(date(w.end))}</div>
      <div class="barcell" aria-hidden="true"><div class="bar${w.share > limit ? " over" : ""}" style="width:${Math.min(100, (w.share / Math.max(limit * 1.6, ...ew.windows.map((x) => x.share))) * 100)}%"></div><div class="limit" style="left:${(limit / Math.max(limit * 1.6, ...ew.windows.map((x) => x.share))) * 100}%"></div></div>
      <div class="n tnum" style="text-align:right">${esc(pct(w.share, 1))}</div>`).join("")}</div>
      <p class="ladder-foot"><i></i> mandate limit, ${esc(pct(limit, 0))} of in-place rent in any quarter. Windows run from the rent roll date, ${esc(date(ew.basis_date))}.</p>` : "";

  // acquisition costs
  const ac = o.acquisition_costs || {};
  const acRows = [["dld_transfer_fee", "DLD transfer fee (4%)"], ["dld_admin", "DLD admin"], ["trustee_fee", "Trustee fee"], ["broker_fee", "Broker fee"], ["broker_fee_vat", "VAT on broker fee"], ["transfer_costs", "Transfer costs", "sub"], ["mortgage_registration", "Mortgage registration"], ["total", "Total acquisition costs", "total"]]
    .filter(([key]) => ac[key]).map(([key, label, cls]) => `<tr class="${cls || ""}"><td>${esc(label)}</td><td class="n">${mcite("acq." + key, aedFull(ac[key].value))}</td></tr>`).join("");

  // gap-filling inputs
  const inputs = o.inputs || {};
  const opexIn = Object.entries(inputs).filter(([key]) => key.startsWith("deal.opex_aed."));
  const defaults = opexIn.filter(([, v]) => v.provenance === "default");
  const opexTbl = opexIn.length ? `<table class="tbl dense"><thead><tr><th>Cost line</th><th>Source</th><th class="n">Year 1</th></tr></thead><tbody>${opexIn.map(([key, v]) =>
    `<tr><td>${esc(sentence(key.split(".").pop()))}</td><td>${prov(v.provenance)}${v.note ? ` <span class="muted xs">${esc(v.note)}</span>` : ""}</td><td class="n">${v.value == null ? "n/a" : esc(aedFull(v.value))}</td></tr>`).join("")}</tbody></table>` : "";

  return `
  <section class="section"><h2>Key metrics</h2>
    <p class="note">Year 1 is ${esc(date(o.analysis_start))} onward; ${int(o.hold_years)}-year hold. Select a figure to see the inputs it depends on and where each came from.</p>
    <dl class="kpis">
      ${kpi("Year-1 NOI", "noi_year1", aed)}
      ${kpi("Net yield on cost", "going_in_net_yield_on_cost", pct, th.min_going_in_net_yield_on_cost, "min")}
      ${kpi("Net yield on price", "going_in_net_yield_on_price", pct)}
      ${kpi("Year-1 DSCR", "dscr_year1", mult, th.min_dscr_year1, "min")}
      ${kpi("Levered IRR, pre-tax", "levered_irr_pre_tax", pct, th.target_levered_irr, "target")}
      ${kpi("Equity multiple, pre-tax", "levered_equity_multiple_pre_tax", mult, th.target_equity_multiple, "target")}
      ${kpi("Levered IRR, post-tax", "levered_irr_post_tax", pct)}
      ${kpi("Unlevered IRR, pre-tax", "unlevered_irr_pre_tax", pct)}
      ${kpi("Price per sq ft NSA", "price_per_sqft_nsa", (v) => (v == null ? "n/a" : `AED ${int(v)}`))}
      ${kpi("Total cost", "total_cost_aed", aed)}
      ${kpi("Loan", "loan_aed", aed)}
      ${kpi("Equity", "equity_aed", aed)}
      ${kpi("Debt yield", "debt_yield_year1", pct)}
      ${kpi("Breakeven occupancy", "breakeven_occupancy_dscr_1", pct)}
      ${kpi("Exit yield", "exit_yield", pct)}
      ${kpi("Gross exit value", "gross_exit_value_aed", aed)}
    </dl>
  </section>

  <section class="section" id="walk-away"><h2>Walk-away price</h2>
    <div class="walkaway">
      <div>
        <div class="big">${mcite("walk_away_price_aed", aed(waP))}</div>
        <div class="vsask">${wa.discount_to_asking?.value != null ? (wa.discount_to_asking.value >= 0 ? `${esc(pct(wa.discount_to_asking.value, 1))} below the asking price` : `${esc(pct(-wa.discount_to_asking.value, 1))} above the asking price: the deal clears the mandate at asking`) : ""}</div>
        ${rail}
      </div>
      <div>
        <p>The highest price, on a AED 10,000 grid, at which the deal still meets the ${esc(pct(wa.target_levered_irr?.value))} levered IRR target and the ${esc(mult(wa.dscr_floor?.value))} Year-1 DSCR floor. <b>Binding constraint: ${esc(constraintText(wa.binding_constraint, th))}.</b></p>
        <table class="tbl dense"><thead><tr><th></th><th class="n">Levered IRR</th><th class="n">DSCR Y1</th></tr></thead><tbody>
          <tr><td>At ${esc(aed(waP))}</td><td class="n">${mcite("wa.levered_irr_at_price", pct(wa.levered_irr_at_price?.value))}</td><td class="n">${mcite("wa.dscr_at_price", mult(wa.dscr_at_price?.value))}</td></tr>
          <tr><td>AED 10,000 higher</td><td class="n">${esc(pct(wa.levered_irr_one_step_above?.value))}</td><td class="n">${esc(mult(wa.dscr_one_step_above?.value))}</td></tr>
          <tr><td>Yield on cost at walk-away</td><td class="n" colspan="2">${esc(pct(wa.going_in_net_yield_on_cost_at_price?.value))}</td></tr>
        </tbody></table>
      </div>
    </div>
  </section>

  <section class="section" id="om-yield"><h2>OM-stated yield against the buyer's basis</h2>
    <p class="note">Brokers quote yields gross, on asking price, and call them net. The engine recomputes the OM's figure on the OM's own basis, then on a buyer's basis: Year-1 NOI after the costs the buyer bears, over price plus DLD fee and acquisition costs.</p>
    ${ladder}
  </section>

  <section class="section" id="cash-flow"><h2>Year-by-year cash flow</h2>
    <p class="note">AED thousands. Costs in brackets. Year ${years.length} is shown shaded: its NOI is the forward income the exit is priced on, not a year of the hold.</p>
    <div class="tbl-wrap"><table class="tbl dense cf"><thead><tr><th scope="col">AED '000</th>${years.map((y, i) => `<th scope="col" class="yr${inHold[i] ? "" : " fwd"}">Year ${y}<br><span class="muted xs">${esc((cf.period_start?.[i] || "").slice(0, 4))}${inHold[i] ? "" : " exit"}</span></th>`).join("")}</tr></thead>
      <tbody>${cfRows}${debtRows}${levRow}</tbody></table></div>
  </section>

  <section class="section" id="sensitivity"><h2>Sensitivity</h2>
    <p class="note">Exit yield against market rent. The rent shift moves every year's market level, so it reaches renewals, re-lets and the exit; in-place rents hold until they roll.</p>
    ${grid}
  </section>

  <div class="two-col">
    <section class="section"><h2>Acquisition costs</h2>
      <table class="tbl dense"><tbody>${acRows}</tbody></table>
    </section>
    <section class="section"><h2>Lease expiry by quarter</h2>
      <p class="note">Share of in-place rent expiring in each of the next four quarters.</p>
      ${expiry}
    </section>
  </div>

  <section class="section"><h2>Operating costs and where each came from</h2>
    <p class="note">${defaults.length ? `${defaults.length} cost line${defaults.length === 1 ? " is" : "s are"} missing from the seller's statement and filled from mandate defaults per sq ft of NSA.` : "Every standard cost line is in the seller's statement."} Unknown facts count against a deal, never for it.</p>
    ${opexTbl}
  </section>
  ${(o.warnings || []).length ? `<section class="section"><h2>Engine warnings</h2><ul class="small">${o.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></section>` : ""}`;
}

// ---------------------------------------------------------------- mandate fit

function mandateView(r) {
  const fit = r.mandate_fit || {};
  const tests = fit.tests || [];
  const row = (t) => `<tr>
      <td><b>${esc(testName(t.name))}</b></td>
      <td>${t.kind === "hard" ? "Hard" : "Soft"}</td>
      <td class="${Array.isArray(t.threshold) ? "" : "n"}">${esc(testValue(t.name, t.threshold))}</td>
      <td class="${Array.isArray(t.threshold) ? "" : "n"}">${esc(testValue(t.name, t.actual))}</td>
      <td>${statusMark(t.status)}</td>
      <td class="small">${esc(t.reason)}<span class="muted"> Source: ${esc(words(t.source))}.</span></td>
    </tr>`;
  const hard = tests.filter((t) => t.kind === "hard"), soft = tests.filter((t) => t.kind !== "hard");
  const facts = fit.deal_facts || {};
  const fprov = fit.deal_facts_provenance || {};
  return `
  <div class="verdict-block plain">${chip(fit.verdict, true)}<span>${esc(humanReason(fit.reason))}</span></div>
  <p class="small" style="max-width:75ch">Any hard fail gives <b>Pass</b>. No soft fails and no unknowns gives <b>Pursue</b>. Anything else is <b>Needs work</b>. An unknown counts as a fail, never a pass, even for a hard filter: the screen does not give a deal credit for what the seller did not show.</p>
  <div class="tbl-wrap"><table class="tbl dense mandate-tbl">
    <colgroup><col style="width:17%"><col style="width:6%"><col style="width:17%"><col style="width:14%"><col style="width:9%"><col></colgroup>
    <thead><tr><th scope="col">Test</th><th scope="col">Kind</th><th scope="col" class="n">Threshold</th><th scope="col" class="n">Actual</th><th scope="col">Result</th><th scope="col">Reason</th></tr></thead>
    <tbody><tr class="group"><td colspan="6">Hard filters: fail one and the deal is out of mandate</td></tr>${hard.map(row).join("")}
    <tr class="group"><td colspan="6">Soft filters: count against the deal, for the analyst to judge</td></tr>${soft.map(row).join("")}</tbody>
  </table></div>
  ${Object.keys(facts).length ? `<section class="section" style="margin-top:28px"><h2>Deal facts the tests read</h2><div class="tbl-wrap"><table class="tbl dense"><thead><tr><th>Fact</th><th>Value</th><th>From</th></tr></thead><tbody>${Object.entries(facts).map(([key, v]) => {
    const p = fprov[key] || {};
    const link = p.page && p.doc ? `<button type="button" class="cite inline-num" data-ev="page" data-doc="${esc(p.doc)}" data-page="${p.page}" data-bbox="${esc(JSON.stringify(p.bbox || []))}" data-title="${esc(sentence(key))}">${esc(p.doc)}, p.${p.page}</button>` : esc(p.from || p.doc || "");
    return `<tr><td>${esc(sentence(key))}</td><td>${esc(typeof v === "number" ? (key.includes("price") ? aedFull(v) : key.includes("year") ? String(v) : int(v)) : v == null ? "unknown" : words(String(v)))}</td><td class="small">${link}${p.status ? ` <span class="muted">${esc(words(p.status))}</span>` : ""}</td></tr>`;
  }).join("")}</tbody></table></div></section>` : ""}
  <p class="notice-line">Mandate: ${esc(r.mandate_fit?.firm || "the illustrative fund's buy box")} in data/mandate.yaml. Synthetic deal; fictional property.</p>`;
}

// ---------------------------------------------------------------- documents

const ROLE = { om: "Offering memorandum", rent_roll: "Rent roll", operating_statement: "Operating statement" };

function docsView(r) {
  const docs = r.documents || [];
  return `<p class="note small" style="max-width:75ch">The package exactly as the broker sent it: file names, layouts and formats vary by deal, and one OM in the set is a scan. The screen identified each document's role from its content.</p>
  <div class="docs-list">${docs.map((d) => {
    const role = ROLE[d.role] || sentence(d.role || "other");
    if (d.kind === "pdf") {
      return `<section class="doc"><h3>${esc(d.doc_id)}</h3>
        <div class="meta">${esc(role)}. PDF, ${int(d.pages.length)} page${d.pages.length === 1 ? "" : "s"}${d.scanned ? ", scanned (text read by OCR)" : ""}. ${esc(d.role_reason || "")}</div>
        <div class="thumbs">${d.pages.map((p) => `<button type="button" class="thumb" data-ev="page" data-doc="${esc(d.doc_id)}" data-page="${p.number}" data-title="${esc(d.doc_id)}, page ${p.number}" aria-pressed="false" aria-label="Open page ${p.number} of ${esc(d.doc_id)}"><img src="${esc(data.pageSrc(r, p.image))}" alt="" loading="lazy" width="${Math.round(p.width_pt)}" height="${Math.round(p.height_pt)}"><span>${p.number}</span></button>`).join("")}</div>
      </section>`;
    }
    return `<section class="doc"><h3>${esc(d.doc_id)}</h3>
      <div class="meta">${esc(role)}. Spreadsheet, ${int((d.sheets || []).length)} sheet${(d.sheets || []).length === 1 ? "" : "s"}. ${esc(d.role_reason || "")}</div>
      <div class="sheets">${(d.sheets || []).map((s) => `<button type="button" class="btn ghost sm" data-ev="sheet" data-doc="${esc(d.doc_id)}" data-sheet="${esc(s.name)}" data-title="${esc(d.doc_id)}">${esc(s.name)} <span class="muted">${int(s.n_rows)} rows x ${int(s.n_cols)} columns</span></button>`).join("")}</div>
    </section>`;
  }).join("")}</div>
  <p class="notice-line">Synthetic documents: every page carries a "synthetic, for demonstration" footer.</p>`;
}

// ---------------------------------------------------------------- run details

function runView(r) {
  const m = r.meta || {};
  const t = m.tokens || {};
  const om = r.extracted?.om || {};
  const fields = Object.entries(om).filter(([key, v]) => key !== "upside_claims" && v && typeof v === "object");
  const counts = fields.reduce((a, [, v]) => ((a[v.status] = (a[v.status] || 0) + 1), a), {});
  const stages = Object.entries(m.stage_durations_s || {});
  const memo = r.memo || {};
  const fieldRow = ([key, v]) => {
    const s = v.source || {};
    const val = key.includes("year") && typeof v.value === "number" ? String(v.value) : v.value == null ? (v.status === "not_stated" ? "not stated" : "n/a") : typeof v.value === "object" ? Object.entries(v.value).filter(([, x]) => x != null).map(([a, b]) => `${words(a)}: ${words(b)}`).join(", ") : byUnit(v.value, /aed/i.test(v.unit || "") ? "AED" : v.unit === "ratio" ? "ratio" : v.unit === "sqft" ? "sqft" : "");
    const link = s.page ? `<button type="button" class="cite inline-num" data-ev="page" data-doc="${esc(s.doc)}" data-page="${s.page}" data-bbox="${esc(JSON.stringify(s.bbox || []))}" data-title="${esc(sentence(key))}">p.${s.page}</button>` : "";
    const st = v.status === "verified" ? '<span class="verified">verified</span>' : v.status === "verified_fuzzy" ? '<span class="verified">verified, fuzzy</span>' : v.status === "unverified" ? `<span class="unverified" title="${esc(v.reason || "")}">unverified</span>` : '<span class="muted">not stated</span>';
    return `<tr><td>${esc(sentence(key))}</td><td>${esc(val)}</td><td>${st}</td><td class="n">${link}</td></tr>`;
  };
  return `
  <section class="section"><h2>Run</h2>
    <div class="tbl-wrap"><table class="tbl dense"><tbody>
      <tr><th scope="row">Model</th><td>${esc(m.model)}${m.mapping_model && m.mapping_model !== m.model ? `; layout mapping ${esc(m.mapping_model)}` : ""}</td></tr>
      <tr><th scope="row">Pipeline version</th><td>${esc(m.pipeline_version)}; engine ${esc(m.engine_version)}</td></tr>
      <tr><th scope="row">Started</th><td>${esc(m.started_at)}</td></tr>
      <tr><th scope="row">Wall time</th><td class="tnum">${esc(duration(m.duration_s))}</td></tr>
      <tr><th scope="row">Model calls</th><td class="tnum">${int((m.calls || []).length)}</td></tr>
      <tr><th scope="row">Tokens</th><td class="tnum">${int(t.input_tokens)} input, ${int(t.output_tokens)} output, ${int(t.cache_creation_input_tokens)} cache write, ${int(t.cache_read_input_tokens)} cache read</td></tr>
      <tr><th scope="row">Cost</th><td class="tnum">${esc(usd(m.cost_usd))} <span class="muted small">${esc(m.prices_note || "")}</span></td></tr>
      <tr><th scope="row">Memo check</th><td>${memo.status === "passed" ? `<span class="verified">passed</span>` : `<span class="unverified">failed, memo withheld</span>`}; ${int((memo.attempts || []).length)} attempt${(memo.attempts || []).length === 1 ? "" : "s"}${(memo.attempts || []).map((a) => `, attempt ${a.attempt}: ${int((a.errors || []).length)} problems`).join("")}</td></tr>
    </tbody></table></div>
  </section>
  <div class="two-col">
    <section class="section"><h2>Time by stage</h2>
      <table class="tbl dense"><thead><tr><th>Stage</th><th class="n">Seconds</th></tr></thead><tbody>${stages.map(([s, v]) => `<tr><td>${esc(sentence(s))}</td><td class="n">${esc(num(v, 1))}</td></tr>`).join("")}</tbody></table>
    </section>
    <section class="section"><h2>Model calls</h2>
      <table class="tbl dense"><thead><tr><th>Stage</th><th class="n">In</th><th class="n">Out</th><th class="n">Cost</th></tr></thead><tbody>${(m.calls || []).map((c) => `<tr><td>${esc(sentence(c.stage))}</td><td class="n">${int(c.input_tokens + c.cache_creation_input_tokens + c.cache_read_input_tokens)}</td><td class="n">${int(c.output_tokens)}</td><td class="n">${esc(usd(c.cost_usd))}</td></tr>`).join("")}</tbody></table>
    </section>
  </div>
  <section class="section"><h2>OM extraction and verification</h2>
    <p class="note">${Object.entries(counts).map(([s, n]) => `${n} ${words(s)}`).join(", ")}. A field is verified only if code finds its quote on the cited page and the value parses from the quote. Unverified fields cannot feed the engine.</p>
    <div class="tbl-wrap"><table class="tbl dense"><thead><tr><th>Field</th><th>Value</th><th>Status</th><th class="n">Page</th></tr></thead><tbody>${fields.map(fieldRow).join("")}</tbody></table></div>
  </section>
  ${(r.notes || []).length ? `<section class="section"><h2>Data-handling notes</h2><ul class="small">${r.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></section>` : ""}
  ${(r.errors || []).length ? `<section class="section"><h2>Errors</h2><ul class="small">${r.errors.map((e) => `<li>${esc(e.stage)}: ${esc(e.error || JSON.stringify(e))}</li>`).join("")}</ul></section>` : ""}
  ${(r.rejected_model_findings || []).length ? `<section class="section"><h2>Rejected model findings</h2><p class="note">Raised by the model review but dropped because no quote could be verified.</p><ul class="small">${r.rejected_model_findings.map((f) => `<li><b>${esc(f.title)}</b>: ${esc(f.rejected_because)}</li>`).join("")}</ul></section>` : ""}
  <p class="notice-line">Synthetic deal. Costs are computed from assumed list prices.</p>`;
}

export { verdictClass };
