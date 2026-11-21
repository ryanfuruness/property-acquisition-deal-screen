"""Stage 4, rent roll: the model maps the layout, code parses every unit and computes the summary.

The model says where the header is, what each column means, which rows are totals or
section headings, and how statuses and unit types are spelled. Code then reads every cell
itself, so no rent figure passes through the model. Each parsed unit keeps the address of
every cell it came from (and, for a PDF rent roll, the page and box).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import Any

from . import config
from .ingest import Document, Sheet, a1, col_index, parse_a1, sheet_as_text, split_cell_ref
from .llm import ModelClient, ToolResult, load_prompt
from .numbers import parse_date, parse_number
from .schemas import RENT_ROLL_MAP_TOOL

LET_STATUSES = ("occupied", "under_renewal", "notice_served", "legal_case")   # tenant in place
ENGINE_UNIT_TYPES = ("studio", "1br", "2br", "3br", "retail")

_ASKING_IN_TEXT = re.compile(r"asking(?:\s+rent)?\D{0,12}?(?:AED\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})", re.I)
# Remark cues that refine an "occupied" status. Order matters: "not renewing" is a notice, not a renewal.
_REMARK_STATUS = (
    ("legal_case", re.compile(r"\b(legal|rdc|case filed|bounced|eviction)\b", re.I)),
    ("notice_served", re.compile(r"vacat|notice|leaving|not renew|moving out", re.I)),
    ("under_renewal", re.compile(r"renew", re.I)),
)
_REMARK_HEADER = re.compile(r"remark|note|comment", re.I)

_TOTAL_LABEL = re.compile(r"\b(total|subtotal|sub-total|grand total|sum)\b", re.I)

# Fallbacks when a value is not in the model's vocabulary (code never trusts a silent guess:
# every fallback is recorded on the unit as a note).
_STATUS_PATTERNS = (
    ("legal_case", r"legal|rdc|case|bounced|dispute"),
    ("notice_served", r"notice|vacating|leaving"),
    ("under_renewal", r"renew|holdover|holding"),
    ("vacant", r"vacant|available|empty|unlet|to let"),
    ("occupied", r"occupied|leased|let|rented|active"),
)
_TYPE_PATTERNS = (
    ("retail", r"shop|retail|ret\b|commercial"),
    ("studio", r"studio|stu\b|\bst\b"),
    ("3br", r"\b3|three"),
    ("2br", r"\b2|two"),
    ("1br", r"\b1|one"),
)


# ---------------------------------------------------------------------------- model mapping


def map_layout(client: ModelClient, model: str, doc: Document) -> ToolResult:
    """Ask the model for the rent-roll layout."""
    grids = "\n\n".join(sheet_as_text(s) for s in doc.sheets)
    content = [{"type": "text", "text": f"Rent roll document `{doc.doc_id}`:\n\n{grids}"}]
    return client.call_tool(stage="rent_roll_map", model=model, system=load_prompt("rent_roll_map"),
                            content=content, tools=[RENT_ROLL_MAP_TOOL], tool_name=RENT_ROLL_MAP_TOOL["name"])


# ---------------------------------------------------------------------------- parsing


def _lookup(vocab: list[dict], key: str, text: str | None) -> str | None:
    if text is None:
        return None
    t = " ".join(str(text).split()).lower()
    for v in vocab or []:
        if " ".join(str(v.get("text", "")).split()).lower() == t:
            return v.get(key)
    return None


def _fallback(patterns, text: str | None) -> str | None:
    if not text:
        return None
    t = str(text).lower()
    for value, pat in patterns:
        if re.search(pat, t):
            return value
    return None


_PLACEHOLDERS = {"-", "–", "—", "--", "n/a", "na", "nil", "none", "tbc", "tba", "."}


def _text(v: Any) -> str | None:
    """Cell text, with empty cells and placeholders ('-', 'n/a') as None."""
    if v is None:
        return None
    s = str(v).strip()
    return None if not s or s.lower() in _PLACEHOLDERS else s


def _ref(sheet: Sheet, row: int, col: int) -> str:
    return f"{sheet.name}!{a1(row, col)}"


def parse_units(doc: Document, layout: dict) -> tuple[list[dict], list[dict]]:
    """Parse every unit row. Returns (units, skipped rows with reasons)."""
    day_first = layout.get("date_format", "DMY") != "MDY"
    units: list[dict] = []
    skipped: list[dict] = []
    for table in layout.get("tables", []):
        sheet = doc.sheet(table.get("sheet", ""))
        if sheet is None:
            skipped.append({"row": None, "sheet": table.get("sheet"), "reason": "sheet named by the layout not found"})
            continue
        cols: dict[str, tuple[int, dict]] = {}
        for c in table.get("columns", []):
            if c.get("field") and c["field"] != "ignore":
                try:
                    cols.setdefault(c["field"], (col_index(c["column"]), c))
                except (KeyError, TypeError):
                    continue
        remark_cols = _remark_columns(sheet, table, cols)
        excluded = {int(e["row"]): e.get("kind", "other") for e in table.get("exclude_rows", []) if "row" in e}
        first, last = int(table.get("first_data_row", 1)), int(table.get("last_data_row", sheet.n_rows))
        role = table.get("role", "unit_leases")
        for r in range(first, min(last, sheet.n_rows) + 1):
            if r in excluded:
                skipped.append({"sheet": sheet.name, "row": r, "reason": f"excluded by layout ({excluded[r]})"})
                continue
            rec = _parse_row(sheet, r, cols, layout, day_first, remark_cols)
            if rec is None:
                skipped.append({"sheet": sheet.name, "row": r, "reason": "blank row"})
                continue
            label = " ".join(str(sheet.value(r, c) or "") for c in range(1, min(sheet.n_cols, 3) + 1))
            if _TOTAL_LABEL.search(label) or _TOTAL_LABEL.search(str(rec.get("unit") or "")):
                skipped.append({"sheet": sheet.name, "row": r, "reason": "total row (label) excluded by code"})
                continue
            if rec.get("unit") is None and rec.get("annual_rent_aed") is None and rec.get("area_sqft") is None:
                skipped.append({"sheet": sheet.name, "row": r, "reason": "no unit, rent or area: not a unit row"})
                continue
            rec["table_role"] = role
            units.append(rec)
    return units, skipped


def parse_master_lease(doc: Document, layout: dict) -> dict | None:
    """Read the master lease's terms from the cells the layout names. None if there is no master lease."""
    spec = layout.get("master_lease") or {}
    if not spec.get("annual_rent_cell"):
        return None
    day_first = layout.get("date_format", "DMY") != "MDY"
    vals, cells = {}, {}
    for field in ("tenant", "annual_rent", "lease_start", "lease_end", "cheques"):
        ref = spec.get(f"{field}_cell")
        if not ref:
            continue
        sheet_name, addr = split_cell_ref(ref)
        sheet = doc.sheet(sheet_name) if sheet_name else (doc.sheets[0] if doc.sheets else None)
        try:
            vals[field] = sheet.get(addr) if sheet else None
        except ValueError:
            vals[field] = None
        cells[field] = f"{sheet.name}!{addr}" if sheet else ref
    start, end = parse_date(vals.get("lease_start"), day_first), parse_date(vals.get("lease_end"), day_first)
    cheques = parse_number(vals.get("cheques"))
    return {"tenant": _text(vals.get("tenant")), "annual_rent_aed": parse_number(vals.get("annual_rent")),
            "lease_start": start.isoformat() if start else None, "lease_end": end.isoformat() if end else None,
            "cheques": int(cheques) if cheques is not None else None,
            "source": {"doc": doc.doc_id, "cells": cells, "range": ", ".join(cells.values())}}


