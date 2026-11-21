// The evidence panel: where a number came from.
// A citation resolves through the run's fact sheet to one of: a PDF page with the quoted span
// highlighted (bbox fractions from run.json), spreadsheet cells, an engine calculation with its
// inputs and their provenance, a mandate assumption or test, or a discrepancy record.

import { esc, byUnit, aed, aedFull, pct, mult, int, date, words, sentence, prov, statusMark, sev, metricLabel, inputLabel, testName, humanReason } from "./format.js";
import { findDoc, pageSrc, parseRanges, colName, pdfCellBoxes } from "./data.js";

const MANDATE_URL = "https://github.com/ryanfuruness/property-acquisition-deal-screen/blob/main/data/mandate.yaml";
const MARKET_URL = "https://github.com/ryanfuruness/property-acquisition-deal-screen/blob/main/data/market/areas.yaml";

const ASSUME_INPUT = {
  ltv: "mandate.underwriting.debt.ltv",
  eibor: "mandate.underwriting.debt.base_rate_3m_eibor",
  margin: "mandate.underwriting.debt.margin",
  amortisation_years: "mandate.underwriting.debt.amortisation_years",
  structural_vacancy: "mandate.underwriting.operations.structural_vacancy",
  collection_loss: "mandate.underwriting.operations.collection_loss",
  renewal_probability: "mandate.underwriting.operations.renewal_probability",
  management_fee: "mandate.underwriting.operations.property_management_pct_of_egi",
  exit_yield_expansion_bps: "mandate.underwriting.market_view.exit_yield_expansion_bps",
};

const OM_BASIS_FIELD = {
  "om.yield_basis": "yield_stated",
  "om.annual_rent_basis": "annual_rent_stated",
  "om.occupancy_as_of": "occupancy_stated",
};

const STATUS_TEXT = {
  verified: ["verified", "Quote found on the cited page; value parses from it"],
  verified_fuzzy: ["verified (fuzzy)", "Quote matched approximately on an OCR'd page; figures agree"],
  unverified: ["unverified", "Quote or value failed verification; not used by the engine"],
};

// Which unit rows and columns a rent-roll fact is computed from.
function rrSelection(rr, key) {
  const units = rr.units || [];
  const let_ = (u) => u.status !== "vacant";
  const name = key.replace(/^rr\./, "");
  let rows = units, fields = ["unit"], measure = null, what = "";
  if (name === "in_place_rent_aed") { rows = units.filter(let_); fields = ["annual_rent"]; measure = "annual_rent"; what = "annual rent of every let unit"; }
  else if (name === "potential_rent_aed") { fields = ["annual_rent", "asking_rent"]; what = "in-place rent plus asking rent on vacant units"; }
  else if (name === "vacant_asking_rent_aed") { rows = units.filter((u) => u.status === "vacant"); fields = ["annual_rent", "asking_rent", "status"]; what = "asking rent on vacant units"; }
  else if (name === "unit_count") { fields = ["unit"]; measure = "unit_count"; what = "unit rows, totals and headings excluded"; }
  else if (name === "let_units") { rows = units.filter(let_); fields = ["unit", "status"]; measure = "occupied_units"; what = "units with a let status"; }
  else if (name === "vacant_units") { rows = units.filter((u) => u.status === "vacant"); fields = ["unit", "status"]; measure = "vacant_units"; what = "units marked vacant"; }
  else if (name === "occupancy_by_units") { fields = ["status"]; measure = "occupancy"; what = "status of every unit row"; }
  else if (name === "occupancy_by_area" || name === "area_sqft_total") { fields = ["area"]; measure = "area"; what = "unit areas"; }
  else if (name === "deposits_aed") { fields = ["deposit"]; measure = "deposit"; what = "security deposits"; }
  else if (/^status\./.test(name)) { const s = name.split(".")[1]; rows = units.filter((u) => u.status === s); fields = ["unit", "status"]; what = `units with status ${words(s)}`; }
  else if (/\.units$|\.avg_rent_psf$/.test(name)) {
    const t = name.split(".")[0]; rows = units.filter((u) => u.unit_type === t);
    fields = name.endsWith("avg_rent_psf") ? ["unit_type", "area", "annual_rent"] : ["unit_type"]; what = `${t} unit rows`;
  }
  return { rows, fields, measure, what };
}

export class EvidencePanel {
  constructor(root, run, hooks = {}) {
    this.root = root;
    this.run = run;
    this.hooks = hooks;
    this.live = document.getElementById("live");
    this.history = [];
    this.empty();
    root.addEventListener("click", (e) => this.onClick(e));
  }

  // ------------------------------------------------------------ frame
  frame(title, what, body) {
    this.root.innerHTML = `
      <div class="ev-head">
        <div><h2 id="ev-title">${title}</h2>${what ? `<div class="what">${what}</div>` : ""}</div>
        <button type="button" class="close" data-ev="close" aria-label="Close evidence panel">Close</button>
      </div>
      <div class="ev-body">${body}</div>`;
    this.root.classList.add("open");
    this.root.scrollTop = 0;
    if (this.live) this.live.textContent = `Evidence: ${this.root.querySelector("#ev-title").textContent}`;
  }

