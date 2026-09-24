"""Tests for the full-horizon native 15-minute optimiser."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from custom_components.dutch_energy_prices.models import (
    BatteryBank,
    BatterySnapshot,
    EnergyForecastPeriod,
    PricePeriod,
    PriceSettings,
)
from custom_components.dutch_energy_prices.optimizer import optimize_energy_plan

START = datetime(2027, 6, 1, tzinfo=UTC)


def price_periods(imports: list[str], exports: list[str] | None = None) -> tuple[PricePeriod, ...]:
    exports = exports or imports
    return tuple(
        PricePeriod(
            START + timedelta(minutes=15 * index),
            START + timedelta(minutes=15 * (index + 1)),
            Decimal(import_price),
            Decimal(import_price),
            Decimal(exports[index]),
        )
        for index, import_price in enumerate(imports)
    )


def settings(**overrides) -> PriceSettings:
    values = dict(
        vat_percentage=Decimal("21"),
        energy_tax=Decimal("0"),
        supplier_import_markup=Decimal("0"),
        supplier_export_adjustment=Decimal("0"),
        battery_round_trip_efficiency=Decimal("0.85"),
        battery_charge_efficiency=Decimal("0.90"),
        battery_operating_cost=Decimal("0"),
        minimum_profit=Decimal("0.001"),
        battery_min_reserve_percent=Decimal("0"),
        battery_reserve_buffer_kwh=Decimal("0"),
        battery_target_energy_kwh=Decimal("2"),
        max_charge_power_kw=Decimal("2"),
        max_discharge_power_kw=Decimal("2"),
    )
    values.update(overrides)
    return PriceSettings(**values)


def battery(stored: str = "0", capacity: str = "10") -> BatterySnapshot:
    return BatterySnapshot((BatteryBank("Combined", Decimal(capacity), Decimal(stored)),))


def load_forecast(values: list[str], solar: list[str] | None = None):
    solar = solar or ["0"] * len(values)
    return tuple(
        EnergyForecastPeriod(
            START + timedelta(minutes=15 * index),
            START + timedelta(minutes=15 * (index + 1)),
            Decimal(solar[index]),
            Decimal(load),
        )
        for index, load in enumerate(values)
    )


def test_scans_non_contiguous_cheap_slots_and_costs_each_allocation() -> None:
    periods = price_periods(["0.10", "0.40", "0.11", "0.50"])
    plan = optimize_energy_plan(
        periods,
        battery(),
        settings(),
        now=START,
        forecasts=load_forecast(["0", "0.5", "0", "0.5"]),
    )

    charge_starts = [slot.start for slot in plan.slots if slot.grid_charge_kwh > 0]
    assert charge_starts == [periods[0].start, periods[2].start]
    assert plan.charge_cost_eur == sum(
        slot.grid_charge_kwh * periods[index].import_price for index, slot in enumerate(plan.slots)
    )
    assert plan.net_value_eur > 0


def test_current_partial_slot_respects_remaining_duration() -> None:
    periods = price_periods(["-0.10", "0.50"])
    plan = optimize_energy_plan(
        periods,
        battery(),
        settings(),
        now=START + timedelta(minutes=10),
        forecasts=load_forecast(["0", "1"]),
    )

    assert plan.slots[0].grid_charge_kwh <= Decimal("2") / Decimal("12")


def test_negative_export_price_makes_solar_storage_more_valuable() -> None:
    periods = price_periods(["0.20", "0.40"], ["-0.05", "0.10"])
    plan = optimize_energy_plan(
        periods,
        battery(),
        settings(solar_confidence_percent=Decimal("100")),
        now=START,
        forecasts=load_forecast(["0", "0.5"], solar=["0.5", "0"]),
    )

    assert plan.solar_charge_kwh > 0
    assert plan.self_discharge_kwh > 0
    assert plan.net_value_eur > 0


def test_negative_all_in_import_charges_even_without_a_visible_discharge_sink() -> None:
    periods = price_periods(["-0.10", "0.20"])
    plan = optimize_energy_plan(
        periods,
        battery(),
        settings(),
        now=START,
        forecasts=load_forecast(["0", "0"]),
    )

    assert plan.grid_charge_kwh > 0
    assert plan.charge_cost_eur < 0
    assert plan.net_value_eur > 0


def test_grid_export_uses_export_tariff_only_when_enabled() -> None:
    periods = price_periods(["0.10", "0.10"], ["0.01", "0.50"])
    forecast = load_forecast(["0", "0"])
    disabled = optimize_energy_plan(
        periods, battery(), settings(allow_grid_export=False), now=START, forecasts=forecast
    )
    enabled = optimize_energy_plan(
        periods, battery(), settings(allow_grid_export=True), now=START, forecasts=forecast
    )

    assert disabled.export_discharge_kwh == 0
    assert enabled.export_discharge_kwh > 0
    assert enabled.export_revenue_eur > 0


def test_existing_energy_preserves_forecast_bridge_reserve() -> None:
    periods = price_periods(["0.50", "0.40", "0.10"])
    forecast = load_forecast(["0.5", "0.5", "0"], solar=["0", "0", "1"])
    plan = optimize_energy_plan(
        periods,
        battery(stored="4"),
        settings(solar_confidence_percent=Decimal("100")),
        now=START,
        forecasts=forecast,
    )

    expected_bridge = Decimal("1") / settings().resolved_discharge_efficiency
    assert plan.reserve_kwh == expected_bridge
    assert plan.self_discharge_kwh <= (Decimal("4") - expected_bridge) * Decimal(
        str(settings().resolved_discharge_efficiency)
    )


def test_early_discharge_frees_capacity_for_a_later_charge_cycle() -> None:
    periods = price_periods(["0.80", "0.10", "0.60"])
    plan = optimize_energy_plan(
        periods,
        battery(stored="10", capacity="10"),
        settings(battery_min_reserve_percent=Decimal("90")),
        now=START,
        forecasts=load_forecast(["0.5", "0", "0.5"]),
    )

    assert plan.slots[0].self_discharge_kwh > 0
    assert plan.slots[1].grid_charge_kwh > 0
    assert plan.slots[2].self_discharge_kwh > 0


def test_reserve_covers_night_before_solar_forecast_begins() -> None:
    periods = price_periods(["0.30"] * 4)
    daylight_only = (
        EnergyForecastPeriod(periods[3].start, periods[3].end, Decimal("1"), Decimal("0")),
    )
    plan = optimize_energy_plan(
        periods,
        battery(stored="5"),
        settings(solar_confidence_percent=Decimal("100")),
        now=START,
        forecasts=daylight_only,
        fallback_load_kw=Decimal("1"),
    )

    expected = Decimal("0.75") / settings().resolved_discharge_efficiency
    assert plan.reserve_kwh == expected