def _remark_columns(sheet: Sheet, table: dict, cols: dict) -> list[int]:
    """Remarks columns: mapped as ``remarks``, or any header cell that says remark / note / comment."""
    found = [cols["remarks"][0]] if "remarks" in cols else []
    for c in table.get("columns", []):
        if _REMARK_HEADER.search(str(c.get("header_text") or "")):
            try:
                found.append(col_index(c["column"]))
            except (KeyError, TypeError):
                pass
    for hr in table.get("header_rows", []) or []:
        for ci in range(1, sheet.n_cols + 1):
            v = sheet.value(int(hr), ci)
            if isinstance(v, str) and len(v) < 25 and _REMARK_HEADER.search(v):
                found.append(ci)
    return sorted(set(found))


def _parse_row(sheet: Sheet, r: int, cols: dict, layout: dict, day_first: bool,
               remark_cols: list[int] = ()) -> dict | None:
    raw: dict[str, Any] = {f: (sheet.value(r, ci) if not isinstance(sheet.value(r, ci), str)
                               else _text(sheet.value(r, ci))) for f, (ci, _) in cols.items()}
    if all(v is None for v in raw.values()):
        return None
    notes: list[str] = []
    cells = {f: _ref(sheet, r, ci) for f, (ci, _) in cols.items() if sheet.value(r, ci) is not None}
    boxes = {}
    if sheet.page is not None:
        for f, (ci, _) in cols.items():
            cell = sheet.cell(r, ci)
            if cell is not None and cell.bbox is not None and cell.value is not None:
                boxes[f] = list(cell.bbox)

    # area
    area = parse_number(raw.get("area"))
    area_unit = (cols.get("area", (0, {}))[1].get("unit_of_measure") or "sqft") if "area" in cols else None
    area_sqft = None
    area_original = None
    if area is not None and area > 0:
        if area_unit == "sqm":
            area_sqft = round(area * config.SQM_TO_SQFT, 2)
            area_original = {"value": area, "unit": "sqm"}
        else:
            area_sqft = area

    # rent
    rent = parse_number(raw.get("annual_rent"))
    rent_unit = cols.get("annual_rent", (0, {}))[1].get("unit_of_measure") if "annual_rent" in cols else None
    if rent is None and raw.get("monthly_rent") is not None:
        m = parse_number(raw.get("monthly_rent"))
        rent = None if m is None else m * 12
        if rent is not None:
            notes.append("annual rent = monthly rent x 12")
    elif rent is not None and rent_unit == "AED_per_month":
        rent *= 12
        notes.append("rent column is monthly; x 12")
    asking = parse_number(raw.get("asking_rent"))

    # status
    status_text = _text(raw.get("status"))
    status = _lookup(layout.get("status_vocabulary"), "status", status_text)
    if status is None and status_text:
        status = _fallback(_STATUS_PATTERNS, status_text)
        if status:
            notes.append(f"status {status_text!r} not in the mapped vocabulary; read as {status}")
    tenant = _text(raw.get("tenant"))
    if status is None:
        status = "occupied" if (tenant and rent) else "vacant"
        notes.append(f"no status given; inferred {status} from tenant and rent")

    # unit type
    type_text = _text(raw.get("unit_type"))
    unit_type = _lookup(layout.get("unit_type_vocabulary"), "unit_type", type_text)
    if unit_type is None and type_text:
        unit_type = _fallback(_TYPE_PATTERNS, type_text)
        if unit_type:
            notes.append(f"type {type_text!r} not in the mapped vocabulary; read as {unit_type}")

    status_stated = status            # as the roll's status column says, before remarks refine it
    remarks = " | ".join(str(sheet.value(r, c)) for c in remark_cols if _text(sheet.value(r, c)))
    if status == "vacant" and asking is None and remarks:
        m = _ASKING_IN_TEXT.search(remarks)
        if m:
            asking = float(m.group(1).replace(",", ""))
            notes.append(f"asking rent read from remarks ({remarks!r})")
    if status == "occupied" and remarks:
        for refined, cue in _REMARK_STATUS:
            if cue.search(remarks):
                status = refined
                notes.append(f"status refined to {refined} from remarks ({remarks!r})")
                break

    # vacant rows that carry a rent figure carry an asking rent, never in-place income
    if status == "vacant" and rent:
        asking = asking or rent
        notes.append("vacant unit shows a rent figure; treated as asking rent, not income")
        rent = None

    lease_start = parse_date(raw.get("lease_start"), day_first)
    lease_end = parse_date(raw.get("lease_end"), day_first)
    for f, val in (("lease_start", lease_start), ("lease_end", lease_end)):
        if raw.get(f) is not None and val is None:
            notes.append(f"{f} {raw.get(f)!r} could not be read as a date")
    cheques = parse_number(raw.get("cheques"))
    return {
        "unit": _text(raw.get("unit")),
        "unit_type": unit_type,
        "unit_type_text": type_text,
        "floor": _text(raw.get("floor")),
        "area_sqft": area_sqft,
        "area_original": area_original,
        "tenant": tenant,
        "tenant_type": _text(raw.get("tenant_type")),
        "ejari_no": _text(raw.get("ejari_no")),
        "lease_start": lease_start.isoformat() if lease_start else None,
        "lease_end": lease_end.isoformat() if lease_end else None,
        "annual_rent_aed": rent,
        "asking_rent_aed": asking,
        "cheques": int(cheques) if cheques is not None else None,
        "deposit_aed": parse_number(raw.get("deposit")),
        "status": status,
        "status_text": status_text,
        "status_stated": status_stated,
        "chiller": _text(raw.get("chiller")),
        "remarks": remarks or None,
        "source": {"doc": None, "sheet": sheet.name, "row": r,
                   "range": f"{sheet.name}!A{r}:{a1(r, max(sheet.n_cols, 1))}",
                   "cells": cells, "page": sheet.page, "bbox": boxes or None},
        "notes": notes,
    }


