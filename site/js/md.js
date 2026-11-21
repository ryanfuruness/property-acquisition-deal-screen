// A small markdown renderer for the memo, the brief and the failure log.
// Safe by construction: all source text is HTML-escaped before any markup is added,
// raw HTML in the source is shown as text, and link URLs are limited to http(s), mailto,
// in-page hashes and relative paths. Supports headings, paragraphs, ordered and unordered
// lists (with one nested level), GFM pipe tables, blockquotes, fenced code, rules,
// **bold**, *italic*, `code`, [links](url) and the memo's citation anchors [[fact_id]].

import { esc } from "./format.js";

const ANCHOR = /\[\[([A-Za-z0-9_.\-+%]+)\]\]/g;
// The figure written just before an anchor: money, %, x, bps, counts with units, dates, quarters.
const FIGURE = new RegExp(
  "(" +
    "(?:\\d{1,2}\\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\\.?\\s\\d{4})" +
    "|(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\\.?\\s\\d{4})" +
    "|(?:\\d{4}-\\d{2}-\\d{2})|(?:20\\d\\d[- ]?Q[1-4])|(?:Q[1-4][ -]20\\d\\d)" +
    "|(?:(?:AED\\s?)?[-−+]?(?:AED\\s?)?\\d[\\d,]*(?:\\.\\d+)?(?:\\s?(?:k|mn|m|bn|million|billion)\\b)?" +
    "(?:\\s?%|x\\b|\\s?bps\\b|\\s?pp\\b)?" +
    "(?:\\s(?:sq\\s?ft|sqft|psf|per sq ft|units?|tenancies|leases|years?|months?|days'?|percentage points|points|bps)\\b)?" +
    "(?:\\s(?:a year|per year|a yr|on NSA|on BUA))?)" +
  ")(\\**)(\\s*)$"
);

const FIGURE_ANY = new RegExp(FIGURE.source.replace(/\(\\\*\*\)\(\\s\*\)\$$/, ""), "g");

// The last figure within 36 characters before an anchor, with only words (no digits) after it.
function lastFigure(before) {
  const tailStart = Math.max(0, before.length - 36);
  const tail = before.slice(tailStart);
  let last = null;
  for (const m of tail.matchAll(FIGURE_ANY)) if (/\d/.test(m[1])) last = m;
  if (!last) return null;
  const after = tail.slice(last.index);
  if (/\d/.test(tail.slice(last.index + last[1].length))) return null;
  if (/[*`|]/.test(after)) return null;
  const trimmed = after.replace(/\s+$/, "");
  return { start: tailStart + last.index, label: trimmed, rest: "" };
}

function safeUrl(url) {
  const u = url.trim();
  if (/^(https?:|mailto:)/i.test(u)) return u;
  if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return null; // javascript:, data:, etc.
  return u; // relative or hash
}

// Inline markup on raw text: code spans and citation anchors are cut out first, then the rest is
// escaped, then markup is added. `opts.cite(id, labelHtml)` renders an anchor.
function inline(text, opts, tokens) {
  const stash = (html) => {
    tokens.push(html);
    return `\u0000${tokens.length - 1}\u0001`;
  };
  // code spans first: their content is literal
  text = text.replace(/`([^`]+)`/g, (_, c) => stash(`<code>${esc(c)}</code>`));
  // citation anchors, absorbing the figure before them
  if (opts.cite) {
    let out = "";
    let last = 0;
    ANCHOR.lastIndex = 0;
    let m;
    while ((m = ANCHOR.exec(text))) {
      let before = text.slice(last, m.index);
      const fm = before.slice(-60).match(FIGURE);
      let label = null;
      const loose = fm ? null : lastFigure(before);
      if (fm && fm[1] && /\d/.test(fm[1])) {
        const cut = before.length - fm[0].length;
        label = fm[1];
        const stars = fm[2] || "";
        before = before.slice(0, cut);
        out += before + stash(opts.cite(m[1], esc(label))) + stars;
      } else if (loose) {
        // "9.9% of income [[id]]": the figure, then a few words, then the anchor
        out += before.slice(0, loose.start) + stash(opts.cite(m[1], esc(loose.label))) + loose.rest;
      } else {
        out += before.replace(/\s+$/, "") + stash(opts.cite(m[1], null));
      }
      last = m.index + m[0].length;
    }
    text = out + text.slice(last);
  } else {
    text = text.replace(ANCHOR, "");
  }
  text = esc(text);
  // links
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (_, label, url) => {
    const raw = url.replace(/&amp;/g, "&");
    const href = opts.link ? opts.link(raw) : safeUrl(raw);
    if (!href) return label;
    const ext = /^https?:/i.test(href);
    return stash(`<a href="${esc(href)}"${ext ? ' rel="noopener" target="_blank"' : ""}>`) + label + stash("</a>");
  });
  // autolinks
  text = text.replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, (_, pre, url) =>
    pre + stash(`<a href="${url}" rel="noopener" target="_blank">${url}</a>`));
  text = text.replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__([^_]+?)__/g, "<strong>$1</strong>");
  text = text.replace(/(^|[^*\w])\*(?!\s)([^*]+?)\*(?!\w)/g, "$1<em>$2</em>");
  text = text.replace(/(^|[^\w])_(?!\s)([^_]+?)_(?!\w)/g, "$1<em>$2</em>");
  return text;
}

