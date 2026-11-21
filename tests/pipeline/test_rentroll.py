import pytest

from helpers import make_xlsx
from pipeline.ingest import ingest_xlsx
from pipeline.rentroll import build_rent_roll, roll_date

ROWS = [
    ["Opal Court - Tenancy Schedule as at 31/10/2026"],
    [],
    ["Unit", "Type", "Area (sq m)", "Tenant", "Ejari", "Start", "End", "Rent p.a.", "Status"],
    ["GROUND FLOOR"],
    ["G01", "Shop", 100, "Cafe LLC", "E1", "01/01/2026", "31/12/2026", 150000, "Occupied"],
    ["101", "Studio", 40, "A. Tenant", "E2", "01/03/2026", "28/02/2027", 45000, "occupied "],
    ["102", "1 BHK", 65, None, None, None, None, 60000, "Vacant"],
    ["FIRST FLOOR"],
    ["201", "2BHK", 100, "B. Tenant", None, "01/09/2025", "31/08/2026", 80000, "Occupied"],
    ["202", "1 BHK", 65, "C. Tenant", "E5", "01/06/2026", "31/05/2027", 62000, "RDC case"],
    ["203", "1 BHK", 65, "D. Tenant", "E6", "01/01/2026", "31/12/2026", 61000, "Notice to vacate"],
    ["Total", None, 435, None, None, None, None, 500000, None],
    ["Occupancy", "6 units", "83%"],
]

LAYOUT = {
    "tables": [{"sheet": "RR", "role": "unit_leases", "header_rows": [3], "first_data_row": 4, "last_data_row": 12,
                "columns": [{"column": "A", "header_text": "Unit", "field": "unit"},
                            {"column": "B", "header_text": "Type", "field": "unit_type"},
                            {"column": "C", "header_text": "Area (sq m)", "field": "area", "unit_of_measure": "sqm"},
                            {"column": "D", "header_text": "Tenant", "field": "tenant"},
                            {"column": "E", "header_text": "Ejari", "field": "ejari_no"},
                            {"column": "F", "header_text": "Start", "field": "lease_start"},
                            {"column": "G", "header_text": "End", "field": "lease_end"},
                            {"column": "H", "header_text": "Rent p.a.", "field": "annual_rent", "unit_of_measure": "AED_per_year"},
                            {"column": "I", "header_text": "Status", "field": "status"}],
                "exclude_rows": [{"row": 4, "kind": "section"}, {"row": 8, "kind": "section"}]}],
    "date_format": "DMY",
    "as_of": {"value": "31/10/2026", "cell": "RR!A1"},
    "status_vocabulary": [{"text": "Occupied", "status": "occupied"}, {"text": "Vacant", "status": "vacant"},
                          {"text": "RDC case", "status": "legal_case"}],
    "unit_type_vocabulary": [{"text": "Shop", "unit_type": "retail"}, {"text": "Studio", "unit_type": "studio"},
                             {"text": "1 BHK", "unit_type": "1br"}, {"text": "2BHK", "unit_type": "2br"}],
    "summary_rows": [{"sheet": "RR", "row": 12, "label": "Total",
                      "cells": [{"cell": "C12", "measure": "area"}, {"cell": "H12", "measure": "annual_rent"}]}],
}


@pytest.fixture
def rr(tmp_path):
    doc = ingest_xlsx(make_xlsx(tmp_path / "roll.xlsx", {"RR": ROWS}), "roll.xlsx")
    return build_rent_roll(doc, LAYOUT)


def test_every_unit_row_parsed_and_non_units_skipped(rr):
    assert [u["unit"] for u in rr["units"]] == ["G01", "101", "102", "201", "202", "203"]
    reasons = [s["reason"] for s in rr["skipped_rows"]]
    assert reasons.count("excluded by layout (section)") == 2
    assert any("total row" in r for r in reasons), "the Total row is dropped by code even if the layout missed it"


