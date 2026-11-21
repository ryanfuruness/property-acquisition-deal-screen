"""Stage 1, ingest (code only).

* PDFs become per-page text with word boxes (pdfplumber). A page with no usable text layer is
  OCR'd with Tesseract, which gives text and word boxes too; such pages are marked ``ocr``.
* Tables on PDF pages (rent rolls and statements delivered as PDF) are also turned into cell
  grids, so the rent-roll and statement stages treat PDFs and spreadsheets alike.
* Spreadsheets and CSV files become A1-addressed cell grids.
* Every PDF page is rendered to a PNG for the site.

All coordinates are fractions of the page size (0-1, origin top-left), so the site can
overlay highlights on the page image at any resolution.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf
from PIL import Image, ImageFilter

from . import config
from .loader import PackageLoader

# --------------------------------------------------------------------------- data model


@dataclass
class Word:
    """A word on a page; box in page fractions (x0, top, x1, bottom)."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    conf: float | None = None  # OCR confidence 0-100; None for a text layer


@dataclass
class Page:
    number: int                 # 1-based
    width_pt: float
    height_pt: float
    text: str
    words: list[Word]
    ocr: bool = False
    ocr_mean_conf: float | None = None
    ocr_variant: str | None = None
    ocr_alternates: list[list[Word]] = field(default_factory=list)  # other OCR passes' words
    image: str | None = None    # path relative to runs/<deal_id>/


@dataclass
class Cell:
    value: Any
    bbox: tuple[float, float, float, float] | None = None  # page fractions, for PDF tables


@dataclass
class Sheet:
    """A grid of cells with A1 addresses. ``rows[r][c]`` is row r+1, column c+1."""

    name: str
    rows: list[list[Cell]]
    page: int | None = None     # source page when the grid came from a PDF table
    merged: list[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def cell(self, row: int, col: int) -> Cell | None:
        """1-based row and column."""
        if 1 <= row <= len(self.rows) and 1 <= col <= len(self.rows[row - 1]):
            return self.rows[row - 1][col - 1]
        return None

    def value(self, row: int, col: int) -> Any:
        c = self.cell(row, col)
        return None if c is None else c.value

    def get(self, address: str) -> Any:
        row, col = parse_a1(address)
        return self.value(row, col)


@dataclass
class Document:
    doc_id: str                 # path relative to package/, used in every citation
    path: Path
    kind: str                   # "pdf" or "sheet"
    pages: list[Page] = field(default_factory=list)
    sheets: list[Sheet] = field(default_factory=list)
    role: str = "unknown"       # om | rent_roll | operating_statement | unknown
    role_reason: str = ""

    @property
    def scanned(self) -> bool:
        return self.kind == "pdf" and any(p.ocr for p in self.pages)

    def page(self, number: int) -> Page | None:
        return self.pages[number - 1] if 1 <= number <= len(self.pages) else None

    def sheet(self, name: str) -> Sheet | None:
        for s in self.sheets:
            if s.name == name:
                return s
        lowered = {s.name.lower(): s for s in self.sheets}
        return lowered.get(name.lower())


# --------------------------------------------------------------------------- A1 helpers

_A1 = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def col_letter(col: int) -> str:
    """1 -> A, 27 -> AA."""
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def parse_a1(address: str) -> tuple[int, int]:
    """'B7' -> (7, 2). Raises ValueError on anything else."""
    m = _A1.match(address.strip())
    if not m:
        raise ValueError(f"not an A1 cell address: {address!r}")
    return int(m.group(2)), col_index(m.group(1))


def a1(row: int, col: int) -> str:
    return f"{col_letter(col)}{row}"


def split_cell_ref(ref: str) -> tuple[str | None, str]:
    """'Rent Roll!B7' -> ('Rent Roll', 'B7'); 'B7' -> (None, 'B7'). Quotes around the sheet are dropped."""
    if "!" in ref:
        sheet, addr = ref.rsplit("!", 1)
        return sheet.strip().strip("'"), addr.strip()
    return None, ref.strip()


# --------------------------------------------------------------------------- PDF


def _norm_box(x0: float, top: float, x1: float, bottom: float, w: float, h: float) -> tuple[float, ...]:
    return (round(max(0.0, x0 / w), 5), round(max(0.0, top / h), 5),
            round(min(1.0, x1 / w), 5), round(min(1.0, bottom / h), 5))


# OCR preprocessing variants: each is run and kept, because on a noisy scan no single pass reads
# every figure; the verifier may match a quote against any pass (and must still agree on figures).
OCR_VARIANTS = (
    ("blur_threshold", lambda img: img.filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: 255 if v > 180 else 0)),
    ("plain", lambda img: img),
    ("median", lambda img: img.filter(ImageFilter.MedianFilter(5))),
)


