import datetime as dt

import pytest

from pipeline.numbers import parse_date, parse_number, parse_numbers, value_in_quote


@pytest.mark.parametrize("text,value,kind", [
    ("Asking price: AED 48.5m", 48_500_000, "money"),
    ("AED 48,500,000", 48_500_000, "money"),
    ("AED 3.2 million", 3_200_000, "money"),
    ("AED 48.5 mn", 48_500_000, "money"),
    ("Dhs 850k", 850_000, "money"),
    ("AED 1.2bn", 1_200_000_000, "money"),
    ("gross yield of 8.65%", 0.0865, "pct"),
    ("8.65 per cent", 0.0865, "pct"),
    ("NSA 4,830 sq m", 4830, "sqm"),
    ("4830 m²", 4830, "sqm"),
    ("52,000 sq ft BUA", 52000, "sqft"),
    ("52,000 sq.ft", 52000, "sqft"),
    ("(12,500)", -12500, "plain"),
    ("120 units", 120, "plain"),
])
def test_parse_numbers(text, value, kind):
    n = parse_numbers(text)[0]
    assert n.value == pytest.approx(value)
    assert n.kind == kind


def test_labels_glued_to_letters_are_not_numbers():
    assert parse_numbers("G+4 building, 1BR and 2BR, T12") == []


@pytest.mark.parametrize("cell,expected", [
    (12500, 12500), ("12,500", 12500), ("AED 12,500", 12500), ("(1,200)", -1200), ("5%", 0.05),
    ("-", None), ("n/a", None), (None, None), ("", None), ("1 BR 700", None), (True, None),
])
def test_parse_number_cells(cell, expected):
    assert parse_number(cell) == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("value,quote,unit,ok", [
    (48_500_000, "Guide price AED 48.5m", "AED", True),
    (48_520_000, "Guide price AED 48.5m", "AED", False),
    (0.0865, "Gross ROI 8.65%", "ratio", True),
    (0.0856, "Gross ROI 8.65%", "ratio", False),
    (4830 * 10.7639, "NSA 4,830 sq m", "sqft", True),
    (4830, "NSA 4,830 sq m", "sqm", True),
    (112, "Units 112 units", None, True),
    (113, "Units 112 units", None, False),
])
def test_value_in_quote(value, quote, unit, ok):
    assert value_in_quote(value, quote, unit)[0] is ok


@pytest.mark.parametrize("text,day_first,expected", [
    ("2026-10-31", True, dt.date(2026, 10, 31)),
    ("31/10/2026", True, dt.date(2026, 10, 31)),
    ("10/31/2026", False, dt.date(2026, 10, 31)),
    ("31-Oct-2026", True, dt.date(2026, 10, 31)),
    ("31 October 2026", True, dt.date(2026, 10, 31)),
    ("Oct 31, 2026", True, dt.date(2026, 10, 31)),
    (46326, True, dt.date(2026, 10, 31)),
    ("31/02/2026", True, None),
    ("-", True, None),
])
def test_parse_date(text, day_first, expected):
    assert parse_date(text, day_first) == expected
