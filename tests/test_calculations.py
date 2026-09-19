"""Tests for exact price and future optimisation calculations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.dutch_energy_prices.calculations import (
    calculate_period,
    calculate_periods,
    cheapest_window,
    effective_battery_cost,
    grid_arbitrage_profit,
    solar_storage_value,
)
from custom_components.dutch_energy_prices.models import MarketPricePeriod, PriceSettings


def raw_period(price: str = "0.0632", minute: int = 0) -> MarketPricePeriod:
    start = datetime(2027, 1, 10, 12, tzinfo=UTC) + timedelta(minutes=minute)
    return MarketPricePeriod(start, start + timedelta(minutes=15), Decimal(price))


def settings(**overrides) -> PriceSettings:
    values = {
        "vat_percentage": Decimal("21"),
        "energy_tax": Decimal("0.09161"),
        "supplier_import_markup": Decimal("0.01"),
        "supplier_export_adjustment": Decimal("-0.005"),
        "battery_round_trip_efficiency": Decimal("0.85"),
    }
    values.update(overrides)
    return PriceSettings(**values)


def test_default_import_and_export_calculation() -> None:
    period = calculate_period(raw_period(), settings())

    assert period.import_price == Decimal("0.1994201")
    assert period.export_price == Decimal("0.0582")
    assert period.import_vat == Decimal("0.0346101")
    assert period.export_vat == Decimal("0")


def test_vat_applicability_is_component_specific() -> None:
    period = calculate_period(
        raw_period(),
        settings(
            vat_market_import=False,
            vat_import_markup=True,
            vat_energy_tax=False,
            vat_market_export=True,
            vat_export_adjustment=True,
        ),
    )

    assert period.import_price == Decimal("0.16691")
    assert period.export_price == Decimal("0.070422")
    assert period.import_vat == Decimal("0.0021")
    assert period.export_vat == Decimal("0.012222")


def test_decimal_avoids_binary_float_rounding() -> None:
    period = calculate_period(raw_period("0.1"), settings(energy_tax=Decimal("0.2")))

    assert period.import_price == Decimal("0.3751")


def test_rejects_non_quarter_hour_period() -> None:
    start = datetime(2027, 1, 10, tzinfo=UTC)

    with pytest.raises(ValueError, match="exactly 15 minutes"):
        MarketPricePeriod(start, start + timedelta(hours=1), Decimal("0.1"))


def test_rejects_naive_datetimes() -> None:
    start = datetime(2027, 1, 10)

    with pytest.raises(ValueError, match="timezone-aware"):
        MarketPricePeriod(start, start + timedelta(minutes=15), Decimal("0.1"))


def test_cheapest_window_uses_contiguous_quarter_hours() -> None:
    prices = ["0.30", "0.10", "0.11", "0.09", "0.12", "0.40"]
    periods = tuple(
        calculate_period(
            raw_period(price, index * 15),
            settings(
                vat_percentage=Decimal("0"),
                energy_tax=Decimal("0"),
                supplier_import_markup=Decimal("0"),
            ),
        )
        for index, price in enumerate(prices)
    )

    window = cheapest_window(periods, 4)

    assert window is not None
    assert window.start == periods[1].start
    assert window.end == periods[4].end
    assert window.average_import_price == Decimal("0.105")


def test_cheapest_window_does_not_cross_data_gap() -> None:
    first = calculate_period(raw_period("0.01", 0), settings())
    last = calculate_period(raw_period("0.01", 30), settings())

    assert cheapest_window((first, last), 2) is None


def test_rejects_overlapping_periods() -> None:
    first = raw_period("0.1", 0)
    duplicate = raw_period("0.2", 0)

    with pytest.raises(ValueError, match="must not overlap"):
        calculate_periods((first, duplicate), settings())


def test_cheapest_window_prefers_earliest_equal_window() -> None:
    periods = tuple(
        calculate_period(raw_period("0.1", index * 15), settings()) for index in range(3)
    )

    window = cheapest_window(periods, 1)

    assert window is not None
    assert window.start == periods[0].start


def test_battery_economics_are_ready_for_v02() -> None:
    efficiency = Decimal("0.8")

    assert effective_battery_cost(Decimal("0.16"), efficiency) == Decimal("0.2")
    assert grid_arbitrage_profit(Decimal("0.16"), Decimal("0.30"), efficiency) == Decimal("0.10")
    assert solar_storage_value(Decimal("0.05"), Decimal("0.30"), efficiency) == Decimal("0.190")


@pytest.mark.parametrize("efficiency", [Decimal("0"), Decimal("-0.1"), Decimal("1.01")])
def test_invalid_battery_efficiency(efficiency: Decimal) -> None:
    with pytest.raises(ValueError):
        effective_battery_cost(Decimal("0.1"), efficiency)
