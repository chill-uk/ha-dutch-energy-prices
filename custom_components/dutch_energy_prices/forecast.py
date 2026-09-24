"""Generic solar-forecast normalisation for Home Assistant entities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import EnergyForecastPeriod

START_KEYS = ("period_start", "start", "datetime", "time", "date")
POWER_KW_KEYS = ("pv_estimate", "power_kw", "kw")
POWER_W_KEYS = ("power", "watts", "value")
ENERGY_KEYS = ("energy_kwh", "energy", "wh_period")


def find_forecast_items(attributes: Mapping[str, Any], configured_attribute: str = "") -> list[Any]:
    """Find a forecast list in a configured or common provider attribute."""
    keys = (
        (configured_attribute,)
        if configured_attribute
        else (
            "detailedForecast",
            "detailedHourly",
            "forecast",
            "data",
        )
    )
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, list):
            return value
    return []


def normalize_solar_forecast(items: Iterable[Any]) -> tuple[EnergyForecastPeriod, ...]:
    """Convert common Solcast/Open-Meteo shapes into 15-minute solar energy."""
    parsed: list[tuple[datetime, Decimal, str]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        start = _datetime_value(raw)
        measurement = _energy_value(raw)
        if start is not None and measurement is not None:
            parsed.append((start, measurement[0], measurement[1]))
    parsed.sort(key=lambda item: item[0])
    result: list[EnergyForecastPeriod] = []
    for index, (start, value, kind) in enumerate(parsed):
        inferred_end = (
            parsed[index + 1][0] if index + 1 < len(parsed) else start + timedelta(minutes=30)
        )
        duration = inferred_end - start
        if duration <= timedelta(0) or duration > timedelta(hours=3):
            duration = timedelta(minutes=30)
        slots = max(1, round(duration.total_seconds() / 900))
        for slot in range(slots):
            slot_start = start + timedelta(minutes=15 * slot)
            if kind == "kw":
                kwh = value / Decimal("4")
            elif kind == "w":
                kwh = value / Decimal("4000")
            elif kind == "wh":
                kwh = value / Decimal("1000") / Decimal(slots)
            else:
                kwh = value / Decimal(slots)
            result.append(
                EnergyForecastPeriod(
                    slot_start,
                    slot_start + timedelta(minutes=15),
                    solar_kwh=max(Decimal("0"), kwh),
                )
            )
    return tuple(result)


def combine_solar_forecasts(
    forecasts: Iterable[tuple[EnergyForecastPeriod, ...]], strategy: str
) -> tuple[EnergyForecastPeriod, ...]:
    """Combine multiple providers without changing native time resolution."""
    grouped: dict[datetime, list[EnergyForecastPeriod]] = {}
    for forecast in forecasts:
        for item in forecast:
            grouped.setdefault(item.start, []).append(item)
    combined = []
    for start, items in sorted(grouped.items()):
        values = [item.solar_kwh for item in items]
        if strategy == "conservative":
            solar = min(values)
        elif strategy == "optimistic":
            solar = max(values)
        else:
            solar = sum(values, Decimal("0")) / Decimal(len(values))
        combined.append(EnergyForecastPeriod(start, items[0].end, solar_kwh=solar))
    return tuple(combined)


def _datetime_value(item: Mapping[str, Any]) -> datetime | None:
    for key in START_KEYS:
        value = item.get(key)
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else None
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                return parsed
    return None


def _energy_value(item: Mapping[str, Any]) -> tuple[Decimal, str] | None:
    for keys, kind in ((ENERGY_KEYS, "kwh"), (POWER_KW_KEYS, "kw"), (POWER_W_KEYS, "w")):
        for key in keys:
            if key not in item:
                continue
            try:
                value = Decimal(str(item[key]))
            except (InvalidOperation, TypeError):
                continue
            if value.is_finite():
                if key == "wh_period":
                    kind = "wh"
                return value, kind
    return None