  empty() {
    const r = this.run;
    const docs = (r.documents || []).length;
    const facts = Object.keys(r.fact_sheet || {}).length;
    this.root.classList.remove("open");
    this.root.innerHTML = `
      <div class="ev-empty">
        <h2>Evidence</h2>
        <p>Select any blue figure to see where it came from. Every number in the memo resolves to one of these:</p>
        <ul>
          <li><b>A page</b> of the broker's PDF, with the quoted words highlighted.</li>
          <li><b>Cells</b> in the rent roll or operating statement.</li>
          <li><b>A calculation</b> by the underwriting engine, with each input tagged ${prov("document")} ${prov("default")} ${prov("mandate")} or ${prov("market")}.</li>
        </ul>
        <p class="small muted">This run has ${int(facts)} facts drawn from ${int(docs)} documents. Use Tab to move between figures and Enter to open one; Escape closes the panel.</p>
      </div>`;
  }

  onClick(e) {
    const b = e.target.closest("[data-ev]");
    if (b) this.dispatch(b);
  }

  // Elements anywhere on the page can drive the panel with data-ev attributes.
  dispatch(b) {
    const a = b.dataset;
    if (a.ev === "close") { this.hooks.onClose?.(); this.empty(); return; }
    if (a.ev === "page") this.showPage(a.doc, +a.page, a.bbox ? JSON.parse(a.bbox) : [], { title: a.title || null });
    if (a.ev === "sheet") this.showSheet(a.doc, a.ref || "", { title: a.title || null, sheet: a.sheet || null });
    if (a.ev === "fact") this.showFact(a.fact);
    if (a.ev === "metric") this.showMetric(a.metric);
    if (a.ev === "tab") this.hooks.onTab?.(a.tab, a.focus);
    if (a.ev === "pg") this.showPage(a.doc, +a.page, [], { title: null });
  }

  // ------------------------------------------------------------ dispatch
  showFact(id) {
    const f = this.run.fact_sheet?.[id];
    if (!f) {
      this.frame("Not in the fact sheet", esc(id), `<p>The memo cites <code>${esc(id)}</code>, which is not a fact in this run. The memo checker would have failed it, so this should not happen.</p>`);
      return;
    }
    const src = f.source || {};
    const kind = src.kind;
    if (kind === "document") return this.factDocument(id, f);
    if (kind === "rent_roll") return this.factRentRoll(id, f);
    if (kind === "operating_statement") return this.factOpex(id, f);
    if (kind === "engine") return this.factEngine(id, f);
    if (kind === "mandate") return this.factMandate(id, f);
    if (kind === "mandate_fit") return this.factMandateFit(id, f);
    if (kind === "discrepancy") return this.factDiscrepancy(id, f);
    return this.factPlain(id, f);
  }

  valueBlock(f) {
    const v = byUnit(f.value, f.unit);
    if (f.unit === "text" && String(v).length > 60) return `<p>${esc(v)}</p>`;
    return `<div class="ev-value">${esc(v)}</div>`;
  }

  // ------------------------------------------------------------ document facts (OM pages)
  factDocument(id, f) {
    const s = f.source;
    const st = STATUS_TEXT[s.status] || [s.status || "", ""];
    const head = `${this.valueBlock(f)}
      ${s.quote && s.quote !== f.value ? `<blockquote class="ev-quote">“${esc(s.quote)}”</blockquote>` : ""}
      <div class="ev-meta"><span><b>${esc(s.doc)}</b>, page ${int(s.page)}</span>
      ${st[0] ? `<span class="${s.status === "unverified" ? "unverified" : "verified"}" title="${esc(st[1])}">${s.status === "unverified" ? "✗" : "✓"} ${esc(st[0])}</span>` : ""}
      ${s.match && s.match !== "exact" ? `<span>match: ${esc(s.match)}</span>` : ""}</div>`;
    this.renderPage(sentence(f.label), `Extracted by the model, checked by code against the page`, s.doc, s.page, s.bbox || [], head);
  }

  showPage(docId, page, bboxes, { title, head = "" } = {}) {
    this.renderPage(title || `${docId}, page ${page}`, "Source page as received", docId, page, bboxes, head);
  }

