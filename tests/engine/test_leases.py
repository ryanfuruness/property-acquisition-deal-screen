"""Single-unit lease cases, hand calculated.

Market rent is a flat AED 100,000 a year (8,333.33 a month) unless stated, and the
lease expires at month 6 (a lease ending 30 June 2027 in a January 2027 analysis).
"""

import pytest

from engine.leases import LeaseAssumptions, UnitLease, model_unit, rera_max_increase, renewal_rent

BANDS = ((0.10, 0.00), (0.20, 0.05), (0.30, 0.10), (0.40, 0.15), (1.00, 0.20))
MARKET = [100_000.0] * 6


def assumptions(p=1.0, downtime=1.5, fee=0.5, notice_months=90 / (365 / 12)):
    return LeaseAssumptions(renewal_probability=p, downtime_months=downtime, leasing_fee_months=fee,
                            rera_bands=BANDS, notice_months=notice_months, months=72)


def unit(rent=85_000.0, expiry=6, status="occupied"):
    return UnitLease(unit="A1", unit_type="1br", area_sqft=1000, status=status,
                     annual_rent_aed=rent, expiry_month=expiry)


def year(schedule_list, y):
    return sum(schedule_list[12 * y: 12 * y + 12])


class TestReraBands:
    @pytest.mark.parametrize("current, expected_rent, rule", [
        (95_000, 95_000, "rera_band_0pct"),       # 5% below the index: no increase
        (90_000, 90_000, "rera_band_0pct"),       # exactly 10% below: still the first band
        (85_000, 89_250, "rera_band_5pct"),       # 15% below: +5%
        (80_000, 84_000, "rera_band_5pct"),       # exactly 20% below: +5%
        (75_000, 82_500, "rera_band_10pct"),      # 25% below: +10%
        (65_000, 74_750, "rera_band_15pct"),      # 35% below: +15%
        (50_000, 60_000, "rera_band_20pct"),      # 50% below: +20%
    ])
    def test_under_rented_band(self, current, expected_rent, rule):
        rent, got_rule = renewal_rent(current, 100_000, BANDS)
        assert rent == pytest.approx(expected_rent)
        assert got_rule == rule

    def test_over_rented_resets_to_market(self):
        assert renewal_rent(120_000, 100_000, BANDS) == (100_000, "over_rented_reset_to_reference")

    def test_increase_never_exceeds_market(self):
        # 99,000 is 1% below: 0%. A hypothetical generous band still caps at market.
        assert rera_max_increase(99_000, 100_000, BANDS) == 0.0
        rent, _ = renewal_rent(95_000, 100_000, ((1.0, 0.50),))
        assert rent == 100_000


class TestSingleUnitRenewal:
    @pytest.mark.parametrize("current, renewed", [
        (95_000, 95_000), (85_000, 89_250), (75_000, 82_500), (65_000, 74_750), (50_000, 60_000),
    ])
    def test_year_one_prorated_by_month(self, current, renewed):
        s = model_unit(unit(current), MARKET, assumptions(p=1.0))
        # Six months at the old rent, six at the renewed rent.
        assert year(s.rent, 0) == pytest.approx(current / 2 + renewed / 2)
        assert sum(s.leasing_fees) == 0.0

    def test_second_renewal_retests_against_index(self):
        s = model_unit(unit(85_000), MARKET, assumptions(p=1.0))
        # 89,250 is 10.75% below the index at the next renewal: +5% again to 93,712.50.
        assert year(s.rent, 1) == pytest.approx(89_250 / 2 + 93_712.5 / 2)
        assert s.events[1]["renewal_rule"] == "rera_band_5pct"

    def test_over_rented_unit_resets_at_renewal(self):
        s = model_unit(unit(120_000), MARKET, assumptions(p=1.0))
        assert year(s.rent, 0) == pytest.approx(60_000 + 50_000)
        assert year(s.rent, 1) == pytest.approx(100_000)
        assert s.events[0]["renewal_rule"] == "over_rented_reset_to_reference"

    def test_no_increase_inside_notice_window(self):
        # Expires at month 1 (31 Jan 2027): too soon to serve 90 days' notice.
        s = model_unit(unit(85_000, expiry=1), MARKET, assumptions(p=1.0))
        assert s.events[0]["renewal_rule"] == "notice_window_no_increase"
        assert s.events[0]["renewal_rent"] == 85_000
        # Month 3 is outside the 2.96-month window, so the band applies.
        s3 = model_unit(unit(85_000, expiry=3), MARKET, assumptions(p=1.0))
        assert s3.events[0]["renewal_rent"] == pytest.approx(89_250)

    def test_growth_path_sets_market_at_expiry(self):
        # Market falls 4% to 96,000 in year 1: a 95,000 rent is now 1.04% below, no change;
        # a 100,000 rent is over-rented and resets to 96,000.
        falling = [96_000.0] * 6
        s = model_unit(unit(100_000), falling, assumptions(p=1.0))
        assert s.events[0]["renewal_rent"] == pytest.approx(96_000)