# ---------------------------------------------------------------------------- as-of date


_DATE_CUE = re.compile(r"\b(as\s+(?:on|at|of)|dated|updated|run\s+date|position|prepared|report\s+date|"
                       r"rent\s+roll\s+date|date)\b", re.I)


def roll_date(doc: Document, layout: dict) -> tuple[dt.date | None, dict | None]:
    """The rent roll date, read by code. In order: the cell the model pointed to; a line of sheet or page
    text with a date cue ("as at", "as on", "updated", "run date"...); the file name. A month without a day
    is read as month end, and the source says so."""
    day_first = layout.get("date_format", "DMY") != "MDY"
    cell = (layout.get("as_of") or {}).get("cell")
    if cell:
        sheet_name, addr = split_cell_ref(cell)
        sheet = doc.sheet(sheet_name) if sheet_name else (doc.sheets[0] if doc.sheets else None)
        if sheet is not None:
            try:
                text = sheet.get(addr)
            except ValueError:
                text = None
            d = parse_date(text, day_first) or _date_in_text(str(text or ""), day_first)
            if d:
                return d, _date_source(doc, str(text), f"{sheet.name}!{addr}", None, "cell named by the layout", day_first)
    for text, where_cell, where_page in _text_lines(doc):
        if _DATE_CUE.search(text):
            d = _date_in_text(text, day_first)
            if d:
                return d, _date_source(doc, text, where_cell, where_page, "dated line in the document", day_first)
    for text, where_cell, where_page in _title_lines(doc):
        d = _full_date_in_text(text, day_first)
        if d:
            return d, _date_source(doc, text, where_cell, where_page, "date in the title", day_first)
    name = re.sub(r"[_]+", " ", doc.doc_id)
    d = _date_in_text(name, day_first)
    if d:
        return d, _date_source(doc, doc.doc_id, None, None, "file name", day_first)
    return None, None