  renderPage(title, what, docId, pageNo, bboxes, head) {
    const d = findDoc(this.run, docId);
    if (!d || d.kind !== "pdf") {
      this.frame(esc(title), esc(what), `${head}<p class="muted">The page image for ${esc(docId)} is not in this run.</p>`);
      return;
    }
    const pages = d.pages || [];
    const p = pages.find((x) => x.number === pageNo) || pages[0];
    if (!p) { this.frame(esc(title), esc(what), `${head}<p class="muted">No pages recorded.</p>`); return; }
    const boxes = (bboxes || []).filter((b) => Array.isArray(b) && b.length === 4);
    const hl = boxes.map((b) => {
      const [x0, y0, x1, y1] = b.map(Number);
      const pad = 0.003;
      return `<span class="hl" style="left:${((x0 - pad) * 100).toFixed(3)}%;top:${((y0 - pad) * 100).toFixed(3)}%;width:${((x1 - x0 + 2 * pad) * 100).toFixed(3)}%;height:${((y1 - y0 + 2 * pad) * 100).toFixed(3)}%"></span>`;
    }).join("");
    const pager = pages.length > 1 ? `<div class="pager" role="group" aria-label="Pages of ${esc(d.doc_id)}"><span class="muted">Page</span>${pages.map((x) =>
      `<button type="button" data-ev="pg" data-doc="${esc(d.doc_id)}" data-page="${x.number}" ${x.number === p.number ? 'aria-current="true"' : ""} aria-label="Page ${x.number}">${x.number}</button>`).join("")}</div>` : "";
    const scan = p.ocr ? `<p class="small muted">Scanned page: text read by OCR${p.ocr_mean_conf ? ` (mean confidence ${int(p.ocr_mean_conf)})` : ""}.</p>` : "";
    const alt = `Page ${p.number} of ${d.doc_id}${boxes.length ? ", with the quoted text highlighted" : ""}. Synthetic document.`;
    this.frame(esc(title), esc(what), `${head}${pager}${scan}
      <div class="pageimg${boxes.length ? " flash" : ""}"><img src="${esc(pageSrc(this.run, p.image))}" alt="${esc(alt)}" width="${Math.round(p.width_pt)}" height="${Math.round(p.height_pt)}">${hl}</div>
      ${boxes.length ? `<div class="legend-inline"><span><i class="hl"></i>quoted span located by code</span></div>` : ""}`);
    const img = this.root.querySelector(".pageimg img");
    const scroll = () => {
      const first = this.root.querySelector(".pageimg .hl");
      if (first) {
        const panel = this.root;
        const rel = first.getBoundingClientRect().bottom - panel.getBoundingClientRect().top;
        // scroll only when the highlight is out of view, so the value and quote above the page stay visible
        if (rel > panel.clientHeight - 24) {
          const top = first.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop - panel.clientHeight * 0.4;
          panel.scrollTo({ top: Math.max(0, top), behavior: "auto" });
        }
      }
    };
    if (img.complete) scroll(); else img.addEventListener("load", scroll, { once: true });
  }

  // ------------------------------------------------------------ spreadsheet cells
  showSheet(docId, ref, { title, what = "Cells as received", head = "", cells = null, totals = null, sheet: wanted = null } = {}) {
    const d = findDoc(this.run, docId);
    const ranges = parseRanges(ref);
    if (!d) { this.frame(esc(title || docId), esc(what), `${head}<p class="muted">${esc(docId)} is not in this run.</p>`); return; }
    if (d.kind === "pdf") {
      // A table read from a PDF page: sheet names are p<N> or p<N>t<K>
      const byPage = pdfCellBoxes(this.run, d.doc_id, [...ranges, ...(cells || [])]);
      const pages = Object.keys(byPage).map(Number).sort((a, b) => a - b);
      const pm = (ranges[0]?.sheet || cells?.[0]?.sheet || "").match(/^p(\d+)/);
      const page = pages[0] || (pm ? +pm[1] : 1);
      const note = (ref ? `<p class="small muted">Cells ${esc(ref)} of the table code read from this PDF.</p>` : "") +
        (pages.length > 1 ? `<p class="small muted">Highlighted rows continue on page${pages.length > 2 ? "s" : ""} ${pages.slice(1).join(", ")}.</p>` : "");
      this.renderPage(title || docId, what, d.doc_id, page, byPage[page] || [], head + note);
      return;
    }
    const sheetName = wanted || ranges[0]?.sheet || cells?.[0]?.sheet || d.sheets?.[0]?.name;
    const sheet = (d.sheets || []).find((s) => s.name === sheetName) || (d.sheets || []).find((s) => s.name.toLowerCase() === String(sheetName).toLowerCase()) || d.sheets?.[0];
    if (!sheet) { this.frame(esc(title || docId), esc(what), `${head}<p class="muted">No sheet data recorded.</p>`); return; }
    const on = new Set();
    const tot = new Set();
    const add = (set, rg) => { for (let r = rg.r0; r <= rg.r1; r++) for (let c = rg.c0; c <= rg.c1; c++) set.add(`${r}:${c}`); };
    const mine = (rg) => rg.sheet === sheet.name || rg.sheet == null;
    for (const rg of ranges) if (mine(rg)) add(on, rg);
    for (const c of cells || []) if (mine(c)) add(on, c);
    for (const c of totals || []) if (mine(c)) add(tot, c);
    const nCols = Math.max(sheet.n_cols || 0, ...(sheet.rows || []).map((r) => r.length));
    const head2 = `<tr><th scope="col"></th>${Array.from({ length: nCols }, (_, j) => `<th scope="col">${colName(j + 1)}</th>`).join("")}</tr>`;
    const body = (sheet.rows || []).map((row, i) => {
      const r = i + 1;
      return `<tr><th scope="row">${r}</th>${Array.from({ length: nCols }, (_, j) => {
        const v = row[j];
        const key = `${r}:${j + 1}`;
        const cls = tot.has(key) ? "total" : on.has(key) ? "on" : "";
        const txt = v == null ? "" : cellText(v);
        return `<td${cls ? ` class="${cls}"` : ""}${txt.length > 28 ? ` title="${esc(txt)}"` : ""}>${esc(txt)}</td>`;
      }).join("")}</tr>`;
    }).join("");
    const legend = `<div class="legend-inline"><span><i></i>cells this figure is computed from</span>${tot.size ? `<span><i class="total"></i>the seller's own total</span>` : ""}</div>`;
    const sheets = (d.sheets || []).length > 1 ? `<p class="small muted">Sheet “${esc(sheet.name)}” of ${int(d.sheets.length)}.</p>` : "";
    this.frame(esc(title || `${d.doc_id}`), esc(what), `${head}
      <div class="ev-meta"><span><b>${esc(d.doc_id)}</b></span><span>${esc(sheet.name)}</span>${ref ? `<span>${esc(ref)}</span>` : ""}</div>
      ${sheets}${legend}
      <div class="grid-wrap" tabindex="0" role="region" aria-label="Spreadsheet ${esc(sheet.name)} of ${esc(d.doc_id)}"><table class="sheet"><thead>${head2}</thead><tbody>${body}</tbody></table></div>`);
    const first = this.root.querySelector(".sheet td.on, .sheet td.total");
    if (first) {
      const wrap = this.root.querySelector(".grid-wrap");
      wrap.scrollTop = Math.max(0, first.offsetTop - 60);
      wrap.scrollLeft = Math.max(0, first.offsetLeft + first.offsetWidth - wrap.clientWidth + 40);
    }
  }

