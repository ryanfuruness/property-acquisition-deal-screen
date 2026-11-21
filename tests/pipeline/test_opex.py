import pytest

from helpers import make_pdf, make_xlsx
from pipeline.ingest import ingest_pdf, ingest_xlsx
from pipeline.opex import build_opex

SHEET = [
    ["Income & Expense Statement FY2026 (Jan-Sep 2026, annualised)"],
    ["Line", "Jan-Sep"],
    ["Rental income", 900000],
    ["Parking", 9000],
    ["Bad debts", "(9,000)"],
    ["Maintenance", 45000],
    ["Insurance", 9000],
    ["Chiller charges", 90000],
    ["Total expenses", 144000],
    ["Loan interest", 30000],
    ["NOI", 756000],
]


def mapping(months=9, basis="period_total", presented=True):
    def line(label, cat, row, sign="expense"):
        return {"label": label, "category": cat, "label_cell": f"S!A{row}", "amount_cell": f"S!B{row}", "sign": sign}
    return {"period": {"start": "2026-01-01", "end": "2026-09-30", "months_covered": months,
                       "presented_as_annual": presented, "annualised": False,
                       "evidence": [{"doc": "st.xlsx", "cell": "S!A1", "quote": "Jan-Sep 2026"}]},
            "amount_basis": basis,
            "lines": [line("Rental income", "rental_income", 3, "income"), line("Parking", "other_income", 4, "income"),
                      line("Bad debts", "collection_loss", 5, "deduction"), line("Maintenance", "maintenance_repairs", 6),
                      line("Insurance", "insurance", 7), line("Chiller charges", "district_cooling", 8),
                      line("Total expenses", "total_or_subtotal", 9), line("Loan interest", "non_operating", 10)],
            "stated_totals": [{"label": "Total expenses", "measure": "total_expenses", "amount_cell": "S!B9"},
                              {"label": "NOI", "measure": "noi", "amount_cell": "S!B11"}],
            "vat_basis": "unstated"}


@pytest.fixture
def doc(tmp_path):
    return ingest_xlsx(make_xlsx(tmp_path / "st.xlsx", {"S": SHEET}), "st.xlsx")


def test_partial_period_annualised_by_code(doc):
    o = build_opex(doc, [doc], mapping(), chiller_landlord_pays=True)
    assert o["period"]["months_used"] == 9
    assert o["period"]["annualisation"]["factor"] == pytest.approx(12 / 9)
    assert o["totals_by_category"]["rental_income"] == pytest.approx(1_200_000)
    assert o["totals_by_category"]["collection_loss"] == pytest.approx(12_000)     # sign taken from category
    assert "non_operating" not in o["totals_by_category"]                          # loan interest excluded
    assert o["total_expenses_aed"] == pytest.approx(144000 * 12 / 9)
    assert all(c["foots"] for c in o["stated_total_checks"])


def test_absent_standard_categories(doc):
    o = build_opex(doc, [doc], mapping(), chiller_landlord_pays=True)
    assert set(o["absent_standard_categories"]) == {"property_management", "sinking_fund", "utilities_common",
                                                     "security_cleaning"}
    m = mapping()
    m["lines"] = [ln for ln in m["lines"] if ln["category"] != "district_cooling"]
    assert "district_cooling" in build_opex(doc, [doc], m, chiller_landlord_pays=True)["absent_standard_categories"]
    assert "district_cooling" not in build_opex(doc, [doc], m, chiller_landlord_pays=False)["absent_standard_categories"]


def test_already_annualised_amounts_are_not_scaled_again(doc):
    o = build_opex(doc, [doc], mapping(basis="annualised_total"), chiller_landlord_pays=None)
    assert o["period"]["annualisation"]["factor"] == 1.0
    assert "already annualised" in o["period"]["annualisation"]["note"]


def test_amount_cell_without_a_number_is_unverified(doc):
    m = mapping()
    m["lines"][3]["amount_cell"] = "S!A6"        # the label, not the amount
    o = build_opex(doc, [doc], m, chiller_landlord_pays=None)
    assert "Maintenance" in o["unverified_lines"] and "maintenance_repairs" not in o["totals_by_category"]


def test_month_cells_summed(tmp_path):
    d = ingest_xlsx(make_xlsx(tmp_path / "m.xlsx", {"T12": [["Line"] + [f"M{i}" for i in range(1, 13)],
                                                             ["Insurance"] + [1000] * 12]}), "m.xlsx")
    m = {"period": {"start": "2025-11-01", "end": "2026-10-31", "months_covered": 12, "presented_as_annual": True,
                    "annualised": False, "evidence": []},
         "amount_basis": "monthly_columns",
         "lines": [{"label": "Insurance", "category": "insurance", "month_cells": "T12!B2:M2", "sign": "expense"}],
         "stated_totals": [], "vat_basis": "unstated"}
    o = build_opex(d, [d], m, chiller_landlord_pays=None)
    assert o["totals_by_category"]["insurance"] == 12000 and o["period"]["months_used"] == 12


def test_pdf_line_from_verified_quote(tmp_path):
    d = ingest_pdf(make_pdf(tmp_path / "st.pdf", [["Insurance 99,487", "Management fees 335,268"]]), "st.pdf")
    m = {"period": {"start": "2025-09-01", "end": "2026-08-31", "months_covered": 12, "presented_as_annual": True,
                    "annualised": False, "evidence": []}, "amount_basis": "period_total",
         "lines": [{"label": "Insurance", "category": "insurance", "page": 1, "quote": "Insurance 99,487",
                    "amount_as_printed": "99,487", "sign": "expense"},
                   {"label": "Mgmt", "category": "property_management", "page": 1, "quote": "Management fees 335,268",
                    "amount_as_printed": "353,268", "sign": "expense"}],
         "stated_totals": [], "vat_basis": "unstated"}
    o = build_opex(d, [d], m, chiller_landlord_pays=None)
    assert o["totals_by_category"] == {"insurance": 99487}
    assert o["lines"][0]["source"]["bbox"] and o["lines"][1]["status"] == "unverified"
