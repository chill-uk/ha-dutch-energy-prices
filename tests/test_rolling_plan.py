"""Check rolling battery guidance with prices, telemetry and reserve limits."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.dutch_energy_prices.models import PricePeriod, PriceSettings
from custom_components.dutch_energy_prices.rolling_plan import ActionStabilizer, rolling_decision


def periods(prices: list[str]) -> tuple[PricePeriod, ...]:
    start = datetime(2027, 1, 10, 12, tzinfo=UTC)
    return tuple(
        PricePeriod(
            start + timedelta(minutes=15 * index),
            start + timedelta(minutes=15 * (index + 1)),
            Decimal(price),
            Decimal(price),
            Decimal(price),
        )
        for index, price in enumerate(prices)
    )


def settings(**overrides) -> PriceSettings:
    values = dict(
        vat_percentage=Decimal("21"),
        energy_tax=Decimal("0"),
        supplier_import_markup=Decimal("0"),
        supplier_export_adjustment=Decimal("0"),
    )
    values.update(overrides)
    return PriceSettings(**values)


def test_discharge_is_limited_by_load_and_protected_reserve() -> None:
    prices = periods(["0.40"] + ["0.10"] * 16 + ["0.30"])
    recommendation = rolling_decision(
        prices, prices[0].start, Decimal("80"), Decimal("0.17"), settings()
    )

    assert recommendation is not None
    assert recommendation.action == "discharge"
    assert recommendation.next_charge_start == prices[1].start
    assert recommendation.reserve_kwh == Decimal("3.5925")
    assert recommendation.slot_energy_kwh == Decimal("0.0425")
    assert recommendation.recommended_power_kw == Decimal("0.17")
    assert recommendation.estimated_value_eur > 0


def test_held_energy_covers_baseline_until_next_charge() -> None:
    prices = periods(["0.40"] * 8 + ["0.10"] * 16 + ["0.30"])
    recommendation = rolling_decision(
        prices, prices[0].start, Decimal("20"), Decimal("0.5"), settings()
    )

    assert recommendation is not None
    assert recommendation.reserve_kwh == Decimal("4.55")
    assert recommendation.available_kwh == 0
    assert recommendation.action == "hold"


def test_charge_window_remains_active_across_quarter_hour_boundaries() -> None:
    prices = periods(["0.10"] * 16 + ["0.40"])
    for index in (0, 1, 8):
        recommendation = rolling_decision(
            prices, prices[index].start, Decimal("20"), Decimal("0.5"), settings()
        )
        assert recommendation is not None
        assert recommendation.action == "charge"
        assert recommendation.recommended_power_kw == Decimal("3")
        assert recommendation.slot_energy_kwh == Decimal("0.75")


def test_mid_slot_plan_limits_energy_to_remaining_time() -> None:
    prices = periods(["0.40"] + ["0.10"] * 16 + ["0.30"])
    recommendation = rolling_decision(
        prices, prices[0].start + timedelta(minutes=10), Decimal("80"), Decimal("0.17"), settings()
    )
    assert recommendation is not None
    assert recommendation.action == "discharge"
    assert recommendation.slot_energy_kwh == Decimal("0.17") / Decimal("12")


def test_discharge_cannot_exceed_output_limit_even_under_high_house_load() -> None:
    prices = periods(["0.40"] + ["0.10"] * 16 + ["0.30"])
    recommendation = rolling_decision(
        prices, prices[0].start, Decimal("100"), Decimal("4"), settings()
    )
    assert recommendation is not None
    assert recommendation.action == "discharge"
    assert recommendation.recommended_power_kw == Decimal("2.4")


def test_price_gap_before_cheap_period_makes_recommendation_unavailable() -> None:
    full = periods(["0.40"] * 2 + ["0.10"] * 16)
    missing = (full[0], *full[2:])
    assert (
        rolling_decision(missing, full[0].start, Decimal("80"), Decimal("0.5"), settings()) is None
    )


def test_no_charging_without_future_peak_and_no_discharge_without_household_use() -> None:
    prices = periods(["0.10"] * 16)
    recommendation = rolling_decision(
        prices, prices[0].start, Decimal("20"), Decimal("0"), settings()
    )
    assert recommendation is not None
    assert recommendation.action == "hold"


@pytest.mark.parametrize(
    "soc,load", [(Decimal("101"), Decimal("1")), (Decimal("50"), Decimal("-1"))]
)
def test_invalid_telemetry_is_not_actionable(soc: Decimal, load: Decimal) -> None:
    prices = periods(["0.40"] + ["0.10"] * 16)
    assert rolling_decision(prices, prices[0].start, soc, load, settings()) is None


def test_action_stabilizer_requires_confirmation_and_dwell_time() -> None:
    start = datetime(2027, 1, 10, 12, tzinfo=UTC)
    stabilizer = ActionStabilizer(confirmations=2, minimum_dwell=timedelta(minutes=5))

    assert stabilizer.update("hold", start) == "hold"
    assert stabilizer.update("discharge", start + timedelta(minutes=1)) == "hold"
    assert stabilizer.update("discharge", start + timedelta(minutes=2)) == "hold"
    assert stabilizer.update("discharge", start + timedelta(minutes=5)) == "discharge"
    assert stabilizer.update(None, start + timedelta(minutes=6)) == "discharge"
