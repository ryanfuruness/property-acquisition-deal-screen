// Loads site/data/*. Every path is relative so the site works under a GitHub Pages project path.

const cache = new Map();

async function getJSON(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }).catch((e) => { cache.delete(path); throw e; }));
  }
  return cache.get(path);
}

async function getText(path) {
  const key = "text:" + path;
  if (!cache.has(key)) {
    cache.set(key, fetch(path, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.text();
    }).catch((e) => { cache.delete(key); throw e; }));
  }
  return cache.get(key);
}

export async function manifest() {
  try {
    return await getJSON("data/manifest.json");
  } catch {
    return { deals: [], package_index: [], evals: { files: [] }, docs: [], missing: true,
             repo_url: "https://github.com/ryanfuruness/property-acquisition-deal-screen" };
  }
}

export async function run(dealId) {
  const r = await getJSON(`data/runs/${encodeURIComponent(dealId)}/run.json`);
  if (!r.__indexed) index(r, dealId);
  return r;
}

export const evalFile = (name) => getJSON(`data/evals/${name}`);
export const evalText = (name) => getText(`data/evals/${name}`);
export const doc = (name) => getText(`data/docs/${name}`);

export function pageSrc(r, image) {
  return `data/runs/${encodeURIComponent(r.__dealId)}/${image}`;
}

// Lookups the views share.
function index(r, dealId) {
  r.__indexed = true;
  r.__dealId = dealId;
  r.__docs = new Map((r.documents || []).map((d) => [d.doc_id, d]));
  const uw = r.underwriting || {};
  r.__out = uw.outputs || null;
  r.__facts = r.fact_sheet || {};
}

export function findDoc(r, id) {
  if (!id) return null;
  if (r.__docs.has(id)) return r.__docs.get(id);
  const lower = String(id).toLowerCase();
  for (const [k, d] of r.__docs) if (k.toLowerCase() === lower) return d;
  return null;
}

export function metricValue(r, name) {
  const m = r.__out?.metrics?.[name];
  return m ? m.value : null;
}

// "Rent Roll!A6:O6, Other!B2" -> [{sheet, r0, c0, r1, c1}]
export function parseRanges(ref) {
  if (!ref) return [];
  const out = [];
  for (const part of String(ref).split(/,\s*(?=(?:'[^']+'|[^!,]+)!)/)) {
    const m = part.trim().match(/^(?:(?:'([^']+)'|([^!]+))!)?\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?$/);
    if (!m) continue;
    const sheet = m[1] || m[2] || null; // a bare "A2" means the document's only (or current) sheet
    const c0 = colNum(m[3]), r0 = +m[4];
    const c1 = m[5] ? colNum(m[5]) : c0, r1 = m[6] ? +m[6] : r0;
    out.push({ sheet, r0: Math.min(r0, r1), r1: Math.max(r0, r1), c0: Math.min(c0, c1), c1: Math.max(c0, c1) });
  }
  return out;
}

export function colNum(letters) {
  let n = 0;
  for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

export function colName(n) {
  let s = "";
  while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

// For tables read from PDF pages: the page boxes of cells, indexed from the rent-roll units and
// statement lines that carry both a cell address and a box. Returns {page: [[x0,y0,x1,y1], ...]}.
export function pdfCellBoxes(r, docId, ranges) {
  if (!r.__cellBoxes) {
    const idx = new Map();
    const put = (doc, cell, page, box) => {
      if (!doc || !cell || !page || !Array.isArray(box) || box.length !== 4 || typeof box[0] !== "number") return;
      for (const rg of parseRanges(cell)) idx.set(`${doc}|${rg.sheet}|${rg.r0}|${rg.c0}`, { page, box });
    };
    for (const u of r.rent_roll_summary?.units || []) {
      const s = u.source || {};
      if (s.cells && s.bbox && !Array.isArray(s.bbox)) for (const [f, cell] of Object.entries(s.cells)) put(s.doc, cell, s.page, s.bbox[f]);
    }
    for (const l of r.opex?.lines || []) {
      const s = l.source || {};
      if (s.cell && Array.isArray(s.bbox) && s.bbox.length) put(s.doc, s.cell, s.page, s.bbox[0]);
    }
    r.__cellBoxes = idx;
  }
  const out = {};
  for (const rg of ranges) {
    for (let row = rg.r0; row <= rg.r1; row++) for (let c = rg.c0; c <= rg.c1; c++) {
      const hit = r.__cellBoxes.get(`${docId}|${rg.sheet}|${row}|${c}`);
      if (hit) (out[hit.page] = out[hit.page] || []).push(hit.box);
    }
  }
  return out;
}