def _text_lines(doc: Document):
    """(text, cell, page) for the header and footer rows of each sheet and the lines of each PDF page."""
    for sheet in doc.sheets:
        if sheet.page is not None:
            continue
        rows = list(range(1, min(sheet.n_rows, 10) + 1)) + list(range(max(11, sheet.n_rows - 4), sheet.n_rows + 1))
        for r in rows:
            for c in range(1, sheet.n_cols + 1):
                v = sheet.value(r, c)
                if isinstance(v, str):
                    yield v, f"{sheet.name}!{a1(r, c)}", None
    for page in doc.pages:
        for line in page.text.splitlines():
            yield line, None, page.number


def _title_lines(doc: Document):
    """Title-like text: an early sheet row with a single filled cell, or one of the first lines of a PDF."""
    for sheet in doc.sheets:
        if sheet.page is not None:
            continue
        for r in range(1, min(sheet.n_rows, 5) + 1):
            filled = [(c, sheet.value(r, c)) for c in range(1, sheet.n_cols + 1) if sheet.value(r, c) is not None]
            if len(filled) == 1 and isinstance(filled[0][1], str):
                yield filled[0][1], f"{sheet.name}!{a1(r, filled[0][0])}", None
    if doc.pages:
        for line in doc.pages[0].text.splitlines()[:4]:
            yield line, None, 1


