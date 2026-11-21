"""IRR, annuity and loan schedule against hand-calculated values."""

import datetime as dt

import pytest

from engine.costs import acquisition_costs, mandate_acquisition_rates
from engine.finance import (annuity_payment, equity_multiple, expiry_month_index, irr,
                            loan_schedule, npv)


class TestIrr:
    def test_par_bond_is_ten_percent(self):
        # -100, then 10 a year and 100 back: a par bond at a 10% coupon.
        assert irr([-100, 10, 10, 110]) == pytest.approx(0.10, abs=1e-10)

    def test_single_payoff(self):
        # 1000 growing at 10% for 5 years is 1610.51.
        assert irr([-1000, 0, 0, 0, 0, 1610.51]) == pytest.approx(0.10, abs=1e-10)

    def test_annuity(self):
        # -100 then 50 for three years: 50 * a(3, r) = 100 at r = 23.3752%.
        r = irr([-100, 50, 50, 50])
        assert r == pytest.approx(0.2337519, abs=1e-6)
        assert npv(r, [-100, 50, 50, 50]) == pytest.approx(0.0, abs=1e-8)

    def test_negative_irr(self):
        # Get back 90 of 100 after one year: -10%.
        assert irr([-100, 90]) == pytest.approx(-0.10, abs=1e-10)

    def test_undefined_when_no_sign_change(self):
        assert irr([100, 10, 10]) is None
        assert irr([-100, -10]) is None

    def test_equity_multiple(self):
        assert equity_multiple([-100, 10, 10, 110]) == pytest.approx(1.30)


class TestDebt:
    LOAN = 27_500_000.0
    RATE = 0.068           # 3M EIBOR 4.30% + margin 2.50%

    def test_annuity_payment_hand_calculated(self):
        # 1.068^15 = 2.6826794989; payment = L r f / (f - 1) = 2,981,322.745.
        assert annuity_payment(self.LOAN, self.RATE, 15) == pytest.approx(2_981_322.745, abs=0.01)

    def test_schedule_year_one_split_and_full_repayment(self):
        rows = loan_schedule(self.LOAN, self.RATE, 15, 15)
        assert rows[0]["interest"] == pytest.approx(1_870_000.0)          # 27.5m x 6.8%
        assert rows[0]["principal"] == pytest.approx(2_981_322.745 - 1_870_000.0, abs=0.01)
        assert rows[1]["opening_balance"] == pytest.approx(self.LOAN - rows[0]["principal"])
        assert rows[-1]["closing_balance"] == pytest.approx(0.0, abs=1e-4)
        assert all(r["debt_service"] == pytest.approx(rows[0]["debt_service"]) for r in rows)

    def test_zero_rate_is_straight_line(self):
        assert annuity_payment(1500.0, 0.0, 15) == pytest.approx(100.0)


class TestAcquisitionCosts:
    def test_hand_calculated(self, mandate):
        # Price 50m, loan 55% = 27.5m.
        a = acquisition_costs(50_000_000.0, 27_500_000.0, mandate_acquisition_rates(mandate))
        assert a["dld_transfer_fee"] == pytest.approx(2_000_000.0)    # 4%
        assert a["dld_admin"] == 580.0
        assert a["trustee_fee"] == 4200.0
        assert a["broker_fee"] == pytest.approx(1_000_000.0)          # 2%
        assert a["broker_fee_vat"] == pytest.approx(50_000.0)         # 5% of the fee
        assert a["mortgage_registration"] == pytest.approx(68_750.0 + 290.0)   # 0.25% of loan + 290
        assert a["transfer_costs"] == pytest.approx(3_054_780.0)
        assert a["total"] == pytest.approx(3_123_820.0)

    def test_no_mortgage_registration_without_loan(self, mandate):
        a = acquisition_costs(50_000_000.0, 0.0, mandate_acquisition_rates(mandate))
        assert a["mortgage_registration"] == 0.0


class TestExpiryMonth:
    START = dt.date(2027, 1, 1)

    @pytest.mark.parametrize("lease_end, month", [
        ("2027-06-30", 6),     # next lease starts 1 Jul: Jan-Jun at the old rent
        ("2027-06-14", 5),     # next lease starts 15 Jun: rounds to June
        ("2027-06-20", 6),     # next lease starts 21 Jun: rounds to July
        ("2027-12-31", 12),
        ("2026-11-30", 0),     # already expired: rolls at the start
    ])
    def test_rounding(self, lease_end, month):
        assert expiry_month_index(dt.date.fromisoformat(lease_end), self.START) == month
