"""Stage 3, verify (code only).

For every extracted field:

1. **Quote on the cited page.** The quote is matched against the page's words, case- and
   whitespace-insensitively, then ignoring punctuation. On an OCR'd page a fuzzy match is
   allowed (similarity >= ``config.OCR_FUZZY_MIN_RATIO``), and every number in the quote must
   also appear in the OCR text it matched, so a misread digit cannot slip through.
2. **Value from the quote.** Numbers must parse from the quote (AED, commas, m/mn/million, %,
   sq ft / sq m). Text values must appear in the quote; categorical values must be backed by
   a keyword in the quote (e.g. "freehold" for tenure = freehold).
3. **Boxes.** The matched words' boxes, merged per line, in page fractions, for the site's
   highlight.

A field that fails is ``unverified`` with the reason, and cannot feed the engine.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from . import config
from .ingest import Document, Page, Word, split_cell_ref, parse_a1
from .numbers import parse_numbers, value_in_quote, close

VERIFIED, VERIFIED_FUZZY, UNVERIFIED, NOT_STATED = "verified", "verified_fuzzy", "unverified", "not_stated"
TRUSTED = {VERIFIED, VERIFIED_FUZZY}

# ---------------------------------------------------------------------------- normalisation

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                        "—": "-", "−": "-", " ": " ", " ": " ", " ": " "})


def normalise(text: str) -> str:
    """Case-, whitespace- and typography-normalised text."""
    text = unicodedata.normalize("NFKC", text or "").translate(_TRANS).lower()
    return " ".join(text.split())


def loose(text: str) -> str:
    """Only letters, digits, '.' and '%': ignores spacing and punctuation differences."""
    return re.sub(r"[^a-z0-9.%]", "", normalise(text))


# ---------------------------------------------------------------------------- quote matching


@dataclass
class QuoteMatch:
    found: bool
    method: str | None = None          # exact | normalised | fuzzy
    similarity: float | None = None
    bboxes: list[list[float]] | None = None
    matched_text: str | None = None
    reason: str | None = None


def _line_boxes(words: list[Word]) -> list[list[float]]:
    """Union of word boxes per text line."""
    boxes: list[list[float]] = []
    for w in sorted(words, key=lambda w: (round(w.top, 3), w.x0)):
        if boxes and abs(boxes[-1][1] - w.top) < 0.006 and w.x0 >= boxes[-1][0] - 0.002:
            b = boxes[-1]
            b[0], b[1], b[2], b[3] = min(b[0], w.x0), min(b[1], w.top), max(b[2], w.x1), max(b[3], w.bottom)
        else:
            boxes.append([w.x0, w.top, w.x1, w.bottom])
    return [[round(v, 4) for v in b] for b in boxes]


def _stream(words: list[Word]) -> tuple[str, list[int]]:
    """Concatenate loose word texts; map each character back to its word index."""
    chars, owners = [], []
    for i, w in enumerate(words):
        lw = loose(w.text)
        chars.append(lw)
        owners.extend([i] * len(lw))
    return "".join(chars), owners


# Largest number of words allowed between consecutive parts of a quote: a line break in the quote
# is a layout break (label and figure in separate boxes); an ellipsis is an explicit omission.
MAX_GAP_WORDS = {"line": 12, "ellipsis": 40}


def _parts(quote: str) -> list[tuple[str, str]]:
    """Split a quote into (part, how it joins the previous part); every part must be found in order."""
    out: list[tuple[str, str]] = []
    for i, chunk in enumerate(re.split(r"\s*(?:\.\.\.|…)\s*", quote)):
        for j, line in enumerate(chunk.splitlines()):
            if loose(line):
                out.append((line, "ellipsis" if i and not j else "line"))
    return out


def match_quote(quote: str, page: Page) -> QuoteMatch:
    """Find ``quote`` on ``page``: exact or normalised on a text layer; on an OCR'd page also fuzzy,
    against each OCR pass (the best match wins; figures must agree with the matched OCR text)."""
    if not quote or not loose(quote):
        return QuoteMatch(False, reason="empty quote")
    word_sets = [page.words] + (page.ocr_alternates if page.ocr else [])
    for words in word_sets:
        m = _match_words(quote, words, page.text if words is page.words else "")
        if m.found:
            return m
    if not page.ocr:
        return QuoteMatch(False, reason="quote not found on the cited page")
    best = None
    for words in word_sets:
        m = _fuzzy(quote, words)
        if m.found:
            return m
        if best is None or (m.similarity or 0) > (best.similarity or 0):
            best = m
    return best


def _match_words(quote: str, words: list[Word], page_text: str) -> QuoteMatch:
    """Exact (normalised text) or punctuation-insensitive match of the quote's parts, in order."""
    stream, owners = _stream(words)
    joined = normalise(" ".join(w.text for w in words))
    method = "exact" if normalise(quote) in joined or (page_text and normalise(quote) in normalise(page_text)) \
        else "normalised"
    matched: list[Word] = []
    pos, last_word = 0, None
    for part, join in _parts(quote):
        target = loose(part)
        i = stream.find(target, pos)
        if i < 0:
            return QuoteMatch(False)
        idx = sorted(set(owners[i:i + len(target)]))
        if last_word is not None and idx[0] - last_word - 1 > MAX_GAP_WORDS[join]:
            return QuoteMatch(False)
        matched += [words[k] for k in idx]
        pos, last_word = i + len(target), idx[-1]
    return QuoteMatch(True, method, 1.0, _line_boxes(matched), " ".join(w.text for w in matched))


