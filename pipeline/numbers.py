"""Parse the numbers a broker writes ("AED 48.5m", "8.65%", "4,830 sq m", "(12,500)").

Used by the verifier (does the extracted value really come from the quote?), the rent-roll
and statement parsers (cell text to numbers) and the memo checker (numbers in prose).
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass

from .config import SQM_TO_SQFT

_SCALE = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "mm": 1e6, "mil": 1e6, "million": 1e6, "millions": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
}
_CURRENCY = r"(?:AED|Dhs?\.?|Dirhams?)"
_SQFT = r"(?:sq\.?\s*ft\.?|sqft|square\s+feet|square\s+foot|ft²|ft2|sf\b|psf\b)"
_SQM = r"(?:sq\.?\s*m(?:etres|eters|trs?)?\.?(?![a-z])|sqm|square\s+met(?:re|er)s?|m²|m2\b)"

NUMBER_RE = re.compile(
    rf"(?P<neg>[(\-−–]\s*)?"
    rf"(?:(?P<cur>{_CURRENCY})\s*)?"
    rf"(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    rf"(?:\s*(?P<scale>k|thousand|mn|mm|million|millions|mil|m|bn|billion|b)(?![a-z²2]))?"
    rf"(?P<close>\))?"
    rf"(?:\s*(?P<pct>%|per\s*cent|percent|pct\b))?"
    rf"(?:\s*(?P<sqft>{_SQFT})|\s*(?P<sqm>{_SQM}))?"
    rf"(?:\s*(?P<cur2>{_CURRENCY}))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedNumber:
    value: float        # after scale; a percentage is returned as a ratio (8.5% -> 0.085)
    kind: str           # money | pct | sqft | sqm | plain
    raw: str
    start: int
    end: int
    decimals: int       # digits after the decimal point as written (rounding precision)
    scale: float = 1.0  # multiplier applied (1e6 for "m")

    @property
    def sqft(self) -> float:
        return self.value * SQM_TO_SQFT if self.kind == "sqm" else self.value


def parse_numbers(text: str) -> list[ParsedNumber]:
    """All numbers in ``text`` with their unit. Ordinals glued to letters ("1BR", "G+4") are skipped."""
    out: list[ParsedNumber] = []
    for m in NUMBER_RE.finditer(text or ""):
        start = m.start("num")
        before = text[start - 1] if start > 0 else " "
        after_i = m.end("num")
        after = text[after_i] if after_i < len(text) else " "
        if before.isalpha() or (before in "+" and start > 1 and text[start - 2].isalpha()):
            continue  # G+4, T12, Q3
        if after.isalpha() and not (m.group("scale") or m.group("pct") or m.group("sqft") or m.group("sqm")):
            continue  # 1BR, 3rd
        num = m.group("num").replace(",", "")
        value = float(num)
        decimals = len(num.split(".")[1]) if "." in num else 0
        scale = _SCALE[m.group("scale").lower()] if m.group("scale") else 1.0
        value *= scale
        neg = bool(m.group("neg")) and (m.group("neg").strip() in "-−–" or bool(m.group("close")))
        if neg:
            value = -value
        if m.group("pct"):
            kind, value = "pct", value / 100.0
        elif m.group("sqm"):
            kind = "sqm"
        elif m.group("sqft"):
            kind = "sqft"
        elif m.group("cur") or m.group("cur2"):
            kind = "money"
        else:
            kind = "plain"
        out.append(ParsedNumber(value, kind, m.group(0).strip(), m.start(), m.end(), decimals, scale))
    return out


def parse_number(text: object) -> float | None:
    """A single cell or token to a number: '12,500', 'AED 12,500', '(1,200)', '5%' -> 0.05. None if none."""
    if text is None:
        return None
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return None if isinstance(text, float) and math.isnan(text) else float(text)
    s = str(text).strip()
    if not s or s in {"-", "–", "—", "n/a", "N/A", "nil", "Nil"}:
        return None
    nums = parse_numbers(s)
    if len(nums) != 1:
        return None
    return nums[0].value


def close(a: float, b: float, rel: float = 0.005, abs_tol: float = 1e-9) -> bool:
    """Relative comparison for cross-document checks (not for quote verification, which is exact)."""
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


def value_in_quote(value: float, quote: str, unit: str | None = None) -> tuple[bool, str]:
    """Does ``value`` parse from ``quote``? Returns (ok, explanation).

    ``unit`` guides interpretation: ``ratio`` accepts "8.5%" for 0.085; ``sqft`` accepts a sq m
    figure converted at 10.7639; ``AED`` accepts scaled forms ("48.5m").
    """
    nums = parse_numbers(quote)
    if not nums:
        return False, "no number in quote"
    for n in nums:
        # the value must be the printed figure (scaled), not merely within its rounding;
        # only a sq m figure converted to sq ft may be rounded (to within 1 sq ft)
        candidates = [(n.value, 0.0)]
        if unit == "ratio" and n.kind != "pct":
            candidates.append((n.value / 100.0, 0.0))
        if n.kind == "sqm" and unit != "sqm":
            candidates.append((n.value * SQM_TO_SQFT, 1.0))
        for c, tol in candidates:
            if abs(abs(c) - abs(value)) <= tol + 1e-7 * max(1.0, abs(value)):
                how = f"matches {n.raw!r}"
                if n.kind == "sqm" and c != n.value:
                    how += " converted from sq m at 10.7639"
                return True, how
    return False, f"value {value:g} not found among {[n.raw for n in nums][:6]}"


_MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_date(value: object, day_first: bool = True) -> dt.date | None:
    """Rent-roll dates: ISO strings, datetimes, '31/10/2026', '31-Oct-2026', 'Oct 31, 2026', Excel serials."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20000 < value < 80000:  # Excel serial date
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(value))
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        d, mo = (a, b) if day_first else (b, a)
        return _safe_date(y, mo, d)
    m = re.match(r"^(\d{1,2})[\s\-/.]*([A-Za-z]{3,9})[\s\-/.,]*(\d{2,4})$", s)
    if m:
        mo = _MONTHS.get(m.group(2)[:3].lower())
        y = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        return _safe_date(y, mo, int(m.group(1))) if mo else None
    m = re.match(r"^([A-Za-z]{3,9})[\s\-/.]*(\d{1,2}),?[\s\-/.]*(\d{4})$", s)
    if m:
        mo = _MONTHS.get(m.group(1)[:3].lower())
        return _safe_date(int(m.group(3)), mo, int(m.group(2))) if mo else None
    return None


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None
