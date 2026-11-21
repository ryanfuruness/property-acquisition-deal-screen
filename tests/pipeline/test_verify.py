import pytest

from helpers import make_pdf, raw_field
from pipeline.ingest import Document, Page, Word, ingest_pdf
from pipeline.verify import (NOT_STATED, UNVERIFIED, VERIFIED, VERIFIED_FUZZY, match_quote, verify_evidence,
                             verify_field, verify_upside_claims)


@pytest.fixture
def docs(tmp_path):
    om = make_pdf(tmp_path / "om.pdf", [
        ["Cedarline Residences", "Location: Dubai Silicon Oasis (DSO), Dubai",
         "Guide price AED 48.5m", "Net saleable area (NSA) 4,830 sq m",
         "Title: Freehold, single title deed", "Sold in single ownership"],
        ["Occupancy of 94.6% by units as at October 2026", "Net initial yield of 5.90% after purchaser's costs",
         "Renewals in 2027 will capture 15% reversion across the building"],
    ])
    return [ingest_pdf(om, "om.pdf")]


def test_exact_quote_value_and_boxes(docs):
    f = verify_field("asking_price_aed", raw_field(48_500_000, "Guide price AED 48.5m", unit="AED"), docs)
    assert f["status"] == VERIFIED and f["value"] == 48_500_000
    box = f["source"]["bbox"][0]
    assert len(f["source"]["bbox"]) == 1 and 0 < box[0] < box[2] < 1 and 0 < box[1] < box[3] < 0.3


def test_case_whitespace_and_punctuation_insensitive(docs):
    f = verify_field("asking_price_aed", raw_field(48_500_000, "guide  PRICE: AED 48.5m", unit="AED"), docs)
    assert f["status"] == VERIFIED and f["source"]["match"] == "normalised"


def test_quote_not_on_page_is_unverified(docs):
    f = verify_field("asking_price_aed", raw_field(52_000_000, "Guide price AED 52m", unit="AED"), docs)
    assert f["status"] == UNVERIFIED and "not found" in f["reason"]


def test_value_must_parse_from_quote(docs):
    f = verify_field("asking_price_aed", raw_field(45_800_000, "Guide price AED 48.5m", unit="AED"), docs)
    assert f["status"] == UNVERIFIED and "not found among" in f["reason"]


def test_wrong_page_is_corrected_and_reported(docs):
    f = verify_field("occupancy_stated", raw_field(0.946, "Occupancy of 94.6% by units", page=1), docs)
    assert f["status"] == VERIFIED and f["source"]["page"] == 2 and "page 2" in f["reason"]


def test_percent_given_as_number_is_normalised(docs):
    f = verify_field("occupancy_stated", raw_field(94.6, "Occupancy of 94.6% by units", page=2), docs)
    assert f["status"] == VERIFIED and f["value"] == pytest.approx(0.946)


def test_square_metres_converted_and_original_kept(docs):
    f = verify_field("nsa_sqft", raw_field(4830, "Net saleable area (NSA) 4,830 sq m", unit="sqm"), docs)
    assert f["status"] == VERIFIED
    assert f["value"] == pytest.approx(4830 * 10.7639, abs=0.1) and f["stated"] == {"value": 4830, "unit": "sqm"}


def test_model_converted_sqm_is_accepted_within_one_sqft(docs):
    ok = verify_field("nsa_sqft", raw_field(51989, "Net saleable area (NSA) 4,830 sq m", unit="sqft"), docs)
    off = verify_field("nsa_sqft", raw_field(51900, "Net saleable area (NSA) 4,830 sq m", unit="sqft"), docs)
    assert ok["status"] == VERIFIED and off["status"] == UNVERIFIED


def test_ellipsis_parts_must_appear_in_order(docs):
    q = "Cedarline Residences ... Guide price AED 48.5m"
    assert match_quote(q, docs[0].pages[0]).found
    assert not match_quote("Guide price AED 48.5m ... Cedarline Residences", docs[0].pages[0]).found


def test_enum_needs_keyword_evidence(docs):
    good = verify_field("title_type", raw_field({"tenure": "freehold", "ownership": "single_title"},
                                                "Title: Freehold, single title deed"), docs)
    assert good["status"] == VERIFIED
    weak = verify_field("title_type", raw_field({"tenure": "unstated", "ownership": "single_title"},
                                                "Sold in single ownership"), docs)
    assert weak["status"] == UNVERIFIED and "ownership=single_title" in weak["reason"]


def test_market_area_needs_the_name_or_alias(docs):
    ok = verify_field("market_area", raw_field("Dubai Silicon Oasis", "Location: Dubai Silicon Oasis (DSO), Dubai"), docs)
    bad = verify_field("market_area", raw_field("JVC", "Location: Dubai Silicon Oasis (DSO), Dubai"), docs)
    assert ok["status"] == VERIFIED and bad["status"] == UNVERIFIED


def test_null_value_is_not_stated(docs):
    f = verify_field("opex_stated_aed", {"value": None, "source": None, "quote": None,
                                         "null_reason": "not stated in the OM"}, docs)
    assert f["status"] == NOT_STATED and f["reason"] == "not stated in the OM"


