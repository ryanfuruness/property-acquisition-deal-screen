"""What the deal documents themselves show, read independently of the pipeline.

truth.json is generated from the true building, so a few truth values are facts the broker's
documents never print (most often the asking rent of a vacant unit). The scorer only expects the
run to report what a careful analyst could read: for those values it checks the document text.
Readers: openpyxl for .xlsx, csv for .csv, pdfplumber for text PDFs (a scanned page has no text,
so nothing on it counts as visible).
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from .common import DEALS_DIR


@lru_cache(maxsize=None)
def rows_text(path_str: str) -> tuple[str, ...]:
    """One string per spreadsheet row / CSV line / PDF text line."""
    path = Path(path_str)
    suffix = path.suffix.lower()
    out: list[str] = []
    try:
        if suffix in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    out.append(" | ".join("" if v is None else str(v) for v in row))
        elif suffix == ".csv":
            with open(path, newline="", encoding="utf-8-sig") as fh:
                out = [" | ".join(r) for r in csv.reader(fh)]
        elif suffix == ".pdf":
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    out += (page.extract_text() or "").split("\n")
    except Exception:  # noqa: BLE001 - unreadable document: nothing is visible
        return ()
    return tuple(out)


def _num_patterns(value: float) -> list[re.Pattern]:
    v = int(round(value))
    plain, comma = str(v), f"{v:,}"
    pats = [rf"(?<![\d,.]){re.escape(comma)}(?![\d,])", rf"(?<![\d,.]){re.escape(plain)}(?:\.0+)?(?![\d,])"]
    return [re.compile(p) for p in pats]


def value_in_unit_row(doc_path: Path, unit_id: str, value: float) -> bool:
    """Does a row/line that names this unit also print this amount?"""
    # the unit id as a whole token: not part of a number such as an area "412.40" or an amount "1,412"
    uid = re.compile(rf"(?<![\w.,-]){re.escape(str(unit_id))}(?![\w-]|[.,]\d)", re.I)
    pats = _num_patterns(value)
    for line in rows_text(str(doc_path)):
        if uid.search(line) and any(p.search(line) for p in pats):
            return True
    return False


def rent_roll_path(truth: dict) -> Path | None:
    name = (truth.get("rent_roll") or {}).get("document")
    if not name:
        return None
    pkg = Path(truth.get("_package_dir") or DEALS_DIR / truth["deal_id"] / "package")
    p = pkg / name
    return p if p.exists() else None
