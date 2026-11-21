"""End to end with a stub model on a small synthetic package; no API calls."""

import builtins
import json
import pathlib

import pytest

from helpers import StubClient, make_pdf, make_xlsx
from pipeline.config import RunSettings
from pipeline.llm import BudgetExceeded, Ledger
from pipeline.run import list_deals, run_deal

OM_LINES = ["Palm Court Residences - Offering Memorandum", "Location: Jumeirah Village Circle, Dubai",
            "Title: Freehold, single title deed", "Asking price AED 30,000,000", "Total units 40",
            "Occupancy 99% as at October 2026", "Gross ROI 9.6%", "Chiller: tenants pay Empower directly",
            "Direct leases registered with Ejari", "Completed 2015"]


def raw(value, quote, page=1, **kw):
    return {"value": value, "unit": kw.pop("unit", None), "as_of": None, "source": {"doc": "om.pdf", "page": page},
            "quote": quote, "null_reason": None, **kw}


def none():
    return {"value": None, "unit": None, "as_of": None, "source": None, "quote": None, "null_reason": "not stated"}


EXTRACT = {
    "building_name": raw("Palm Court Residences", "Palm Court Residences"),
    "asset_type": none(), "area": raw("Jumeirah Village Circle, Dubai", "Location: Jumeirah Village Circle, Dubai"),
    "market_area": raw("JVC", "Location: Jumeirah Village Circle, Dubai"), "plot_number": none(),
    "title_type": raw({"tenure": "freehold", "ownership": "single_title"}, "Title: Freehold, single title deed"),
    "completion_year": raw(2015, "Completed 2015"), "floors": none(), "unit_count": raw(40, "Total units 40"),
    "unit_mix": none(), "bua_sqft": none(), "nsa_sqft": none(), "parking_spaces": none(),
    "occupancy_stated": raw(0.99, "Occupancy 99% as at October 2026"),
    "annual_rent_stated": none(), "net_income_stated_aed": none(), "opex_stated_aed": none(),
    "yield_stated": raw(0.096, "Gross ROI 9.6%", basis={"measure": "gross", "on": "unstated"}),
    "asking_price_aed": raw(30_000_000, "Asking price AED 30,000,000", unit="AED"),
    "price_psf_stated": none(),
    "chiller_arrangement": raw("tenant_pays", "Chiller: tenants pay Empower directly"),
    "lease_structure": raw({"type": "direct_leases", "master_tenant": None}, "Direct leases registered with Ejari"),
    "upside_claims": [],
}

LAYOUT = {"tables": [{"sheet": "Rent Roll", "role": "unit_leases", "header_rows": [1], "first_data_row": 2,
                      "last_data_row": 41,
                      "columns": [{"column": "A", "header_text": "Unit", "field": "unit"},
                                  {"column": "B", "header_text": "Type", "field": "unit_type"},
                                  {"column": "C", "header_text": "Area", "field": "area", "unit_of_measure": "sqft"},
                                  {"column": "D", "header_text": "Rent", "field": "annual_rent"},
                                  {"column": "E", "header_text": "End", "field": "lease_end"},
                                  {"column": "F", "header_text": "Ejari", "field": "ejari_no"},
                                  {"column": "G", "header_text": "Status", "field": "status"}],
                      "exclude_rows": []}],
          "date_format": "DMY", "status_vocabulary": [{"text": "Occupied", "status": "occupied"},
                                                      {"text": "Vacant", "status": "vacant"}],
          "unit_type_vocabulary": [{"text": "1 BR", "unit_type": "1br"}], "summary_rows": []}

OPEX_MAP = {"period": {"start": "2025-11-01", "end": "2026-10-31", "months_covered": 12, "presented_as_annual": True,
                       "annualised": False, "evidence": []},
            "amount_basis": "period_total",
            "lines": [{"label": "Rent", "category": "rental_income", "amount_cell": "S!B2", "sign": "income"},
                      {"label": "Maintenance", "category": "maintenance_repairs", "amount_cell": "S!B3", "sign": "expense"}],
            "stated_totals": [], "vat_basis": "unstated"}

REVIEW = {"findings": [{"id": "other_om_claim", "severity": "low", "title": "Invented claim",
                        "evidence": [{"doc": "om.pdf", "page": 1, "quote": "Guaranteed 12% return"}],
                        "why": "w", "analyst_action": "a"}],
          "lease_structure_conclusion": "direct_leases"}

