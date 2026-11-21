"""Small, general financial functions: IRR, NPV, annuities, loan schedules, dates.

Nothing here knows about Dubai or the mandate; those numbers arrive as arguments.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Sequence


def npv(rate: float, cash_flows: Sequence[float]) -> float:
    """Net present value of annual cash flows, the first at t = 0."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cash_flows))


def irr(cash_flows: Sequence[float], tol: float = 1e-12) -> float | None:
    """Internal rate of return of annual cash flows, by bisection.

    Returns ``None`` when the IRR is undefined (the flows do not change sign, or no
    root is bracketed between -99.99% and 1,000,000%). Bisection is used rather than
    Newton's method because it cannot diverge and gives the same answer every run.
    """
    if not (any(cf < 0 for cf in cash_flows) and any(cf > 0 for cf in cash_flows)):
        return None
    lo, hi = -0.9999, 1.0
    f_lo = npv(lo, cash_flows)
    f_hi = npv(hi, cash_flows)
    while f_lo * f_hi > 0:
        hi *= 10.0
        if hi > 1e6:
            return None
        f_hi = npv(hi, cash_flows)
    for _ in range(400):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid, cash_flows)
        if f_mid == 0.0 or (hi - lo) / 2.0 < tol:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def equity_multiple(cash_flows: Sequence[float]) -> float | None:
    """Total money returned divided by total money put in (sum of inflows / outflows)."""
    paid_in = -sum(cf for cf in cash_flows if cf < 0)
    returned = sum(cf for cf in cash_flows if cf > 0)
    if paid_in <= 0:
        return None
    return returned / paid_in


def annuity_payment(principal: float, rate: float, years: int) -> float:
    """Level annual payment, in arrears, that repays ``principal`` over ``years``."""
    if principal == 0:
        return 0.0
    if years <= 0:
        raise ValueError("amortisation years must be positive")
    if rate == 0:
        return principal / years
    return principal * rate / (1.0 - (1.0 + rate) ** -years)


def loan_schedule(principal: float, rate: float, amortisation_years: int,
                  years: int) -> list[dict[str, float]]:
    """Annual schedule of an amortising loan for the first ``years`` years.

    Each row has ``opening_balance``, ``interest``, ``principal``, ``debt_service``
    and ``closing_balance``. Payments are annual, in arrears, at the annuity amount.
    """
    payment = annuity_payment(principal, rate, amortisation_years)
    rows = []
    balance = principal
    for _ in range(years):
        interest = balance * rate
        repaid = min(payment - interest, balance)
        rows.append({
            "opening_balance": balance,
            "interest": interest,
            "principal": repaid,
            "debt_service": interest + repaid,
            "closing_balance": balance - repaid,
        })
        balance -= repaid
    return rows


def add_months(date: dt.date, months: int) -> dt.date:
    """Same day ``months`` later (clamped to month end)."""
    month_index = date.month - 1 + months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [31, 29 if _is_leap(year) else 28, 31, 30, 31, 30,
                     31, 31, 30, 31, 30, 31][month - 1]
    return dt.date(year, month, min(date.day, days_in_month))


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def expiry_month_index(lease_end: dt.date, analysis_start: dt.date) -> int:
    """Month of the analysis in which a lease ending on ``lease_end`` rolls over.

    The day after ``lease_end`` is when the next lease starts. It is rounded to the
    nearest month start: day 1-15 of a month counts from that month, day 16 onwards
    from the next month. A lease that ended before the analysis starts rolls in month 0.
    Month 0 is the month of ``analysis_start``.
    """
    start_next = lease_end + dt.timedelta(days=1)
    index = (start_next.year - analysis_start.year) * 12 + (start_next.month - analysis_start.month)
    if start_next.day > 15:
        index += 1
    return max(index, 0)


def parse_date(value: str | dt.date, field: str) -> dt.date:
    """Parse an ISO ``YYYY-MM-DD`` string (or pass a date through)."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field}: expected an ISO date YYYY-MM-DD, got {value!r}") from exc


def is_finite_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