def _ocr_image(img: Image.Image) -> tuple[str, list[Word], float | None]:
    import pytesseract

    data = pytesseract.image_to_data(img, lang=config.OCR_LANG, output_type=pytesseract.Output.DICT)
    W, H = img.size
    words: list[Word] = []
    lines: dict[tuple, list[str]] = {}
    confs = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append(Word(text, *_norm_box(x, y, x + w, y + h, W, H), conf=conf))
        confs.append(conf)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(text)
    text = "\n".join(" ".join(ws) for ws in lines.values())
    return text, words, (sum(confs) / len(confs) if confs else None)


def _ocr_page(pdf_path: Path, index: int) -> list[tuple[str, str, list[Word], float | None]]:
    """OCR one page with each preprocessing variant; returns [(variant, text, words, mean conf)], best first."""
    with pymupdf.open(pdf_path) as doc:
        pix = doc[index].get_pixmap(dpi=config.OCR_DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    passes = [(name, *_ocr_image(fn(img))) for name, fn in OCR_VARIANTS]
    return sorted(passes, key=lambda p: -(p[3] or 0))


def _pdf_tables(page: "pdfplumber.page.Page", number: int) -> list[Sheet]:
    """Ruled tables on a page as cell grids, with cell boxes for highlighting."""
    sheets: list[Sheet] = []
    W, H = float(page.width), float(page.height)
    for k, table in enumerate(page.find_tables(), start=1):
        rows: list[list[Cell]] = []
        for row in table.rows:
            out_row = []
            for box in row.cells:
                if box is None:
                    out_row.append(Cell(None))
                    continue
                text = page.within_bbox(box).extract_text() or ""
                text = " ".join(text.split())
                out_row.append(Cell(text or None, _norm_box(*box, W, H)))
            rows.append(out_row)
        if len(rows) >= 2:
            sheets.append(Sheet(name=f"p{number}" + (f"t{k}" if k > 1 else ""), rows=rows, page=number))
    return sheets


def _text_table(page: "pdfplumber.page.Page", words: list[Word], number: int) -> Sheet | None:
    """Fallback for unruled PDF tables: rows from word lines, columns from x-gap clustering.

    Columns are found from the vertical gaps that run through most lines, so numbers align
    with their header. Used only when the page has no ruled table.
    """
    if not words:
        return None
    # group words into lines by vertical centre
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0)):
        mid = (w.top + w.bottom) / 2
        if lines and abs(((lines[-1][0].top + lines[-1][0].bottom) / 2) - mid) < 0.004:
            lines[-1].append(w)
        else:
            lines.append([w])
    # merge words into phrases where the gap is small (one space)
    phrases_by_line = []
    for line in lines:
        line.sort(key=lambda w: w.x0)
        phrases: list[list[Word]] = [[line[0]]]
        for w in line[1:]:
            prev = phrases[-1][-1]
            char_w = (prev.x1 - prev.x0) / max(len(prev.text), 1)
            if w.x0 - prev.x1 <= 1.6 * char_w:
                phrases[-1].append(w)
            else:
                phrases.append([w])
        phrases_by_line.append(phrases)
    # column boundaries: right edges of phrases cluster per column; use phrase start x
    starts = sorted(p[0].x0 for ph in phrases_by_line for p in ph)
    if not starts:
        return None
    centres: list[float] = []
    for x in starts:
        if not centres or x - centres[-1] > 0.03:
            centres.append(x)
    rows: list[list[Cell]] = []
    for phrases in phrases_by_line:
        row = [Cell(None) for _ in centres]
        for p in phrases:
            x_mid = p[0].x0
            col = min(range(len(centres)), key=lambda i: abs(centres[i] - x_mid))
            text = " ".join(w.text for w in p)
            box = (min(w.x0 for w in p), min(w.top for w in p), max(w.x1 for w in p), max(w.bottom for w in p))
            if row[col].value is None:
                row[col] = Cell(text, box)
            else:
                old = row[col]
                row[col] = Cell(f"{old.value} {text}", (min(old.bbox[0], box[0]), min(old.bbox[1], box[1]),
                                                       max(old.bbox[2], box[2]), max(old.bbox[3], box[3])))
        rows.append(row)
    return Sheet(name=f"p{number}", rows=rows, page=number) if len(rows) >= 2 else None