  // ------------------------------------------------------------ rent roll facts
  factRentRoll(id, f) {
    const rr = this.run.rent_roll_summary;
    const docId = f.source.doc;
    const value = this.valueBlock(f);
    if (!rr) { this.frame(esc(sentence(f.label)), "Rent roll", value); return; }
    const head = (extra) => `${value}<p class="small">Computed by code from the rent roll${extra ? `: ${esc(extra)}` : ""}. The model only mapped the columns; it did not add anything up.</p>`;
    if (id === "rr.as_of" && rr.as_of_source) {
      const s = rr.as_of_source;
      if (s.cell) return this.showSheet(s.doc, s.cell, { title: sentence(f.label), what: "Rent roll date", head: `${value}<blockquote class="ev-quote">“${esc(s.quote)}”</blockquote>` });
      return this.frame(esc(sentence(f.label)), "Rent roll date", `${value}<p class="small">Read from ${esc(s.how || "the document")}: ${esc(s.quote || "")}</p>`);
    }
    if (/^rr\.master_/.test(id) && rr.master_lease?.source) {
      const s = rr.master_lease.source;
      if (s.page) return this.renderPage(sentence(f.label), "Master lease", s.doc || docId, s.page, s.bbox ? [s.bbox].flat().length === 4 ? [s.bbox] : s.bbox : [], value);
      return this.showSheet(s.doc || docId, s.range || "", { title: sentence(f.label), what: "Master lease", head: value });
    }
    const sel = rrSelection(rr, id);
    const d = findDoc(this.run, docId);
    const stated = (rr.stated_totals || []).find((t) => t.measure && t.measure === sel.measure);
    let statedLine = "";
    if (stated) {
      const fmt = /rent|deposit/.test(stated.measure) ? aedFull : stated.measure === "occupancy" ? pct : int;
      const foots = typeof f.value === "number" && Math.abs(stated.value - f.value) <= Math.max(1, Math.abs(f.value) * 0.0005);
      statedLine = `<p class="small">The seller's own total says <b>${esc(fmt(stated.value))}</b>${stated.cell ? ` (${esc(stated.cell)})` : ""}: ${foots ? '<span class="verified">✓ agrees with the unit rows</span>' : '<span class="unverified">does not agree with the unit rows</span>'}.</p>`;
    }
    const headHtml = head(`${int(sel.rows.length)} rows, ${sel.what}`) + statedLine;
    const cells = [];
    for (const u of sel.rows) for (const fld of sel.fields) {
      const ref = u.source?.cells?.[fld];
      if (ref) cells.push(...parseRanges(ref));
    }
    const totals = stated?.cell ? parseRanges(stated.cell) : [];
    if (d && d.kind === "pdf") {
      return this.showSheet(docId, "", { title: sentence(f.label), what: "Rent roll received as PDF", head: headHtml, cells });
    }
    this.showSheet(docId, "", { title: sentence(f.label), what: "Rent roll, as received", head: headHtml, cells, totals });
  }

