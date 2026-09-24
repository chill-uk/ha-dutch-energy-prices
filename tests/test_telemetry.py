"""Tests for unit-safe multi-bank telemetry normalisation."""

from decimal import Decimal

from custom_components.dutch_energy_prices.telemetry import (
    Measurement,
    build_battery_snapshot,
    energy_kwh,
    power_kw,
)


def test_units_are_normalised_without_float_rounding() -> None:
    assert energy_kwh(Measurement("5024", "Wh")) == Decimal("5.024")
    assert power_kw(Measurement("2400", "W")) == Decimal("2.4")


def test_multiple_banks_use_capacity_soh_and_soc_positionally() -> None:
    snapshot = build_battery_snapshot(
        (Measurement("50", "%", "STREAM"), Measurement("20", "%", "AC5000")),
        configured_capacity_kwh=Decimal("17"),
        capacities=(Measurement("12", "kWh"), Measurement("5", "kWh")),
        state_of_health=(Measurement("99", "%"), Measurement("80", "%")),
    )

    assert snapshot is not None
    assert snapshot.capacity_kwh == Decimal("15.88")
    assert snapshot.stored_energy_kwh == Decimal("6.74")
    assert len(snapshot.banks) == 2


def test_stored_energy_takes_priority_over_soc() -> None:
    snapshot = build_battery_snapshot(
        (Measurement("10", "%"),),
        configured_capacity_kwh=Decimal("10"),
        stored_energy=(Measurement("4.2", "kWh"),),
    )

    assert snapshot is not None
    assert snapshot.stored_energy_kwh == Decimal("4.2")
    assert snapshot.banks[0].capacity_source == "stored_energy_entity"
