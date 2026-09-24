"""Normalise Home Assistant battery and power telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .models import BatteryBank, BatterySnapshot


@dataclass(frozen=True, slots=True)
class Measurement:
    """A state value with its Home Assistant unit."""

    value: str
    unit: str | None = None
    name: str | None = None


def energy_kwh(measurement: Measurement | None) -> Decimal | None:
    """Convert a finite Wh/kWh reading to kWh."""
    value = _decimal(measurement)
    if value is None:
        return None
    if measurement is None or measurement.unit == "kWh":
        return value
    if measurement.unit == "Wh":
        return value / Decimal("1000")
    return None


def power_kw(measurement: Measurement | None) -> Decimal | None:
    """Convert a finite W/kW reading to kW."""
    value = _decimal(measurement)
    if value is None:
        return None
    if measurement is None or measurement.unit == "kW":
        return value
    if measurement.unit == "W":
        return value / Decimal("1000")
    return None


def percentage(measurement: Measurement | None) -> Decimal | None:
    """Read a finite percentage and reject implausible values."""
    value = _decimal(measurement)
    if value is None or measurement is None or measurement.unit not in (None, "%"):
        return None
    return value if 0 <= value <= 100 else None


def build_battery_snapshot(
    soc: tuple[Measurement | None, ...],
    *,
    configured_capacity_kwh: Decimal,
    capacities: tuple[Measurement | None, ...] = (),
    stored_energy: tuple[Measurement | None, ...] = (),
    state_of_health: tuple[Measurement | None, ...] = (),
) -> BatterySnapshot | None:
    """Build positional battery banks, preferring live energy measurements."""
    count = max(len(soc), len(capacities), len(stored_energy), len(state_of_health))
    if count == 0:
        return None
    fallback = configured_capacity_kwh / Decimal(count)
    banks: list[BatteryBank] = []
    for index in range(count):
        soh = percentage(_at(state_of_health, index)) or Decimal("100")
        live_capacity = energy_kwh(_at(capacities, index))
        capacity = (live_capacity if live_capacity is not None else fallback) * soh / Decimal("100")
        stored = energy_kwh(_at(stored_energy, index))
        source = (
            "stored_energy_entity"
            if stored is not None
            else ("capacity_entity" if live_capacity is not None else "configured")
        )
        if stored is None:
            bank_soc = percentage(_at(soc, index))
            if bank_soc is None:
                continue
            stored = capacity * bank_soc / Decimal("100")
        stored = min(capacity, max(Decimal("0"), stored))
        reading = _at(soc, index) or _at(stored_energy, index)
        banks.append(
            BatteryBank(
                name=(reading.name if reading and reading.name else f"Battery {index + 1}"),
                capacity_kwh=capacity,
                stored_energy_kwh=stored,
                state_of_health_percent=soh,
                capacity_source=source,
            )
        )
    return BatterySnapshot(tuple(banks)) if banks else None


def _decimal(measurement: Measurement | None) -> Decimal | None:
    if measurement is None:
        return None
    try:
        value = Decimal(measurement.value)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _at(items: tuple[Measurement | None, ...], index: int) -> Measurement | None:
    return items[index] if index < len(items) else None