def _date_source(doc: Document, quote: str, cell: str | None, page: int | None, how: str, day_first: bool) -> dict:
    month_only = _full_date_in_text(quote, day_first) is None and parse_date(quote, day_first) is None
    return {"doc": doc.doc_id, "cell": cell, "page": page, "quote": quote,
            "how": how + ("; month only, read as month end" if month_only else "")}


def _date_in_text(text: str, day_first: bool) -> dt.date | None:
    """A full date in free text, else a month and year read as month end."""
    return _full_date_in_text(text, day_first) or _month_end_in_text(text)


def _full_date_in_text(text: str, day_first: bool) -> dt.date | None:
    pats = [r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", r"(?<!\d)\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2})(?!\d)",
            r"(?<!\d)\d{1,2}\s*[A-Za-z]{3,9},?\s*\d{4}", r"[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}"]
    for p in pats:
        m = re.search(p, text)
        if m:
            d = parse_date(m.group(0), day_first)
            if d:
                return d
    m = re.search(r"\b\d{8}\b", text)  # 20261031
    if m:
        s = m.group(0)
        return parse_date(f"{s[:4]}-{s[4:6]}-{s[6:]}")
    return None


def _month_end_in_text(text: str) -> dt.date | None:
    """'Oct 26', 'Oct-2026', 'October 2026' -> last day of that month (a month-only date is read as month end)."""
    m = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-_.]*('?\d{2}|\d{4})\b", text, re.I)
    if not m:
        return None
    month = parse_date(f"1 {m.group(1)} 2000").month
    year = int(m.group(2).lstrip("'"))
    year += 2000 if year < 100 else 0
    first_next = dt.date(year + (month == 12), month % 12 + 1, 1)
    return first_next - dt.timedelta(days=1)


# ---------------------------------------------------------------------------- summary


def _quarter(d: dt.date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def summarise(units: list[dict], as_of: dt.date | None) -> dict:
    """Unit-level statistics the reconcile rules and the memo use. All computed here, in code."""
    n = len(units)
    let = [u for u in units if u["status"] in LET_STATUSES]
    vacant = [u for u in units if u["status"] == "vacant"]
    area_total = sum(u["area_sqft"] or 0 for u in units)
    area_let = sum(u["area_sqft"] or 0 for u in let)
    in_place = sum(u["annual_rent_aed"] or 0 for u in let)
    asking_vacant = sum(u["asking_rent_aed"] or 0 for u in vacant)
    by_type: dict[str, dict] = defaultdict(lambda: {"units": 0, "let": 0, "area_sqft": 0.0, "rent_aed": 0.0,
                                                    "let_area_sqft": 0.0})
    for u in units:
        t = by_type[u["unit_type"] or "unknown"]
        t["units"] += 1
        t["area_sqft"] += u["area_sqft"] or 0
        if u["status"] in LET_STATUSES and u["annual_rent_aed"]:
            t["let"] += 1
            t["rent_aed"] += u["annual_rent_aed"]
            t["let_area_sqft"] += u["area_sqft"] or 0
    for t in by_type.values():
        t["avg_rent_psf"] = round(t["rent_aed"] / t["let_area_sqft"], 2) if t["let_area_sqft"] else None
        t["avg_rent_aed"] = round(t["rent_aed"] / t["let"], 0) if t["let"] else None
        t["area_sqft"] = round(t["area_sqft"], 1)

    expiry_q: dict[str, float] = defaultdict(float)
    no_end = 0
    for u in let:
        if u["lease_end"] and u["annual_rent_aed"]:
            expiry_q[_quarter(dt.date.fromisoformat(u["lease_end"]))] += u["annual_rent_aed"]
        elif u["annual_rent_aed"]:
            no_end += 1
    expiry = [{"quarter": q, "rent_aed": round(v, 0), "share": round(v / in_place, 4) if in_place else None}
              for q, v in sorted(expiry_q.items())]

    expired = []
    if as_of:
        # shown as occupied on the roll itself (a remark such as "renewal to follow" does not make it a new lease)
        expired = [u["unit"] for u in let
                   if u.get("status_stated", u["status"]) == "occupied" and u["lease_end"]
                   and dt.date.fromisoformat(u["lease_end"]) < as_of]
    missing_ejari = [u["unit"] for u in let if not u["ejari_no"]]
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "unit_count": n,
        "let_units": len(let),
        "vacant_units": len(vacant),
        "status_counts": {s: sum(1 for u in units if u["status"] == s)
                          for s in ("occupied", "under_renewal", "notice_served", "legal_case", "vacant")},
        "occupancy_by_units": round(len(let) / n, 4) if n else None,
        "occupancy_by_area": round(area_let / area_total, 4) if area_total else None,
        "area_sqft_total": round(area_total, 1),
        "in_place_rent_aed": round(in_place, 2),
        "legal_case_rent_aed": round(sum(u["annual_rent_aed"] or 0 for u in let if u["status"] == "legal_case"), 2),
        "vacant_asking_rent_aed": round(asking_vacant, 2),
        "vacant_units_with_asking_rent": sum(1 for u in vacant if u["asking_rent_aed"]),
        "potential_rent_aed": round(in_place + asking_vacant, 2),
        "by_type": dict(sorted(by_type.items())),
        "expiry_by_quarter": expiry,
        "max_quarter_expiry_share": max((e["share"] or 0 for e in expiry), default=None),
        "let_units_without_lease_end": no_end,
        "expired_leases_shown_occupied": expired,
        "let_units_missing_ejari": missing_ejari,
        "deposits_aed": round(sum(u["deposit_aed"] or 0 for u in units), 2),
        "units_unparsed_type": [u["unit"] for u in units if u["unit_type"] not in ENGINE_UNIT_TYPES],
        "units_without_area": [u["unit"] for u in units if not u["area_sqft"]],
        "let_units_without_rent": [u["unit"] for u in let if not u["annual_rent_aed"]],
    }


def stated_totals(doc: Document, layout: dict) -> list[dict]:
    """Read each summary-row cell the model pointed to; code parses the value."""
    out = []
    for s in layout.get("summary_rows", []):
        sheet = doc.sheet(s.get("sheet", ""))
        if sheet is None:
            continue
        for c in s.get("cells", []):
            try:
                row, col = parse_a1(c["cell"].split("!")[-1])
            except (KeyError, ValueError):
                continue
            raw = sheet.value(row, col)
            value = parse_number(raw)
            if value is None:
                continue
            if c.get("measure") == "occupancy" and value > 1:
                value /= 100.0
            cell = sheet.cell(row, col)
            out.append({"measure": c.get("measure"), "label": s.get("label"), "value": value, "raw": raw,
                        "cell": f"{sheet.name}!{a1(row, col)}", "page": sheet.page,
                        "bbox": list(cell.bbox) if cell is not None and cell.bbox else None})
    return out


def run_rent_roll(client: ModelClient, model: str, doc: Document) -> tuple[dict, ToolResult]:
    """Map, parse and summarise. Returns the run.json ``rent_roll`` block and the model result."""
    result = map_layout(client, model, doc)
    return build_rent_roll(doc, result.data), result


def build_rent_roll(doc: Document, layout: dict) -> dict:
    """Everything after the model call: parse, date, summarise, read stated totals."""
    units, skipped = parse_units(doc, layout)
    for u in units:
        u["source"]["doc"] = doc.doc_id
    master = parse_master_lease(doc, layout)
    as_of, as_of_src = roll_date(doc, layout)
    summary = summarise(units, as_of)
    return {
        "doc": doc.doc_id,
        "layout": layout,
        "as_of_source": as_of_src,
        "units": units,
        "skipped_rows": skipped,
        "master_lease": master,
        "stated_totals": stated_totals(doc, layout),
        "summary": summary,
    }