def _fuzzy(quote: str, words: list[Word]) -> QuoteMatch:
    """Best window of OCR words by similarity of loose text; requires the quote's numbers in the window."""
    target = loose(quote)
    n_q = max(1, len(quote.split()))
    best = (0.0, 0, 0)
    for size in range(max(1, n_q - 3), n_q + 4):
        for start in range(0, max(1, len(words) - size + 1)):
            cand = "".join(loose(w.text) for w in words[start:start + size])
            if not cand or abs(len(cand) - len(target)) > 0.4 * len(target):
                continue
            r = SequenceMatcher(None, target, cand, autojunk=False).ratio()
            if r > best[0]:
                best = (r, start, size)
    ratio, start, size = best
    window = words[start:start + size]
    text = " ".join(w.text for w in window)
    if ratio < config.OCR_FUZZY_MIN_RATIO:
        return QuoteMatch(False, similarity=round(ratio, 3), matched_text=text or None,
                          reason=f"OCR page: best fuzzy match {ratio:.2f} < {config.OCR_FUZZY_MIN_RATIO}")
    window_nums = parse_numbers(text)
    for n in parse_numbers(quote):
        if not any(close(n.value, m.value) for m in window_nums):
            return QuoteMatch(False, similarity=round(ratio, 3), matched_text=text,
                              reason=f"OCR page: quote matches text {ratio:.2f} but the figure {n.raw!r} "
                                     f"is not in the OCR text ({text!r})")
    # highlight only words that belong to the quote or were read confidently (drops scan speckle)
    keep = [w for w in window if loose(w.text) and (loose(w.text) in target or (w.conf or 0) >= 60)]
    return QuoteMatch(True, "fuzzy", round(ratio, 3), _line_boxes(keep or window), text)


def find_doc(docs: list[Document], doc_name: str | None) -> Document | None:
    """Resolve the doc id the model cited: exact, then case-insensitive, then by file name."""
    if not doc_name:
        return None
    for d in docs:
        if d.doc_id == doc_name:
            return d
    low = doc_name.strip().lower()
    for d in docs:
        if d.doc_id.lower() == low or d.doc_id.rsplit("/", 1)[-1].lower() == low.rsplit("/", 1)[-1]:
            return d
    return None


def locate(docs: list[Document], doc_name: str | None, page_no: int | None, quote: str | None,
           search_other_pages: bool = True) -> tuple[Document | None, QuoteMatch, int | None]:
    """Match a quote on the cited page; if not there, look on the other pages and report the move."""
    try:
        page_no = int(str(page_no).strip()) if page_no is not None else None
    except ValueError:
        page_no = None
    doc = find_doc(docs, doc_name)
    if doc is None:
        return None, QuoteMatch(False, reason=f"cited document {doc_name!r} is not in the package"), page_no
    if doc.kind != "pdf":
        return doc, QuoteMatch(False, reason="cited a page in a spreadsheet"), page_no
    page = doc.page(page_no or 0)
    if page is not None:
        m = match_quote(quote or "", page)
        if m.found:
            return doc, m, page_no
    if search_other_pages:
        for p in doc.pages:
            if p.number == page_no:
                continue
            m2 = match_quote(quote or "", p)
            if m2.found:
                m2.reason = f"quote is on page {p.number}, not the cited page {page_no}"
                return doc, m2, p.number
    reason = "cited page does not exist" if page is None else m.reason
    return doc, QuoteMatch(False, reason=reason, similarity=None if page is None else m.similarity,
                           matched_text=None if page is None else m.matched_text), page_no