def test_unknown_document_is_unverified(docs):
    f = verify_field("asking_price_aed", raw_field(48_500_000, "Guide price AED 48.5m", doc="brochure.pdf"), docs)
    assert f["status"] == UNVERIFIED and "not in the package" in f["reason"]


def test_upside_claim_figure_must_parse(docs):
    claims = verify_upside_claims([
        {"quote": "Renewals in 2027 will capture 15% reversion across the building", "source": {"doc": "om.pdf", "page": 2},
         "claimed_uplift": 0.15},
        {"quote": "Renewals in 2027 will capture 15% reversion across the building", "source": {"doc": "om.pdf", "page": 2},
         "claimed_uplift": 0.20}], docs)
    assert claims[0]["status"] == VERIFIED and claims[1]["status"] == UNVERIFIED


def _ocr_page(words: list[str], alternates: list[list[str]] = ()) -> Page:
    def ws(texts):
        return [Word(t, 0.1 + 0.05 * i, 0.2, 0.14 + 0.05 * i, 0.22, conf=60) for i, t in enumerate(texts)]
    return Page(1, 595, 842, " ".join(words), ws(words), ocr=True, ocr_mean_conf=60,
                ocr_alternates=[ws(a) for a in alternates])


def test_fuzzy_match_on_ocr_page():
    page = _ocr_page("Total saleable area : , 43,901 sq.ft".split())
    m = match_quote("Total saleable area 43,901 sq.ft", page)
    assert m.found and m.method in ("normalised", "fuzzy")
    page = _ocr_page("Tota) saleabie area 43,901 sq.ft".split())
    m = match_quote("Total saleable area 43,901 sq.ft", page)
    assert m.found and m.method == "fuzzy" and m.similarity >= 0.85 and m.bboxes


def test_fuzzy_match_rejects_a_misread_figure_unless_another_pass_agrees():
    page = _ocr_page("Built Up Area $4,200 sq.ft".split())
    m = match_quote("Built Up Area 54,200 sq.ft", page)
    assert not m.found and "54,200" in m.reason
    page = _ocr_page("Built Up Area $4,200 sq.ft".split(), alternates=["Bult Up Area 54,200 sq.ft".split()])
    assert match_quote("Built Up Area 54,200 sq.ft", page).found


def test_fuzzy_is_never_used_on_a_text_layer(docs):
    assert not match_quote("Guide prise AED 48.5m", docs[0].pages[0]).found


def test_fuzzy_status_reported(tmp_path):
    page = _ocr_page("Tota) saleabie area 43,901 sq.ft".split())
    doc = Document("om.pdf", tmp_path / "om.pdf", "pdf", pages=[page])
    f = verify_field("nsa_sqft", raw_field(43901, "Total saleable area 43,901 sq.ft", unit="sqft"), [doc])
    assert f["status"] == VERIFIED_FUZZY and "OCR" in f["reason"] and f["source"]["ocr"]


def test_evidence_on_cells(tmp_path):
    from helpers import make_xlsx
    from pipeline.ingest import ingest_xlsx

    x = ingest_xlsx(make_xlsx(tmp_path / "rr.xlsx", {"Master Lease": [["Tenant", "Silverline Homes Management LLC"],
                                                                         ["Relationship", "Subsidiary of Silverline Group"]]}), "rr.xlsx")
    ev = verify_evidence([{"doc": "rr.xlsx", "cell": "Master Lease!B2", "quote": "Subsidiary of Silverline Group"},
                          {"doc": "rr.xlsx", "cell": "Master Lease!B1", "quote": "Subsidiary of Silverline Group"}], [x])
    assert [e["status"] for e in ev] == [VERIFIED, UNVERIFIED]


def test_quote_lines_match_as_nearby_parts(tmp_path):
    d = ingest_pdf(make_pdf(tmp_path / "t.pdf", [["Occupancy    Units    Parking", "93%    107    142"]]), "t.pdf")
    assert match_quote("Occupancy\n93%", d.pages[0]).found
    assert not match_quote("93%\nOccupancy", d.pages[0]).found        # order matters


def test_page_given_as_text_is_accepted(docs):
    f = verify_field("asking_price_aed", raw_field(48_500_000, "Guide price AED 48.5m", page="1", unit="AED"), docs)
    assert f["status"] == VERIFIED and f["source"]["page"] == 1


def test_al_barsha_sub_areas_are_not_al_barsha_south(tmp_path):
    d = ingest_pdf(make_pdf(tmp_path / "a.pdf", [["Location Al Barsha 1, Dubai", "Location Al Barsha South, Dubai",
                                                   "Location Barsha Heights (TECOM), Al Barsha"]]), "om.pdf")
    bad = verify_field("market_area", raw_field("Al Barsha South", "Location Al Barsha 1, Dubai"), [d])
    heights = verify_field("market_area", raw_field("Al Barsha South", "Location Barsha Heights (TECOM), Al Barsha"), [d])
    ok = verify_field("market_area", raw_field("Al Barsha South", "Location Al Barsha South, Dubai"), [d])
    assert bad["status"] == UNVERIFIED and heights["status"] == UNVERIFIED and ok["status"] == VERIFIED