def test_units_normalised_with_cell_addresses(rr):
    u = {x["unit"]: x for x in rr["units"]}
    assert u["101"]["area_sqft"] == pytest.approx(40 * 10.7639, abs=0.01)
    assert u["101"]["area_original"] == {"value": 40, "unit": "sqm"}
    assert u["101"]["status"] == "occupied"            # "occupied " matched after whitespace normalisation
    assert u["203"]["status"] == "notice_served" and u["203"]["notes"]   # fallback pattern, recorded
    assert u["G01"]["unit_type"] == "retail" and u["202"]["status"] == "legal_case"
    assert u["101"]["lease_end"] == "2027-02-28"
    assert u["101"]["source"]["cells"]["annual_rent"] == "RR!H6" and u["101"]["source"]["range"] == "RR!A6:I6"


def test_vacant_rent_is_asking_not_income(rr):
    v = next(x for x in rr["units"] if x["unit"] == "102")
    assert v["annual_rent_aed"] is None and v["asking_rent_aed"] == 60000


def test_summary(rr):
    s = rr["summary"]
    assert s["as_of"] == "2026-10-31"
    assert s["unit_count"] == 6 and s["let_units"] == 5 and s["vacant_units"] == 1
    assert s["occupancy_by_units"] == pytest.approx(5 / 6, abs=1e-4)
    assert s["in_place_rent_aed"] == 150000 + 45000 + 80000 + 62000 + 61000
    assert s["potential_rent_aed"] == s["in_place_rent_aed"] + 60000
    assert s["legal_case_rent_aed"] == 62000
    assert s["expired_leases_shown_occupied"] == ["201"]
    assert s["let_units_missing_ejari"] == ["201"]
    assert s["by_type"]["1br"]["units"] == 3 and s["by_type"]["1br"]["let"] == 2
    assert s["max_quarter_expiry_share"] == pytest.approx((150000 + 61000) / s["in_place_rent_aed"], abs=1e-4)


def test_stated_totals_read_by_code(rr):
    t = {x["measure"]: x for x in rr["stated_totals"]}
    assert t["annual_rent"]["value"] == 500000 and t["annual_rent"]["cell"] == "RR!H12"


def test_monthly_rent_column_is_annualised(tmp_path):
    rows = [["Unit", "Type", "Area", "Monthly rent", "Status"], ["1", "Studio", 400, 4000, "Occupied"]]
    doc = ingest_xlsx(make_xlsx(tmp_path / "m.xlsx", {"S": rows}), "m.xlsx")
    layout = {"tables": [{"sheet": "S", "role": "unit_leases", "header_rows": [1], "first_data_row": 2, "last_data_row": 2,
                          "columns": [{"column": "A", "header_text": "Unit", "field": "unit"},
                                      {"column": "B", "header_text": "Type", "field": "unit_type"},
                                      {"column": "C", "header_text": "Area", "field": "area", "unit_of_measure": "sqft"},
                                      {"column": "D", "header_text": "Monthly rent", "field": "annual_rent",
                                       "unit_of_measure": "AED_per_month"},
                                      {"column": "E", "header_text": "Status", "field": "status"}],
                          "exclude_rows": []}],
              "date_format": "DMY", "status_vocabulary": [], "unit_type_vocabulary": [], "summary_rows": []}
    rr = build_rent_roll(doc, layout)
    assert rr["units"][0]["annual_rent_aed"] == 48000 and rr["units"][0]["unit_type"] == "studio"


def test_roll_date_from_file_name_month_only(tmp_path):
    doc = ingest_xlsx(make_xlsx(tmp_path / "Jade Court Rent List Oct 26.xlsx", {"S": [["x"]]}), "Jade Court Rent List Oct 26.xlsx")
    d, src = roll_date(doc, {"date_format": "DMY"})
    assert d.isoformat() == "2026-10-31" and "month end" in src["how"]