def match_cell(docs: list[Document], doc_name: str | None, cell_ref: str | None, quote: str | None) -> QuoteMatch:
    """Check that a cell (or range) of a sheet contains the quote."""
    doc = find_doc(docs, doc_name)
    if doc is None or not cell_ref:
        return QuoteMatch(False, reason="cell citation without a known document or address")
    sheet_name, addr = split_cell_ref(cell_ref)
    sheet = doc.sheet(sheet_name) if sheet_name else (doc.sheets[0] if doc.sheets else None)
    if sheet is None:
        return QuoteMatch(False, reason=f"sheet {sheet_name!r} not found")
    try:
        if ":" in addr:
            (r1, c1), (r2, c2) = (parse_a1(a) for a in addr.split(":", 1))
        else:
            r1, c1 = r2, c2 = parse_a1(addr)
    except ValueError as exc:
        return QuoteMatch(False, reason=str(exc))
    texts = [str(sheet.value(r, c)) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)
             if sheet.value(r, c) is not None]
    joined = " ".join(texts)
    if quote and loose(quote) and loose(quote) in loose(joined):
        return QuoteMatch(True, "normalised", 1.0, None, joined)
    return QuoteMatch(False, reason="quote not found in the cited cells", matched_text=joined[:200] or None)


# ---------------------------------------------------------------------------- field specs

# Keyword evidence a categorical value needs in its quote (any one of them).
ENUM_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "asset_type": {
        "residential_building": ("residential", "apartment", "flats", "units"),
        "mixed_use_residential_retail": ("retail", "shop", "commercial"),
    },
    "chiller_arrangement": {
        "tenant_pays": ("chiller", "cooling", "empower", "emicool", "ac ", "a/c", "tabreed"),
        "landlord_pays": ("chiller", "cooling", "empower", "emicool", "a/c", "tabreed"),
    },
    "title.tenure": {
        "freehold": ("freehold",),
        "non_freehold": ("non-freehold", "non freehold", "leasehold", "gcc national", "uae national",
                         "restricted", "grant"),
    },
    "title.ownership": {
        "single_title": ("single title", "single-title", "one title deed", "single title deed",
                         "single plot title", "whole-building title", "single freehold title",
                         "title deed in the name", "land and building"),
        "strata": ("strata", "jointly owned", "owners association", "owners' association", "title deeds",
                   "mollak", "oa "),
    },
    "lease_structure": {
        "master_lease": ("master lease", "bulk lease", "master tenant", "head lease", "guaranteed",
                         "single tenant", "leased in its entirety", "fixed return", "master-lease"),
        "direct_leases": ("tenant", "lease", "ejari", "let ", "tenancies", "occupied"),
    },
}

# Market-area aliases: the quote must contain the area key or one of these. Names, not numbers.
AREA_ALIASES: dict[str, tuple[str, ...]] = {
    "JVC": ("jvc", "jumeirah village circle"),
    "Dubai Silicon Oasis": ("silicon oasis", "dso"),
    "International City": ("international city", "warsan"),
    "Al Barsha South": ("al barsha south", "barsha south"),
    "Business Bay": ("business bay",),
}

# Sub-areas that share a name with a mandate area but are not in it.
NOT_IN_AREA: dict[str, tuple[str, ...]] = {
    "Al Barsha South": ("al barsha 1", "al barsha 2", "al barsha 3", "al barsha first", "al barsha second",
                        "al barsha third", "barsha heights", "tecom", "al thanyah"),
}

NUMERIC_UNITS = {
    "completion_year": "plain", "unit_count": "plain", "parking_spaces": "plain",
    "bua_sqft": "area", "nsa_sqft": "area", "occupancy_stated": "ratio", "annual_rent_stated": "AED",
    "net_income_stated_aed": "AED", "opex_stated_aed": "AED", "yield_stated": "ratio",
    "asking_price_aed": "AED", "price_psf_stated": "AED",
}
TEXT_FIELDS = {"building_name", "area", "plot_number", "floors"}