def ingest_pdf(path: Path, doc_id: str) -> Document:
    """Per-page text and word boxes; OCR (several passes) for image pages without a usable text layer."""
    doc = Document(doc_id=doc_id, path=path, kind="pdf")
    with pdfplumber.open(path) as pdf:
        for i, p in enumerate(pdf.pages):
            W, H = float(p.width), float(p.height)
            text = p.extract_text() or ""
            if len(text.strip()) >= config.OCR_MIN_TEXT_CHARS or not p.images:
                words = [Word(w["text"], *_norm_box(w["x0"], w["top"], w["x1"], w["bottom"], W, H))
                         for w in p.extract_words(keep_blank_chars=False, use_text_flow=False)]
                doc.pages.append(Page(i + 1, W, H, text, words))
                continue
            passes = _ocr_page(path, i)
            variant, ocr_text, words, conf = passes[0]
            doc.pages.append(Page(i + 1, W, H, ocr_text, words, ocr=True, ocr_mean_conf=conf, ocr_variant=variant,
                                  ocr_alternates=[p[2] for p in passes[1:]]))
    return doc


def add_pdf_tables(doc: Document) -> None:
    """Turn the tables on each text page into cell grids (ruled tables first, else column clustering)."""
    with pdfplumber.open(doc.path) as pdf:
        for page in doc.pages:
            if page.ocr:
                continue
            p = pdf.pages[page.number - 1]
            found = _pdf_tables(p, page.number)
            if not found:
                fallback = _text_table(p, page.words, page.number)
                found = [fallback] if fallback else []
            doc.sheets.extend(found)