  // ------------------------------------------------------------ operating statement facts
  factOpex(id, f) {
    const op = this.run.opex;
    const value = this.valueBlock(f);
    if (!op) { this.frame(esc(sentence(f.label)), "Operating statement", value); return; }
    const name = id.replace(/^opex\./, "");
    const INCOME = ["rental_income", "other_income"], DED = ["vacancy_loss", "collection_loss"];
    let lines;
    if (name === "total_income_aed") lines = op.lines.filter((l) => INCOME.includes(l.category) || DED.includes(l.category));
    else if (name === "total_expenses_aed" || name === "opex_ratio") lines = op.lines.filter((l) => !INCOME.includes(l.category) && !DED.includes(l.category) && !["total_or_subtotal", "non_operating"].includes(l.category));
    else if (name === "noi_aed") lines = op.lines.filter((l) => !["total_or_subtotal", "non_operating"].includes(l.category));
    else if (name === "absent_standard_categories") lines = [];
    else lines = op.lines.filter((l) => l.category === name);
    const period = op.period || {};
    const ann = period.annualisation || {};
    let head = `${value}`;
    if (["months", "period", "annualisation"].includes(name)) {
      const ev = (period.evidence || []).filter((e) => e.status === "verified" || e.status === "verified_fuzzy");
      head += `<p class="small">${esc(ann.note || "")}${period.months_note ? `. ${esc(period.months_note)}` : ""}.</p>`;
      if (ev[0]?.cell) return this.showSheet(ev[0].doc, ev.map((e) => e.cell).filter(Boolean).join(", "), { title: sentence(f.label), what: "Statement period, as printed", head: head + ev.map((e) => `<blockquote class="ev-quote">“${esc(e.quote)}”</blockquote>`).join("") });
      if (ev[0]?.page) return this.renderPage(sentence(f.label), "Statement period, as printed", ev[0].doc, ev[0].page, ev.flatMap((e) => e.bbox || []), head);
      return this.frame(esc(sentence(f.label)), "Operating statement", head);
    }
    if (name === "absent_standard_categories") {
      head += `<p class="small">Code checks the statement for every standard cost a buyer bears. Absent lines are filled from mandate defaults in the underwriting, tagged ${prov("default")}.</p>`;
      return this.frame(esc(sentence(f.label)), "Operating statement check", head);
    }
    const tbl = lines.length ? `<table class="tbl dense"><thead><tr><th>Line as printed</th><th>Mapped to</th><th class="n">Amount</th></tr></thead><tbody>${lines.map((l) =>
      `<tr><td>${esc(l.label)}</td><td class="muted">${esc(words(l.category))}</td><td class="n">${l.amount_aed == null ? "n/a" : esc(aedFull(l.amount_aed))}${l.status !== "verified" ? ' <span class="unverified" title="' + esc(l.reason || "") + '">✗</span>' : ""}</td></tr>`).join("")}</tbody></table>` : `<p class="muted small">No statement line maps to this category.</p>`;
    head += `<p class="small">Totalled by code from ${int(lines.length)} statement line${lines.length === 1 ? "" : "s"} the model mapped to the chart of accounts${ann.factor && ann.factor !== 1 ? `, then annualised (x ${ann.factor.toFixed(3)})` : ""}.</p>${tbl}`;
    const d = findDoc(this.run, op.doc);
    if (d && d.kind === "pdf") {
      const withPage = lines.filter((l) => l.source?.page);
      const page = withPage[0]?.source.page || 1;
      const boxes = withPage.filter((l) => l.source.page === page).flatMap((l) => l.source.bbox || []);
      return this.renderPage(sentence(f.label), "Operating statement, as received", op.doc, page, boxes, head);
    }
    const cells = [];
    for (const l of lines) {
      if (l.source?.cell) cells.push(...parseRanges(l.source.cell));
      if (l.source?.cells) cells.push(...parseRanges(l.source.cells));
      if (l.source?.label_cell) cells.push(...parseRanges(l.source.label_cell));
    }
    const totals = [];
    const measure = { total_income_aed: "total_income", total_expenses_aed: "total_expenses", noi_aed: "noi" }[name];
    const chk = (op.stated_total_checks || []).find((c) => c.measure === measure);
    if (chk?.cell) {
      totals.push(...parseRanges(chk.cell));
      head += `<p class="small">The statement's own ${esc(chk.label)} is ${esc(aedFull(chk.stated_aed))}: ${chk.foots ? '<span class="verified">✓ foots to the lines</span>' : '<span class="unverified">does not foot to the lines</span>'}.</p>`;
    }
    this.showSheet(op.doc, "", { title: sentence(f.label), what: "Operating statement, as received", head, cells, totals });
  }

  // ------------------------------------------------------------ engine facts
  engineMetric(id, f) {
    const out = this.run.underwriting?.outputs || {};
    const name = id.replace(/^uw\./, "");
    if (out.metrics?.[name]) return { m: out.metrics[name], name: metricLabel(name) };
    if (name.startsWith("walk_away_")) { const k = name.replace("walk_away_", ""); if (out.walk_away?.[k] && typeof out.walk_away[k] === "object") return { m: out.walk_away[k], name: `walk-away ${words(k)}` }; }
    if (name.startsWith("om_yield.")) { const k = name.split(".")[1]; if (out.om_yield_check?.[k]) return { m: out.om_yield_check[k], name: `OM yield check: ${words(k)}` }; }
    if (name.startsWith("opex_default.")) { const k = name.split(".")[1]; const inp = out.inputs?.[`deal.opex_aed.${k}`]; if (inp) return { input: inp, inputName: `deal.opex_aed.${k}` }; }
    if (name.startsWith("sens.")) return { sens: true };
    if (name === "max_expiry_quarter" || name === "max_expiry_quarter_rent_aed") return { expiry: true };
    return {};
  }

