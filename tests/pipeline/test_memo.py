import pytest

from helpers import StubClient
from pipeline.memo import build_fact_sheet, check_memo, tokens, write_memo

FACTS = {
    "deal.asking_price_aed": {"value": 83_000_000.0, "unit": "AED", "label": "asking price"},
    "uw.walk_away_price_aed": {"value": 70_060_000, "unit": "AED", "label": "walk-away"},
    "uw.walk_away_discount_to_asking": {"value": 0.15590, "unit": "ratio", "label": "discount"},
    "uw.dscr_year1": {"value": 1.4713, "unit": "x", "label": "DSCR"},
    "uw.levered_irr_pre_tax": {"value": -0.0123, "unit": "ratio", "label": "IRR"},
    "rr.unit_count": {"value": 112, "unit": "units", "label": "units"},
    "rr.as_of": {"value": "2026-10-31", "unit": "date", "label": "roll date"},
    "uw.max_expiry_window": {"value": "2027-01-01 to 2027-03-31", "unit": "text", "label": "window"},
    "assume.exit_yield_expansion_bps": {"value": 25, "unit": "bps", "label": "expansion"},
    "uw.exit_yield": {"value": 0.07, "unit": "ratio", "label": "exit yield"},
    "disc.collections_gap.why": {"value": "Collections are 15.0% below roll; AED 408,750 a year.", "unit": "text",
                                 "label": "why"},
    "deal.completion_year": {"value": 2013, "unit": "year", "label": "year"},
}


@pytest.mark.parametrize("text", [
    "Walk-away AED 70.1m [[uw.walk_away_price_aed]], 15.6% [[uw.walk_away_discount_to_asking]] below asking.",
    "Asking AED 83,000,000 [[deal.asking_price_aed]] and AED 83m [[deal.asking_price_aed]].",
    "DSCR 1.47x [[uw.dscr_year1]]; levered IRR -1.2% [[uw.levered_irr_pre_tax]].",
    "112 units [[rr.unit_count]] at 31 October 2026 [[rr.as_of]], completed 2013 [[deal.completion_year]].",
    "Exit at 7.0% [[uw.exit_yield]] plus 25 bps [[assume.exit_yield_expansion_bps]].",
    "Collections run 15% [[disc.collections_gap.why]] below the roll, AED 408,750 [[disc.collections_gap.why]] a year.",
    "In Year 1 the T-12 shows 1BR and 2BR units in a G+P+7 block.",
    "## 3 Risks\n1. Rent falls.\n2. Exit widens.",
    "Most rent expires from January 2027 [[uw.max_expiry_window]].",
    "Most rent expires in October 2026 [[rr.as_of]].",
])
def test_grounded_text_passes(text):
    assert check_memo(text, FACTS) == []


@pytest.mark.parametrize("text,needle", [
    ("Walk-away AED 70.1m, well below asking.", "no anchor"),
    ("Walk-away AED 71m [[uw.walk_away_price_aed]].", "does not match"),
    ("DSCR 1.48x [[uw.dscr_year1]].", "does not match"),
    ("IRR 0.0123 [[uw.levered_irr_pre_tax]].", "ratio"),
    ("Two numbers 83m and 70m [[uw.walk_away_price_aed]].", "no anchor"),
    ("Price AED 83m [[deal.price]].", "not a fact-sheet key"),
    ("Collections run 12% [[disc.collections_gap.why]] below.", "does not appear"),
    ("Roll dated 30 September 2026 [[rr.as_of]].", "not the date"),
    ("Exit at 7.0% [[uw.exit_yield]] plus 25 [[assume.exit_yield_expansion_bps]] bps, 3 points [[uw.exit_yield]].", "does not match"),
])
def test_ungrounded_text_fails(text, needle):
    errors = check_memo(text, FACTS)
    assert errors and any(needle in e for e in errors), errors


def test_precision_follows_what_is_written():
    assert check_memo("DSCR 1.5x [[uw.dscr_year1]]", FACTS) == []        # 1.4713 rounds to 1.5
    assert check_memo("DSCR 1.47x [[uw.dscr_year1]]", FACTS) == []
    assert check_memo("DSCR 1.4713x [[uw.dscr_year1]]", FACTS) == []


def test_tokens_skip_anchor_contents():
    toks, anchors = tokens("x 5% [[uw.sens.r-5.e+50.levered_irr_pre_tax]]")
    assert [t.raw for t in toks] == ["5%"] and anchors[0][2] == "uw.sens.r-5.e+50.levered_irr_pre_tax"