def render_pages(doc: Document, out_dir: Path, rel_to: Path) -> None:
    """Render each page to ``<doc-slug>-p<N>.png`` and record the path on the page.

    Text pages: 144 dpi, 256-colour palette. Scanned pages: 108 dpi, 16 grey levels.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = doc_slug(doc.doc_id)
    with pymupdf.open(doc.path) as pdf:
        for page in doc.pages:
            zoom = config.SCAN_IMAGE_ZOOM if page.ocr else config.PAGE_IMAGE_ZOOM
            pix = pdf[page.number - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            if page.ocr:
                img = img.convert("L").quantize(colors=config.SCAN_IMAGE_GREYS)
            else:
                img = img.convert("RGB").quantize(colors=config.PAGE_IMAGE_COLOURS, method=Image.Quantize.MEDIANCUT)
            target = out_dir / f"{slug}-p{page.number}.png"
            img.save(target, optimize=True)
            page.image = target.relative_to(rel_to).as_posix()


def doc_slug(doc_id: str) -> str:
    stem = Path(doc_id).stem
    return re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower() or "doc"


# --------------------------------------------------------------------------- spreadsheets


def _cell_value(v: Any) -> Any:
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(timespec="minutes")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def ingest_xlsx(path: Path, doc_id: str) -> Document:
    """Every worksheet as a grid of computed values (``data_only``), with merged ranges."""
    import openpyxl

    doc = Document(doc_id=doc_id, path=path, kind="sheet")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    for ws in wb.worksheets:
        rows = [[Cell(_cell_value(c.value)) for c in row] for row in ws.iter_rows()]
        while rows and all(c.value is None for c in rows[-1]):
            rows.pop()
        merged = [str(r) for r in ws.merged_cells.ranges]
        doc.sheets.append(Sheet(name=ws.title, rows=rows, merged=merged))
    return doc


def ingest_csv(path: Path, doc_id: str) -> Document:
    """A CSV as one sheet named after the file; values stay strings and are parsed later."""
    raw = path.read_bytes().decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[Cell(_cell_value(v)) for v in r] for r in csv.reader(io.StringIO(raw), dialect)]
    return Document(doc_id=doc_id, path=path, kind="sheet", sheets=[Sheet(name=Path(doc_id).stem, rows=rows)])


# --------------------------------------------------------------------------- package


_ROLE_HINTS = {
    "rent_roll": ("rent roll", "rentroll", "rent_roll", "tenancy schedule", "tenancy list", "rent list",
                  "tenancy", "lease schedule", "ejari"),
    "operating_statement": ("t12", "t-12", "operating statement", "income & expense", "income and expense",
                            "income expenses", "p&l", "profit & loss", "income statement", "landlord statement",
                            "owner statement", "statement of income"),
    "om": ("offering memorandum", "information memorandum", "investment memorandum", "om", "teaser",
           "investment opportunity", "asking price"),
}


def classify(doc: Document) -> tuple[str, str]:
    """Guess a document's role from its file name, then its first page or sheet. Returns (role, reason)."""
    name = re.sub(r"[_\-.]+", " ", Path(doc.doc_id).stem.lower())
    padded = f" {name} "
    for role in ("rent_roll", "operating_statement", "om"):
        for hint in _ROLE_HINTS[role]:
            if f" {hint} " in padded or (len(hint) > 3 and hint in name):
                return role, f"file name contains {hint!r}"
    if doc.kind == "pdf" and doc.pages:
        head = " ".join(p.text for p in doc.pages[:2]).lower()
    else:
        head = " ".join(str(c.value) for s in doc.sheets[:1] for r in s.rows[:15] for c in r
                        if c.value is not None).lower()
    scores = {role: sum(head.count(h) for h in hints if len(h) > 3) for role, hints in _ROLE_HINTS.items()}
    if doc.kind == "pdf" and len(doc.pages) >= 4:
        scores["om"] += 2      # OMs are the long PDFs in a package
    role = max(scores, key=scores.get)
    if scores[role] == 0:
        return "unknown", "no role keywords found"
    return role, f"content keywords ({scores[role]} hits)"


def ingest_package(loader: PackageLoader, pages_dir: Path | None = None,
                   rel_to: Path | None = None) -> list[Document]:
    """Ingest every document in the package, classify it, and render PDF pages if asked."""
    docs: list[Document] = []
    for path in loader.documents():
        doc_id = loader.relative(path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            doc = ingest_pdf(path, doc_id)
        elif suffix == ".csv":
            doc = ingest_csv(path, doc_id)
        else:
            doc = ingest_xlsx(path, doc_id)
        doc.role, doc.role_reason = classify(doc)
        if doc.kind == "pdf" and doc.role in ("rent_roll", "operating_statement"):
            add_pdf_tables(doc)
        if doc.kind == "pdf" and pages_dir is not None:
            render_pages(doc, pages_dir, rel_to or pages_dir.parent)
        docs.append(doc)
    return docs


def sheet_as_text(sheet: Sheet, max_rows: int | None = None, max_chars: int = 60) -> str:
    """Compact grid rendering for the model: one line per non-empty row, ``A5=value`` cells."""
    lines = [f"### Sheet {sheet.name!r}" + (f" (table on PDF page {sheet.page})" if sheet.page else "")
             + f": {sheet.n_rows} rows x {sheet.n_cols} columns"]
    if sheet.merged:
        lines.append("merged: " + ", ".join(sheet.merged[:40]))
    for r, row in enumerate(sheet.rows[: max_rows or len(sheet.rows)], start=1):
        cells = []
        for c, cell in enumerate(row, start=1):
            if cell.value is None:
                continue
            text = str(cell.value).replace("\n", " ")
            if len(text) > max_chars:
                text = text[: max_chars - 1] + "…"
            cells.append(f"{a1(r, c)}={text}")
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)
