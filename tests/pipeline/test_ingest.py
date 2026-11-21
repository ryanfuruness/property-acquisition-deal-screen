import shutil

import pytest

from helpers import make_pdf, make_scanned_pdf, make_xlsx
from pipeline.ingest import (Document, a1, classify, col_index, col_letter, ingest_csv, ingest_package, ingest_pdf,
                             ingest_xlsx, parse_a1, render_pages, sheet_as_text, split_cell_ref)
from pipeline.loader import PackageLoader

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def test_a1_helpers():
    assert col_letter(1) == "A" and col_letter(27) == "AA" and col_index("AB") == 28
    assert parse_a1("B7") == (7, 2) and parse_a1("$C$12") == (12, 3)
    assert a1(7, 2) == "B7"
    assert split_cell_ref("'Rent Roll'!B7") == ("Rent Roll", "B7")
    assert split_cell_ref("B7") == (None, "B7")
    with pytest.raises(ValueError):
        parse_a1("Rent Roll")


def test_pdf_text_and_word_boxes(tmp_path):
    path = make_pdf(tmp_path / "om.pdf", [["Asking price AED 48,500,000", "Units 112"], ["Page two text here"]])
    doc = ingest_pdf(path, "om.pdf")
    assert len(doc.pages) == 2 and not doc.scanned
    p1 = doc.pages[0]
    assert "AED 48,500,000" in p1.text
    w = next(w for w in p1.words if w.text == "48,500,000")
    assert 0 < w.x0 < w.x1 < 1 and 0 < w.top < w.bottom < 0.2   # fractions of the page, near the top


@needs_tesseract
def test_scanned_page_is_ocrd_with_boxes(tmp_path):
    path = make_scanned_pdf(tmp_path / "scan.pdf", ["Asking Price AED 34,500,000", "Total Units 92"])
    doc = ingest_pdf(path, "scan.pdf")
    page = doc.pages[0]
    assert page.ocr and doc.scanned
    assert "34,500,000" in page.text
    assert page.ocr_mean_conf > 50
    assert all(0 <= w.x0 < w.x1 <= 1 for w in page.words)
    assert page.ocr_alternates, "other OCR passes are kept for the verifier"


def test_xlsx_grid_with_a1_addresses(tmp_path):
    path = make_xlsx(tmp_path / "rr.xlsx", {"Rent Roll": [["Unit", "Rent"], ["101", 45000], [None, None]]})
    doc = ingest_xlsx(path, "rr.xlsx")
    sheet = doc.sheet("rent roll")      # case-insensitive lookup
    assert sheet.get("A2") == "101" and sheet.get("B2") == 45000
    assert sheet.n_rows == 2            # trailing blank rows dropped
    assert "B2=45000" in sheet_as_text(sheet)


def test_csv_grid(tmp_path):
    path = tmp_path / "roll.csv"
    path.write_text("Unit;Rent\n101;45,000\n")
    doc = ingest_csv(path, "roll.csv")
    assert doc.sheets[0].get("B2") == "45,000"


def test_classify_by_name_then_content(tmp_path):
    for name, role in [("om.pdf", "om"), ("Opaline rent roll.xlsx", "rent_roll"),
                       ("KT_RentRoll_Export_20261031.xlsx", "rent_roll"),
                       ("Kestrel Tower P&L FY Oct25-Sep26.xlsx", "operating_statement"),
                       ("Jade Court Income Expenses Oct25-Sep26.xlsx", "operating_statement")]:
        assert classify(Document(name, tmp_path / name, "sheet"))[0] == role


def test_package_ingest_renders_png_pages_and_tables(tmp_path):
    pkg = tmp_path / "deals" / "d1" / "package"
    pkg.mkdir(parents=True)
    make_pdf(pkg / "om.pdf", [["Offering memorandum", "Asking price AED 1"]])
    make_pdf(pkg / "Tenancy List.pdf", [["Unit    Type    Rent", "101    Studio    45,000", "102    1 BR    60,000"]])
    out = tmp_path / "runs" / "d1"
    docs = ingest_package(PackageLoader("d1", tmp_path / "deals"), out / "pages", rel_to=out)
    om = next(d for d in docs if d.role == "om")
    assert om.pages[0].image == "pages/om-p1.png" and (out / "pages" / "om-p1.png").exists()
    roll = next(d for d in docs if d.role == "rent_roll")
    assert roll.sheets, "a PDF rent roll is turned into a cell grid"
    grid = roll.sheets[0]
    assert any(c.value == "45,000" and c.bbox for row in grid.rows for c in row)


def test_render_quantises_to_palette(tmp_path):
    from PIL import Image

    doc = ingest_pdf(make_pdf(tmp_path / "a.pdf", [["hello"]]), "a.pdf")
    render_pages(doc, tmp_path / "pages", tmp_path)
    img = Image.open(tmp_path / "pages" / "a-p1.png")
    assert img.mode == "P" and img.size[0] > 1000