  factEngine(id, f) {
    const found = this.engineMetric(id, f);
    const value = this.valueBlock(f);
    const title = found.name ? found.name : sentence(f.label);
    if (found.m) return this.renderMetric(title, found.m, value + (f.source?.note || found.m.note ? `<p class="small">${esc(sentence(f.source?.note || found.m.note))}.</p>` : ""));
    if (found.input) {
      return this.frame(esc(sentence(f.label)), "Mandate default used because the package lacked this cost",
        `${value}<p class="small">${prov(found.input.provenance)} ${esc(found.input.note || "")}</p><p class="small">Defaults are priced per sq ft of NSA from <a href="${MANDATE_URL}" target="_blank" rel="noopener">data/mandate.yaml</a> (underwriting.operations.opex_defaults_aed_per_sqft_nsa). Unknown facts count against a deal, never for it.</p>`);
    }
    if (found.sens) {
      return this.frame(esc(sentence(f.label)), "Engine sensitivity grid",
        `${value}<p class="small">One cell of the 3 x 3 grid: exit yield -50 / 0 / +50 bps against market rent -5% / base / +5%. The engine reruns the whole cash flow for each cell.</p>
         <button type="button" class="btn ghost sm" data-ev="tab" data-tab="underwriting" data-focus="sensitivity">Open the sensitivity grid</button>`);
    }
    if (id === "uw.walk_away_binding_constraint") return this.renderMetric("Walk-away price", this.run.underwriting?.outputs?.walk_away?.price_aed, `${value}<p class="small">The constraint that stops the price going higher.</p>`);
    const warn = id === "uw.warnings" ? "" : "";
    this.frame(esc(sentence(f.label)), "Computed by the underwriting engine", `${value}${warn}<p class="small">Deterministic engine output (no model involved). See the Underwriting tab for the full calculation.</p>
      <button type="button" class="btn ghost sm" data-ev="tab" data-tab="underwriting">Open Underwriting</button>`);
  }

  showMetric(name) {
    const out = this.run.underwriting?.outputs || {};
    let m = out.metrics?.[name];
    let title = metricLabel(name);
    if (!m && name.startsWith("acq.")) { m = out.acquisition_costs?.[name.slice(4)]; title = `Acquisition cost: ${words(name.slice(4))}`; }
    if (!m && name.startsWith("wa.")) { m = out.walk_away?.[name.slice(3)]; title = `Walk-away: ${words(name.slice(3))}`; }
    if (!m && name.startsWith("oy.")) { m = out.om_yield_check?.[name.slice(3)]; title = `OM yield check: ${words(name.slice(3))}`; }
    if (!m) { this.frame(esc(title), "Engine", `<p class="muted">No such metric in this run.</p>`); return; }
    this.renderMetric(title, m, `<div class="ev-value">${esc(byUnit(m.value, m.unit))}</div>${m.note ? `<p class="small">${esc(sentence(m.note))}.</p>` : ""}`);
  }