function restore(html, tokens) {
  // tokens may contain other tokens (a citation inside a link label is not expected, but be safe)
  let prev;
  do {
    prev = html;
    html = html.replace(/\u0000(\d+)\u0001/g, (_, i) => tokens[+i]);
  } while (html !== prev);
  return html;
}

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

export function renderMarkdown(src, opts = {}) {
  const tokens = [];
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  const inl = (t) => inline(t, opts, tokens);
  let i = 0;
  const headingIds = new Map();

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    // fenced code
    const fence = line.match(/^\s*(```|~~~)/);
    if (fence) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    // heading
    const h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (h) {
      const level = Math.min(6, h[1].length + (opts.shiftHeadings || 0));
      const plain = h[2].replace(ANCHOR, "").replace(/[*_`]/g, "");
      let id = (opts.idPrefix || "") + plain.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      const n = headingIds.get(id) || 0;
      headingIds.set(id, n + 1);
      if (n) id += "-" + n;
      out.push(`<h${level} id="${esc(id)}">${inl(h[2])}</h${level}>`);
      i++;
      continue;
    }
    // rule
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    // table
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      const head = splitRow(line);
      const aligns = splitRow(lines[i + 1]).map((c) => (c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : ""));
      i += 2;
      const body = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) body.push(splitRow(lines[i++]));
      const al = (j) => (aligns[j] ? ` style="text-align:${aligns[j]}"` : "");
      out.push(
        `<div class="md-table"><table><thead><tr>${head.map((c, j) => `<th${al(j)}>${inl(c)}</th>`).join("")}</tr></thead><tbody>` +
          body.map((r) => `<tr>${head.map((_, j) => `<td${al(j)}>${inl(r[j] ?? "")}</td>`).join("")}</tr>`).join("") +
          "</tbody></table></div>"
      );
      continue;
    }
    // blockquote
    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(buf.join("\n"), opts)}</blockquote>`);
      continue;
    }
    // list
    const li = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
    if (li) {
      const parseList = (baseIndent) => {
        const first = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+/);
        const ordered = /\d/.test(first[2]);
        const start = ordered ? parseInt(first[2], 10) : 1;
        const items = [];
        while (i < lines.length) {
          const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
          if (!m) {
            // continuation line of the previous item
            if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) {
              items[items.length - 1].text += " " + lines[i].trim();
              i++;
              continue;
            }
            break;
          }
          const indent = m[1].length;
          if (indent < baseIndent) break;
          if (indent > baseIndent + 1 && items.length) {
            items[items.length - 1].sub = parseList(indent);
            continue;
          }
          items.push({ text: m[3], sub: "" });
          i++;
        }
        const tag = ordered ? "ol" : "ul";
        const st = ordered && start !== 1 ? ` start="${start}"` : "";
        return `<${tag}${st}>${items.map((it) => `<li>${inl(it.text)}${it.sub}</li>`).join("")}</${tag}>`;
      };
      out.push(parseList(li[1].length));
      continue;
    }
    // paragraph
    const buf = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^(#{1,6})\s/.test(lines[i]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i]) &&
      !/^\s*>/.test(lines[i]) && !/^\s*(```|~~~)/.test(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1]))
    ) buf.push(lines[i++].trim());
    out.push(`<p>${inl(buf.join(" "))}</p>`);
  }
  return restore(out.join("\n"), tokens);
}