class TestTurnover:
    def test_turnover_with_downtime_and_fee(self):
        # p = 0: tenant leaves at month 6. Unit is empty for 1.5 months, then re-lets at
        # 100,000. Year 1 = 6 x 7,500 + (6 - 1.5) x 8,333.33 = 45,000 + 37,500 = 82,500.
        s = model_unit(unit(90_000), MARKET, assumptions(p=0.0))
        assert year(s.rent, 0) == pytest.approx(82_500)
        assert s.rent[6] == 0.0
        assert s.rent[7] == pytest.approx(100_000 / 12 / 2)
        # Leasing fee: half a month of the new rent, in the month of re-letting (month 7).
        assert s.leasing_fees[7] == pytest.approx(100_000 / 12 * 0.5)
        assert sum(s.leasing_fees[:12]) == pytest.approx(4_166.6667, abs=1e-3)
        # Potential rent ignores the downtime.
        assert year(s.potential_rent, 0) == pytest.approx(45_000 + 50_000)

    def test_expected_value_blend(self):
        # p = 0.7, current 85,000. Renewal 89,250. Turnover 100,000 with 1.5 months lost.
        s = model_unit(unit(85_000), MARKET, assumptions(p=0.7))
        expected = 42_500 + 0.7 * 44_625 + 0.3 * (50_000 - 12_500)
        assert year(s.rent, 0) == pytest.approx(expected)          # 84,987.50
        assert sum(s.leasing_fees[:12]) == pytest.approx(0.3 * 4_166.6667, abs=1e-3)
        assert s.events[0]["expected_rent_after"] == pytest.approx(0.7 * 89_250 + 0.3 * 100_000)

    def test_rera_band_applies_to_each_tenants_own_rent_not_a_blend(self):
        # After the first expiry: 70% chance the tenant renewed at 89,250, 30% a new tenant at
        # 100,000. At the second expiry the renewed tenant (10.75% below) gets +5% to 93,712.50
        # and the new tenant (at the reference) stays at 100,000. A blended 92,475 would have
        # been 7.5% below and got no increase.
        s = model_unit(unit(85_000), MARKET, assumptions(p=0.7))
        second = s.events[1]
        rules = {round(t["current_rent"]): t["renewal_rule"] for t in second["tenant_states"]}
        assert rules == {89_250: "rera_band_5pct", 100_000: "at_reference"}
        first_half = 0.5 * (0.7 * 89_250 + 0.3 * 100_000)
        renewals = 0.5 * (0.49 * 93_712.5 + 0.21 * 100_000)
        turnover = 0.3 * 100_000 / 12 * (6 - 1.5)
        assert year(s.rent, 1) == pytest.approx(first_half + renewals + turnover)       # 90,947.06
        assert year(s.rent, 1) == pytest.approx(90_947.0625)

    def test_turnover_relets_at_reference_uncapped(self):
        # A tenant 50% below the reference may only get +20% on renewal; a re-let is at the reference.
        s = model_unit(unit(50_000), MARKET, assumptions(p=0.0))
        assert s.events[0]["turnover_rent"] == 100_000
        assert year(s.rent, 1) == pytest.approx(100_000 / 2 + 100_000 / 12 * (6 - 1.5))

    def test_notice_served_turns_over(self):
        s = model_unit(unit(90_000, status="notice_served"), MARKET, assumptions(p=0.7))
        assert s.events[0]["renewal_probability"] == 0.0
        assert year(s.rent, 0) == pytest.approx(82_500)

    def test_legal_case_unit_relets_after_resolution_period(self):
        legal = UnitLease(unit="L1", unit_type="1br", area_sqft=1000, status="legal_case", annual_rent_aed=90_000,
                          expiry_month=None, lease_up_downtime=6.0)
        s = model_unit(legal, MARKET, assumptions(p=0.7))
        assert sum(s.rent[:6]) == 0.0
        assert year(s.rent, 0) == pytest.approx(100_000 / 2)
        assert s.leasing_fees[6] == pytest.approx(100_000 / 12 * 0.5)

    def test_vacant_unit_leases_up_after_downtime(self):
        s = model_unit(unit(None, expiry=None, status="vacant"), MARKET, assumptions(p=0.7))
        assert year(s.rent, 0) == pytest.approx(100_000 - 12_500)
        assert s.leasing_fees[1] == pytest.approx(100_000 / 12 * 0.5)
        assert s.events[0]["type"] == "lease_up"
        # The new lease then rolls 12 months later like any other.
        assert s.events[1]["month"] == 12