  renderMetric(title, m, head) {
    const inputs = this.run.underwriting?.outputs?.inputs || {};
    const provMap = this.run.underwriting?.inputs_provenance || {};
    const deps = m?.depends_on || [];
    const groups = { document: [], default: [], market: [], mandate: [] };
    for (const d of deps) (groups[d.provenance] || (groups[d.provenance] = [])).push(d);
    const row = (d) => {
      const inp = inputs[d.input] || {};
      const short = d.input.replace(/^deal\./, "").replace(/^mandate\.(underwriting|buy_box)\./, "").replace(/^market\./, "");
      let link = "";
      const p = provMap[d.input.replace(/^deal\./, "")];
      if (p?.page && p.doc) link = ` <button type="button" class="cite inline-num" data-ev="page" data-doc="${esc(p.doc)}" data-page="${p.page}" data-bbox="${esc(JSON.stringify(p.bbox || []))}" data-title="${esc(inputLabel(d.input))}">p.${p.page}</button>`;
      else if (p?.cell && p.doc) link = ` <button type="button" class="cite inline-num" data-ev="sheet" data-doc="${esc(p.doc)}" data-ref="${esc(p.cell)}" data-title="${esc(inputLabel(d.input))}">${esc(p.cell.split("!").pop())}</button>`;
      else if (p?.lines?.length) {
        const l = p.lines[0];
        if (l.page && l.bbox?.length) link = ` <button type="button" class="cite inline-num" data-ev="page" data-doc="${esc(l.doc)}" data-page="${l.page}" data-bbox="${esc(JSON.stringify(l.bbox || []))}" data-title="${esc(l.label)}">p.${l.page}</button>`;
        else if (l.cell) link = ` <button type="button" class="cite inline-num" data-ev="sheet" data-doc="${esc(l.doc)}" data-ref="${esc([l.cell, l.label_cell].filter(Boolean).join(", "))}" data-title="${esc(l.label)}">${esc(l.cell.split("!").pop())}</button>`;
        else if (l.page) link = ` <button type="button" class="cite inline-num" data-ev="page" data-doc="${esc(l.doc)}" data-page="${l.page}" data-bbox="${esc(JSON.stringify(l.bbox || []))}" data-title="${esc(l.label)}">p.${l.page}</button>`;
      } else if (p?.from === "rent_roll" && p.doc) link = ` <button type="button" class="cite inline-num" data-ev="fact" data-fact="rr.unit_count">rows</button>`;
      return `<li>${prov(d.provenance)}<span class="k">${esc(inputLabel(d.input))}${link}</span><span class="v">${esc(inputValue(inp))}</span></li>`;
    };
    const section = (label, list, open) => list.length ? `<details class="deps-group" ${open ? "open" : ""}><summary>${label} (${list.length})</summary><ul class="deps">${list.map(row).join("")}</ul></details>` : "";
    const counts = Object.entries(groups).filter(([, l]) => l.length).map(([k, l]) => `${prov(k)} ${l.length}`).join(" ");
    this.frame(esc(title), "Computed by the underwriting engine (deterministic, no model)", `${head}
      <div class="ev-section"><h3>Inputs this figure depends on</h3>
        <p class="small">${counts || "None recorded."}</p>
        ${section("From the deal package", groups.document, true)}
        ${section("Mandate defaults filling gaps in the package", groups.default, true)}
        ${section("Market reference data", groups.market, groups.document.length < 3)}
        ${section("Firm mandate and underwriting assumptions", groups.mandate, deps.length < 8)}
      </div>
      <p class="small muted">Assumptions live in <a href="${MANDATE_URL}" target="_blank" rel="noopener">data/mandate.yaml</a> and <a href="${MARKET_URL}" target="_blank" rel="noopener">data/market/areas.yaml</a>, versioned with the code.</p>`);
  }

  // ------------------------------------------------------------ mandate
  factMandate(id, f) {
    const value = this.valueBlock(f);
    const inputs = this.run.underwriting?.outputs?.inputs || {};
    let path = null;
    const key = id.replace(/^assume\./, "");
    if (ASSUME_INPUT[key]) path = ASSUME_INPUT[key];
    const g = key.match(/^rent_growth_year(\d+)$/);
    if (g) path = Object.keys(inputs).find((k) => k.startsWith("mandate.underwriting.market_view.rent_growth_by_year")) || "mandate.underwriting.market_view.rent_growth_by_year";
    const t = id.match(/^mandate\.(.+)\.threshold$/);
    if (t) {
      const test = (this.run.mandate_fit?.tests || []).find((x) => x.name === t[1]);
      return this.frame(esc(sentence(f.label)), "Firm mandate (buy box)", `${value}
        ${test ? `<p class="small">${esc(sentence(test.kind))} filter. ${esc(test.reason)}</p><p>${statusMark(test.status)}</p>` : ""}
        <p class="small">From the buy box in <a href="${MANDATE_URL}" target="_blank" rel="noopener">data/mandate.yaml</a>. The firm's view is data, not code.</p>
        <button type="button" class="btn ghost sm" data-ev="tab" data-tab="mandate">Open Mandate fit</button>`);
    }
    const inp = path ? inputs[path] : null;
    this.frame(esc(sentence(f.label)), "Firm assumption, not package data", `${value}
      <p>${prov("mandate")} <span class="small">${path ? esc(path.replace(/^mandate\./, "")) : ""}${g ? `, year ${g[1]}` : ""}</span></p>
      ${inp?.note ? `<p class="small">${esc(inp.note)}</p>` : ""}
      <p class="small">House view from <a href="${MANDATE_URL}" target="_blank" rel="noopener">data/mandate.yaml</a>. Changing the firm's view is a data change, reviewed like code.</p>`);
  }

  factMandateFit(id, f) {
    const fit = this.run.mandate_fit || {};
    const m = id.match(/^mandate\.(.+)\.(status|reason)$/);
    if (m) {
      const t = (fit.tests || []).find((x) => x.name === m[1]);
      if (t) return this.frame(esc(testName(t.name)), `${esc(sentence(t.kind))} filter`, `<p>${statusMark(t.status)}</p><p>${esc(t.reason)}</p>
        <table class="tbl dense"><tbody><tr><th>Threshold</th><td class="n">${esc(testValue(t.name, t.threshold))}</td></tr><tr><th>Actual</th><td class="n">${esc(testValue(t.name, t.actual))}</td></tr><tr><th>Source</th><td>${esc(words(t.source))}</td></tr></tbody></table>
        <p><button type="button" class="btn ghost sm" data-ev="tab" data-tab="mandate">Open Mandate fit</button></p>`);
    }
    const fails = [...(fit.tests || []).filter((t) => t.status !== "pass")];
    this.frame(esc(sentence(f.label)), "Mandate fit, applied by code", `${this.valueBlock(f)}<p>${esc(humanReason(fit.reason))}</p>
      ${fails.length ? `<table class="tbl dense"><thead><tr><th>Test</th><th>Kind</th><th>Result</th></tr></thead><tbody>${fails.map((t) => `<tr><td>${esc(testName(t.name))}</td><td>${esc(t.kind)}</td><td>${statusMark(t.status)}</td></tr>`).join("")}</tbody></table>` : ""}
      <p class="small">Any hard fail gives Pass; no soft fails or unknowns gives Pursue; anything else is Needs work. An unknown counts against the deal.</p>
      <button type="button" class="btn ghost sm" data-ev="tab" data-tab="mandate">Open Mandate fit</button>`);
  }