def contains_any(quote: str, words: tuple[str, ...]) -> str | None:
    """The first of ``words`` found in the normalised quote, else None."""
    q = f" {normalise(quote)} "
    for w in words:
        if normalise(w) in q or w in q:
            return w
    return None


def _check_value(name: str, raw: dict) -> tuple[bool, str, Any]:
    """Does the value follow from the quote? Returns (ok, explanation, normalised value)."""
    value, quote, unit = raw.get("value"), raw.get("quote") or "", raw.get("unit")
    if name in NUMERIC_UNITS:
        kind = NUMERIC_UNITS[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False, f"value {value!r} is not a number", value
        v = float(value)
        note = ""
        if kind == "ratio" and v > 1.0:
            v, note = v / 100.0, " (model gave a percentage; converted to a ratio)"
        if kind == "area":
            # a value in sq ft may also come from a sq m figure in the quote (converted at 10.7639)
            ok, how = value_in_quote(v, quote, "sqm" if unit == "sqm" else "sqft")
            sqft = v * config.SQM_TO_SQFT if unit == "sqm" else v
            return ok, how + note, round(sqft, 1)
        ok, how = value_in_quote(v, quote, "ratio" if kind == "ratio" else ("AED" if kind == "AED" else None))
        if name in ("completion_year", "unit_count", "parking_spaces"):
            v = int(round(v))
        return ok, how + note, v
    if name in TEXT_FIELDS:
        if not isinstance(value, str) or not value.strip():
            return False, "empty text value", value
        ok = loose(value) in loose(quote)
        return ok, "text appears in quote" if ok else "text value does not appear in the quote", value.strip()
    if name == "market_area":
        if value == "none_of_these":
            return True, "model found no listed market area", value
        other = contains_any(quote, NOT_IN_AREA.get(value, ()))
        if other:
            return False, f"quote names {other!r}, which is not {value}", value
        hit = contains_any(quote, (value.lower(),) + AREA_ALIASES.get(value, ()))
        return bool(hit), (f"quote names {hit!r}" if hit else f"quote does not name {value}"), value
    if name in ("asset_type", "chiller_arrangement"):
        hit = contains_any(quote, ENUM_KEYWORDS[name].get(value, ()))
        return bool(hit), (f"classification backed by {hit!r} in quote" if hit
                           else f"no keyword in the quote supports {value!r}"), value
    if name == "title_type":
        problems, notes = [], []
        for part in ("tenure", "ownership"):
            sub = (value or {}).get(part, "unstated")
            if sub == "unstated":
                continue
            hit = contains_any(quote, ENUM_KEYWORDS[f"title.{part}"].get(sub, ()))
            if sub == "freehold" and hit and contains_any(quote, ("non-freehold", "non freehold")):
                hit = None
            (notes if hit else problems).append(f"{part}={sub}" + (f" ({hit!r})" if hit else ""))
        if problems:
            return False, "no keyword in the quote supports " + ", ".join(problems), value
        return True, "backed by " + ", ".join(notes) if notes else "both parts unstated", value
    if name == "lease_structure":
        typ = (value or {}).get("type", "unstated")
        hit = contains_any(quote, ENUM_KEYWORDS["lease_structure"].get(typ, ()))
        return bool(hit), (f"backed by {hit!r}" if hit else f"no keyword in the quote supports {typ!r}"), value
    if name == "unit_mix":
        counts = {k: v for k, v in (value or {}).items() if isinstance(v, int)}
        if not counts:
            return False, "no counts given", value
        nums = [n.value for n in parse_numbers(quote)]
        missing = [f"{k}={v}" for k, v in counts.items() if v and not any(close(v, n) for n in nums)]
        if missing:
            return False, "counts not in quote: " + ", ".join(missing), value
        return True, "every count appears in the quote", counts
    return False, f"no verification rule for field {name}", value


def _is_stated(raw: dict | None) -> bool:
    if not raw:
        return False
    v = raw.get("value")
    if v is None or v == "unstated" or v == {}:
        return False
    if isinstance(v, dict) and v and all(x in (None, "unstated") for x in v.values()):
        return False
    return True


def verify_field(name: str, raw: dict | None, docs: list[Document]) -> dict:
    """Verify one extracted OM field; returns the run.json field record."""
    raw = raw or {}
    out: dict[str, Any] = {
        "value": None, "unit": raw.get("unit"), "as_of": raw.get("as_of"), "quote": raw.get("quote"),
        "source": None, "status": NOT_STATED, "reason": raw.get("null_reason") or "not stated",
    }
    if "basis" in raw:
        out["basis"] = raw.get("basis")
    if not _is_stated(raw):
        out["value"] = raw.get("value") if raw.get("value") == "unstated" else None
        return out
    src = raw.get("source") or {}
    doc, qm, page_no = locate(docs, src.get("doc"), src.get("page"), raw.get("quote"))
    out["source"] = {"doc": doc.doc_id if doc else src.get("doc"), "page": page_no,
                     "bbox": qm.bboxes or [], "match": qm.method, "similarity": qm.similarity,
                     "ocr": bool(doc and doc.page(page_no or 0) and doc.page(page_no).ocr)}
    ok_value, how, value = _check_value(name, raw)
    out["value"] = value
    if name in ("bua_sqft", "nsa_sqft"):
        out["stated"] = {"value": raw.get("value"), "unit": raw.get("unit") or "sqft"}
        out["unit"] = "sqft"
    out["checks"] = {"quote": qm.reason or f"found ({qm.method})", "value": how}
    if not qm.found:
        out["status"], out["reason"] = UNVERIFIED, qm.reason
    elif not ok_value:
        out["status"], out["reason"] = UNVERIFIED, how
    else:
        out["status"] = VERIFIED_FUZZY if qm.method == "fuzzy" else VERIFIED
        out["reason"] = (f"fuzzy match on an OCR'd page (similarity {qm.similarity:.2f}); figures agree with OCR text"
                         if qm.method == "fuzzy" else None)
        if qm.reason:  # found on a different page than cited
            out["reason"] = qm.reason
    return out


def verify_upside_claims(claims: list[dict] | None, docs: list[Document]) -> list[dict]:
    """Each claim's quote must be on its page; a claimed uplift figure must parse from the quote."""
    out = []
    for c in claims or []:
        src = c.get("source") or {}
        doc, qm, page_no = locate(docs, src.get("doc"), src.get("page"), c.get("quote"))
        rec = {"quote": c.get("quote"), "applies_to": c.get("applies_to"), "claimed_uplift": c.get("claimed_uplift"),
               "source": {"doc": doc.doc_id if doc else src.get("doc"), "page": page_no, "bbox": qm.bboxes or [],
                          "match": qm.method, "similarity": qm.similarity}}
        status, reason = (VERIFIED_FUZZY if qm.method == "fuzzy" else VERIFIED) if qm.found else UNVERIFIED, qm.reason
        if qm.found and c.get("claimed_uplift") is not None:
            ok, how = value_in_quote(float(c["claimed_uplift"]), c.get("quote") or "", "ratio")
            if not ok:
                status, reason = UNVERIFIED, f"claimed uplift: {how}"
        rec["status"], rec["reason"] = status, reason
        out.append(rec)
    return out


def verify_evidence(evidence: list[dict] | None, docs: list[Document]) -> list[dict]:
    """Verify model-cited evidence (page quotes or cell quotes) for review findings and periods."""
    out = []
    for e in evidence or []:
        if e.get("cell"):
            qm = match_cell(docs, e.get("doc"), e.get("cell"), e.get("quote"))
            doc = find_doc(docs, e.get("doc"))
            out.append({"doc": doc.doc_id if doc else e.get("doc"), "cell": e.get("cell"), "quote": e.get("quote"),
                        "status": VERIFIED if qm.found else UNVERIFIED, "reason": qm.reason})
            continue
        doc, qm, page_no = locate(docs, e.get("doc"), e.get("page"), e.get("quote"))
        out.append({"doc": doc.doc_id if doc else e.get("doc"), "page": page_no, "quote": e.get("quote"),
                    "bbox": qm.bboxes or [], "match": qm.method,
                    "status": (VERIFIED_FUZZY if qm.method == "fuzzy" else VERIFIED) if qm.found else UNVERIFIED,
                    "reason": qm.reason})
    return out