def test_master_lease_terms_read_from_named_cells(tmp_path):
    doc = ingest_xlsx(make_xlsx(tmp_path / "ml.xlsx", {
        "Master Lease": [["Master lease terms"], ["Tenant", "Op LLC"], ["Annual rent (AED)", 3_000_000],
                         ["Expiry", "30/06/2029"], ["Total", 3_000_000]],
        "Subs": [["Unit", "Type", "Area", "Rent", "Status"], ["101", "Studio", 450, 40000, "Occupied"],
                 ["Total", None, 450, 40000, None]]}), "ml.xlsx")
    layout = {"tables": [
        {"sheet": "Subs", "role": "sub_leases", "header_rows": [1], "first_data_row": 2, "last_data_row": 2,
         "columns": [{"column": "A", "header_text": "Unit", "field": "unit"},
                     {"column": "B", "header_text": "Type", "field": "unit_type"},
                     {"column": "C", "header_text": "Area", "field": "area"},
                     {"column": "D", "header_text": "Rent", "field": "annual_rent"},
                     {"column": "E", "header_text": "Status", "field": "status"}], "exclude_rows": []}],
        "master_lease": {"tenant_cell": "Master Lease!B2", "annual_rent_cell": "Master Lease!B3",
                         "lease_end_cell": "Master Lease!B4"},
        "date_format": "DMY", "status_vocabulary": [], "unit_type_vocabulary": [],
        "summary_rows": [{"sheet": "Master Lease", "row": 5, "label": "Total",
                          "cells": [{"cell": "B5", "measure": "annual_rent"}]}]}
    rr = build_rent_roll(doc, layout)
    ml = rr["master_lease"]
    assert ml["tenant"] == "Op LLC" and ml["annual_rent_aed"] == 3_000_000 and ml["lease_end"] == "2029-06-30"
    assert ml["source"]["cells"]["annual_rent"] == "Master Lease!B3"
    assert [u["unit"] for u in rr["units"]] == ["101"] and rr["units"][0]["table_role"] == "sub_leases"


def test_remarks_give_asking_rent_and_notice(tmp_path):
    rows = [["Unit", "Type", "Area", "Tenant", "Rent", "Status", "Remarks"],
            ["101", "Studio", 400, None, None, "Vacant", "Asking AED 76,500"],
            ["102", "Studio", 400, "A", 45000, "Occupied", "Vacating on expiry"],
            ["103", "Studio", 400, "B", 45000, "Occupied", "renewal to follow"],
            ["104", "Studio", 400, "C", 45000, "Occupied", None]]
    doc = ingest_xlsx(make_xlsx(tmp_path / "r.xlsx", {"S": rows}), "r.xlsx")
    layout = {"tables": [{"sheet": "S", "role": "unit_leases", "header_rows": [1], "first_data_row": 2, "last_data_row": 5,
                          "columns": [{"column": "A", "header_text": "Unit", "field": "unit"},
                                      {"column": "B", "header_text": "Type", "field": "unit_type"},
                                      {"column": "C", "header_text": "Area", "field": "area"},
                                      {"column": "D", "header_text": "Tenant", "field": "tenant"},
                                      {"column": "E", "header_text": "Rent", "field": "annual_rent"},
                                      {"column": "F", "header_text": "Status", "field": "status"},
                                      {"column": "G", "header_text": "Remarks", "field": "ignore"}],
                          "exclude_rows": []}],
              "date_format": "DMY", "status_vocabulary": [{"text": "Occupied", "status": "occupied"},
                                                          {"text": "Vacant", "status": "vacant"}],
              "unit_type_vocabulary": [], "summary_rows": []}
    u = {x["unit"]: x for x in build_rent_roll(doc, layout)["units"]}
    assert u["101"]["asking_rent_aed"] == 76500 and u["101"]["annual_rent_aed"] is None
    assert u["102"]["status"] == "notice_served" and u["103"]["status"] == "under_renewal"
    assert u["103"]["status_stated"] == "occupied"
    assert u["104"]["status"] == "occupied"


def test_roll_date_from_a_dated_line_or_title(tmp_path):
    from helpers import make_pdf
    from pipeline.ingest import ingest_pdf

    pdf = ingest_pdf(make_pdf(tmp_path / "t.pdf", [["Plot No. 373-4471 Tenancy list as on 30/09/2026", "Unit Rent"]]), "t.pdf")
    d, src = roll_date(pdf, {"date_format": "DMY"})
    assert d.isoformat() == "2026-09-30" and src["page"] == 1 and src["how"] == "dated line in the document"
    x = ingest_xlsx(make_xlsx(tmp_path / "v.xlsx", {"S": [["Vireo"], ["Tenancy Schedule - 31/10/2026"], ["Unit", "Rent"]]}), "v.xlsx")
    d, src = roll_date(x, {"date_format": "DMY"})
    assert d.isoformat() == "2026-10-31" and src["cell"] == "S!A2" and src["how"] == "date in the title"