  // ------------------------------------------------------------ discrepancy
  factDiscrepancy(id, f) {
    const d = (this.run.discrepancies || []).find((x) => x.id === f.source.id);
    if (!d) return this.factPlain(id, f);
    const srcs = (d.sources || []).map((s) => sourceButton(s)).filter(Boolean).join(" ");
    this.frame(esc(d.title), `${sev(d.severity)} discrepancy, detected by ${esc(words(d.detected_by))}`, `
      ${f.unit === "text" ? `<p>${esc(f.value)}</p>` : this.valueBlock(f)}
      <p class="small muted">${esc(sentence(f.label))}</p>
      ${srcs ? `<div class="ev-section"><h3>Sources compared</h3><p>${srcs}</p></div>` : ""}
      <p><button type="button" class="btn ghost sm" data-ev="tab" data-tab="discrepancies" data-focus="${esc(d.id)}">Open the discrepancy card</button></p>`);
  }

  factPlain(id, f) {
    const field = OM_BASIS_FIELD[id];
    const om = this.run.extracted?.om?.[field];
    if (om?.source?.page) {
      return this.renderPage(sentence(f.label), "The OM's own wording", om.source.doc, om.source.page, om.source.bbox || [],
        `${this.valueBlock(f)}${om.quote ? `<blockquote class="ev-quote">“${esc(om.quote)}”</blockquote>` : ""}`);
    }
    this.frame(esc(sentence(f.label)), "Screen record", `${this.valueBlock(f)}<p class="small muted">Recorded by the pipeline about its own data handling.</p>`);
  }
}

// ------------------------------------------------------------ helpers shared with the views

export function cellText(v) {
  const s = String(v);
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[ T]00:00:00$/);
  if (m) return m[1];
  if (/^-?\d+\.\d{5,}$/.test(s)) return String(Math.round(parseFloat(s) * 10000) / 10000);
  return s;
}

function inputValue(inp) {
  const v = inp.value;
  if (v == null) return "not stated";
  if (Array.isArray(v)) return v.length && typeof v[0] === "object" ? `${int(v.length)} rows` : v.map((x) => (typeof x === "number" ? (Math.abs(x) < 1 ? pct(x, 1) : int(x)) : String(x))).join(" / ");
  if (typeof v === "object") return Object.keys(v).length + " values";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v.length > 40 ? v.slice(0, 38) + "…" : v;
  const u = (inp.unit || "").toLowerCase();
  if (u.startsWith("aed/sqft")) return `AED ${v.toFixed(1)} psf`;
  if (u.startsWith("aed")) return aed(v);
  if (u.startsWith("ratio")) return pct(v);
  if (u === "x") return mult(v);
  if (u === "sqft") return `${int(v)} sq ft`;
  return Number.isInteger(v) ? int(v) : String(+v.toFixed(4));
}

export function testValue(name, v) {
  if (v == null) return "unknown";
  if (typeof v === "boolean") return name === "no_master_lease_to_related_party" ? (v ? "Related-party master lease" : "None") : v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map(words).join(", ");
  if (typeof v === "string") return words(v);
  if (/price/.test(name)) return aed(v);
  if (/year$/.test(name) && !/dscr/.test(name)) return String(v);
  if (/units/.test(name)) return int(v);
  if (/dscr|multiple/.test(name)) return mult(v);
  return pct(v);
}

// A button that opens a discrepancy source (page, cells or engine) in the panel.
export function sourceButton(s, label) {
  if (!s) return "";
  const text = label || (s.page ? `${s.doc}, p.${s.page}` : s.cell ? `${s.doc}, ${s.cell}` : s.doc === "engine" ? "Engine calculation" : s.doc);
  if (s.page && s.doc) return `<button type="button" class="btn ghost sm" data-ev="page" data-doc="${esc(s.doc)}" data-page="${s.page}" data-bbox="${esc(JSON.stringify(s.bbox || []))}" data-title="${esc(s.label ? sentence(s.label) : s.doc)}">${esc(text)}</button>`;
  if (s.cell && s.doc) return `<button type="button" class="btn ghost sm" data-ev="sheet" data-doc="${esc(s.doc)}" data-ref="${esc(s.cell)}" data-title="${esc(s.label ? sentence(s.label) : s.doc)}">${esc(text)}</button>`;
  return "";
}

export { date };