MEMO = {"markdown": "## Verdict\nAsking AED 30m [[deal.asking_price_aed]] for 40 units [[rr.unit_count]]."}


@pytest.fixture
def package(tmp_path):
    pkg = tmp_path / "deals" / "d50-palm" / "package"
    pkg.mkdir(parents=True)
    make_pdf(pkg / "om.pdf", [OM_LINES])
    rows = [["Unit", "Type", "Area", "Rent", "End", "Ejari", "Status"]]
    for i in range(40):
        vacant = i < 4
        rows.append([str(101 + i), "1 BR", 750, None if vacant else 75000, None if vacant else f"28/{1 + i % 12:02d}/2027",
                     None if vacant else f"E{i}", "Vacant" if vacant else "Occupied"])
    make_xlsx(pkg / "Palm Court Rent Roll 31Oct2026.xlsx", {"Rent Roll": rows})
    make_xlsx(pkg / "Palm Court T12 Operating Statement.xlsx", {"S": [["Line", "FY"], ["Rent", 2_600_000],
                                                                      ["Maintenance", 120_000]]})
    (tmp_path / "deals" / "d50-palm" / "truth.json").write_text('{"answer": "do not read"}')
    return tmp_path


def stub():
    return StubClient({"extract_om": json.loads(json.dumps(EXTRACT)), "rent_roll_map": LAYOUT, "opex_map": OPEX_MAP,
                       "review": REVIEW, "memo": [MEMO]})


def test_end_to_end_with_stub(package, monkeypatch):
    opened = []
    real_open, real_read = builtins.open, pathlib.Path.read_bytes

    def spy_open(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    def spy_read(self):
        opened.append(str(self))
        return real_read(self)
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "read_bytes", spy_read)

    settings = RunSettings(deals_dir=package / "deals", runs_dir=package / "runs")
    client = stub()
    run = run_deal("d50-palm", settings, client_factory=lambda ledger, deal: client)

    assert not any(p.endswith("truth.json") for p in opened), "the pipeline opened truth.json"
    out = package / "runs" / "d50-palm"
    assert json.loads((out / "run.json").read_text())["deal"]["deal_id"] == "d50-palm"
    assert (out / "pages" / "om-p1.png").exists()
    assert set(run) >= {"deal", "documents", "extracted", "rent_roll_summary", "opex", "discrepancies",
                        "underwriting", "mandate_fit", "memo", "meta"}
    assert run["extracted"]["om"]["asking_price_aed"]["status"] == "verified"
    assert run["rent_roll_summary"]["summary"]["unit_count"] == 40
    ids = {d["id"] for d in run["discrepancies"]}
    assert "occupancy_mismatch" in ids                     # OM 99% vs roll 90%
    assert "missing_opex_items" in ids                     # statement has only maintenance
    assert run["rejected_model_findings"][0]["title"] == "Invented claim"   # its quote is not on the page
    assert run["underwriting"]["status"] == "ok" and run["underwriting"]["deal_inputs"]["rent_roll_date"] == "2026-10-31"
    assert run["mandate_fit"]["verdict"] in ("Pursue", "Needs work", "Pass")
    assert run["memo"]["status"] == "passed"
    assert [c["stage"] for c in run["meta"]["calls"]] == ["extract_om", "rent_roll_map", "opex_map", "review", "memo_1"]
    # the OM document block is marked for caching and reused by the review
    om_blocks = [r["content"][1] for r in client.requests if r["stage"] in ("extract_om", "review")]
    assert om_blocks[0] == om_blocks[1] and om_blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_budget_refuses_to_start(package):
    ledger = Ledger(package / "runs" / "_ledger.json")
    ledger.data["total_usd"] = 30.0
    settings = RunSettings(deals_dir=package / "deals", runs_dir=package / "runs", budget_usd=25.0)
    with pytest.raises(BudgetExceeded):
        run_deal("d50-palm", settings, client_factory=lambda lg, d: stub(), ledger=ledger)


def test_list_deals_reads_folders_not_index(package):
    (package / "deals" / "index.json").write_text("{}")
    assert list_deals(package / "deals") == ["d50-palm"]
