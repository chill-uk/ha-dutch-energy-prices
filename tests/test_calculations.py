"""Tests for exact price and future optimisation calculations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.dutch_energy_prices.calculations import (
    best_battery_arbitrage,
    best_battery_energy_plan,
    best_solar_storage,
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


def test_best_battery_arbitrage_uses_ordered_contiguous_windows() -> None:
    prices = ["0.10", "0.10", "0.20", "0.20", "0.50", "0.50"]
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

    opportunity = best_battery_arbitrage(periods, 2, Decimal("0.8"))

    assert opportunity is not None
    assert opportunity.charge_window.start == periods[0].start
    assert opportunity.charge_window.end == periods[1].end
    assert opportunity.discharge_window.start == periods[4].start
    assert opportunity.discharge_window.end == periods[5].end
    assert opportunity.effective_charge_cost == Decimal("0.125")
    assert opportunity.profit_per_kwh == Decimal("0.375")


def test_best_battery_arbitrage_reports_negative_best_value() -> None:
    prices = ["0.50", "0.50", "0.10", "0.10"]
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

    opportunity = best_battery_arbitrage(periods, 2, Decimal("0.8"))

    assert opportunity is not None
    assert opportunity.charge_window.start == periods[0].start
    assert opportunity.discharge_window.start == periods[2].start
    assert opportunity.profit_per_kwh == Decimal("-0.525")


def test_best_battery_arbitrage_does_not_cross_data_gap() -> None:
    periods = (
        calculate_period(raw_period("0.10", 0), settings()),
        calculate_period(raw_period("0.10", 15), settings()),
        calculate_period(raw_period("0.50", 45), settings()),
        calculate_period(raw_period("0.50", 60), settings()),
    )

    assert best_battery_arbitrage(periods, 2, Decimal("0.8")) is not None
    assert best_battery_arbitrage(periods, 3, Decimal("0.8")) is None


def test_power_limited_plan_uses_exact_energy_and_ordered_quarter_hours() -> None:
    periods = tuple(
        calculate_period(
            raw_period("0.10" if index < 16 else "0.40", index * 15),
            settings(
                vat_percentage=Decimal("0"),
                energy_tax=Decimal("0"),
                supplier_import_markup=Decimal("0"),
            ),
        )
        for index in range(33)
    )

    plan = best_battery_energy_plan(
        periods, Decimal("10"), Decimal("3"), Decimal("2.4"), Decimal("0.85")
    )

    assert plan is not None
    assert len(plan.charge_slot_kwh) == 16
    assert len(plan.discharge_slot_kwh) == 17
    assert plan.charge_window.end == plan.discharge_window.start
    assert sum(plan.charge_slot_kwh) == plan.grid_energy_kwh == Decimal("10") / Decimal("0.85")
    assert sum(plan.discharge_slot_kwh) == Decimal("10")
    assert max(plan.charge_slot_kwh) <= Decimal("0.75")
    assert max(plan.discharge_slot_kwh) <= Decimal("0.6")
    assert plan.net_value_eur == plan.avoided_import_eur - plan.charge_cost_eur


def test_power_limited_plan_allocates_partial_slot_at_best_price() -> None:
    prices = ["0.10", "0.50", "0.40", "0.30"]
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
    plan = best_battery_energy_plan(
        periods, Decimal("0.75"), Decimal("2"), Decimal("2"), Decimal("1")
    )

    assert plan is not None
    assert plan.charge_slot_kwh == (Decimal("0.5"), Decimal("0.25"))
    assert plan.discharge_slot_kwh == (Decimal("0.5"), Decimal("0.25"))
    assert plan.charge_cost_eur == Decimal("0.175")
    assert plan.avoided_import_eur == Decimal("0.275")
    assert plan.net_value_eur == Decimal("0.100")


def test_power_limited_plan_requires_enough_contiguous_slots() -> None:
    periods = tuple(
        calculate_period(raw_period("0.10", index * 15), settings()) for index in (0, 15, 45, 60)
    )
    assert (
        best_battery_energy_plan(periods, Decimal("1"), Decimal("2"), Decimal("2"), Decimal("1"))
        is None
    )


@pytest.mark.parametrize(
    "target,charge,discharge", [("0", "3", "2.4"), ("10", "0", "2.4"), ("10", "3", "-1")]
)
def test_power_limited_plan_rejects_invalid_limits(
    target: str, charge: str, discharge: str
) -> None:
    with pytest.raises(ValueError, match="positive"):
        best_battery_energy_plan(
            (), Decimal(target), Decimal(charge), Decimal(discharge), Decimal("0.85")
        )


def test_best_solar_storage_compares_current_export_with_later_avoided_import() -> None:
    prices = ["0.05", "0.10", "0.30", "0.30"]
    periods = tuple(
        calculate_period(
            raw_period(price, index * 15),
            settings(
                vat_percentage=Decimal("0"),
                energy_tax=Decimal("0"),
                supplier_import_markup=Decimal("0"),
                supplier_export_adjustment=Decimal("0"),
            ),
        )
        for index, price in enumerate(prices)
    )

    opportunity = best_solar_storage(
        periods,
        2,
        Decimal("0.8"),
        now=periods[0].start + timedelta(minutes=5),
    )

    assert opportunity is not None
    assert opportunity.current_period == periods[0]
    assert opportunity.discharge_window.start == periods[2].start
    assert opportunity.value_per_kwh == Decimal("0.190")


@pytest.mark.parametrize("efficiency", [Decimal("0"), Decimal("-0.1"), Decimal("1.01")])
def test_invalid_battery_efficiency(efficiency: Decimal) -> None:
    with pytest.raises(ValueError):
        effective_battery_cost(Decimal("0.1"), efficiency)