def test_write_memo_retries_once_then_fails_closed():
    bad = {"markdown": "Walk-away AED 99m [[uw.walk_away_price_aed]]."}
    client = StubClient({"memo": [bad, bad]})
    memo, results = write_memo(client, "m", FACTS)
    assert memo["status"] == "failed" and memo["markdown"] is None and len(results) == 2
    assert "Code found these problems" in client.requests[1]["content"][-1]["text"]


def test_write_memo_passes_after_retry():
    client = StubClient({"memo": [{"markdown": "AED 99m [[uw.walk_away_price_aed]]"},
                                  {"markdown": "AED 70.1m [[uw.walk_away_price_aed]]"}]})
    memo, _ = write_memo(client, "m", FACTS)
    assert memo["status"] == "passed" and memo["markdown"].startswith("AED 70.1m")
    assert [a["attempt"] for a in memo["attempts"]] == [1, 2]


def test_fact_sheet_uses_verified_fields_only():
    om = {"asking_price_aed": {"value": 1e7, "status": "verified", "quote": "q", "source": {"doc": "om.pdf", "page": 1}},
          "occupancy_stated": {"value": 0.99, "status": "unverified", "quote": "q", "source": {"doc": "om.pdf", "page": 2}},
          "upside_claims": []}
    import engine
    facts = build_fact_sheet(om, None, None, None, None, [], engine.load_mandate(), [])
    assert "deal.asking_price_aed" in facts and "om.occupancy_stated" not in facts
    assert facts["deal.asking_price_aed"]["source"]["page"] == 1
    assert "occupancy stated" in facts["screen.unverified_om_fields"]["value"]


def test_percentage_points():
    facts = {"gap": {"value": "A gap of 7.0 points is about 12 units", "unit": "text", "label": "why"},
             "occ": {"value": 0.07, "unit": "ratio", "label": "ratio"}}
    assert check_memo("a gap of 7.0 points [[gap]], i.e. 7 points [[occ]]", facts) == []
    assert check_memo("8 points [[occ]]", facts)


def test_identifiers_in_prose_are_rejected():
    errors = check_memo("It fails min_dscr_year1 and the [[uw.dscr_year1]] anchor is fine: 1.47x [[uw.dscr_year1]].", FACTS)
    assert any("min_dscr_year1" in e for e in errors) and not any("uw.dscr_year1" in e for e in errors)


def test_display_values_pass_the_checker():
    from pipeline.memo import display
    for key, fact in FACTS.items():
        if fact["unit"] == "text":
            continue
        shown = display(fact).replace(" (negative)", "")
        sign = "-" if isinstance(fact["value"], (int, float)) and fact["value"] < 0 else ""
        assert check_memo(f"{sign}{shown} [[{key}]]", FACTS) == [], (key, shown)
    assert display({"value": 0.0612, "unit": "ratio"}) == "6.1%"
    assert display({"value": 0.5494, "unit": "ratio"}) == "55%"
    assert display({"value": 4_502_892, "unit": "AED/yr"}) == "AED 4.5m"
    assert display({"value": -2_896_431, "unit": "AED"}) == "AED 2.9m (negative)"
    assert display({"value": "2026-10-31", "unit": "date"}) == "31 October 2026"


def test_year_spans_and_place_names_are_not_figures():
    assert check_memo("Years 1 to 5 of the hold, JVC District 11, Al Barsha 1, a 12-month statement.", FACTS) == []
    assert check_memo("From 31 October 2026 [[rr.as_of]] to 31 October 2026.", FACTS)   # each date needs its anchor


def test_calendar_references_are_not_figures():
    assert check_memo("Leases renew through 2027 and the OM expects the uplift within 12 months.", FACTS) == []
    assert check_memo("Rent is AED 2027 a month.", FACTS)             # a bare figure still needs its anchor


def test_negative_facts_must_read_negative():
    assert check_memo("Levered, the IRR is 1.2% [[uw.levered_irr_pre_tax]].", FACTS)
    assert check_memo("Levered, the IRR is -1.2% [[uw.levered_irr_pre_tax]].", FACTS) == []
    assert check_memo("Levered, the deal makes a loss of 1.2% [[uw.levered_irr_pre_tax]] a year.", FACTS) == []
