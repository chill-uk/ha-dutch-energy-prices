"""Forecast-aware battery optimisation at native 15-minute resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .models import (
    BatterySnapshot,
    EnergyForecastPeriod,
    OptimizedEnergyPlan,
    PlannedEnergySlot,
    PricePeriod,
    PriceSettings,
)


@dataclass(frozen=True, slots=True)
class _Source:
    """Energy offered to the battery before charging losses."""

    index: int
    kind: str
    available_kwh: Decimal
    cost_per_kwh: Decimal


@dataclass(frozen=True, slots=True)
class _Sink:
    """Useful AC energy that may be supplied by the battery."""

    index: int
    kind: str
    available_kwh: Decimal
    value_per_kwh: Decimal


def _remaining_fraction(period: PricePeriod, now: datetime) -> Decimal:
    if now <= period.start:
        return Decimal("1")
    if now >= period.end:
        return Decimal("0")
    return Decimal(str((period.end - now).total_seconds())) / Decimal("900")


def _forecast_by_start(
    forecasts: tuple[EnergyForecastPeriod, ...],
) -> dict[datetime, EnergyForecastPeriod]:
    return {item.start: item for item in forecasts}


def calculate_reserve(
    periods: tuple[PricePeriod, ...],
    forecasts: tuple[EnergyForecastPeriod, ...],
    battery: BatterySnapshot,
    settings: PriceSettings,
    now: datetime,
    fallback_load_kw: Decimal = Decimal("0"),
) -> Decimal:
    """Protect energy needed until conservative solar surplus is expected."""
    minimum = (
        battery.capacity_kwh * settings.battery_min_reserve_percent / Decimal("100")
        + settings.battery_reserve_buffer_kwh
    )
    forecast = _forecast_by_start(forecasts)
    confidence = settings.solar_confidence_percent / Decimal("100")
    future_periods = [period for period in periods if period.end > now]
    first_surplus = next(
        (
            index
            for index, period in enumerate(future_periods)
            if (item := forecast.get(period.start)) is not None
            and item.solar_kwh * confidence
            > (item.load_kwh if item.load_kwh > 0 else fallback_load_kw / Decimal("4"))
        ),
        None,
    )
    if first_surplus is None:
        return min(battery.capacity_kwh, minimum)
    bridge_load = Decimal("0")
    for period in future_periods[:first_surplus]:
        fraction = _remaining_fraction(period, now)
        item = forecast.get(period.start)
        solar = (item.solar_kwh * confidence if item else Decimal("0")) * fraction
        load = (
            item.load_kwh
            if item is not None and item.load_kwh > 0
            else fallback_load_kw / Decimal("4")
        ) * fraction
        bridge_load += max(Decimal("0"), load - solar)
    reserve = minimum + bridge_load / settings.resolved_discharge_efficiency
    return min(battery.capacity_kwh, reserve)


def optimize_energy_plan(
    periods: tuple[PricePeriod, ...],
    battery: BatterySnapshot,
    settings: PriceSettings,
    *,
    now: datetime,
    forecasts: tuple[EnergyForecastPeriod, ...] = (),
    fallback_load_kw: Decimal = Decimal("0"),
) -> OptimizedEnergyPlan:
    """Build a power-limited plan from exact per-slot prices and forecasts.

    The optimiser values household use at the avoided import tariff and export
    at the export tariff. Grid and solar inputs may occupy non-contiguous slots;
    every allocation retains its native duration and exact price.
    """
    future = tuple(period for period in periods if period.end > now)
    if not future or not battery.banks:
        return _empty_plan("Price or battery data unavailable")

    charge_efficiency = settings.battery_charge_efficiency
    discharge_efficiency = settings.resolved_discharge_efficiency
    round_trip = settings.resolved_round_trip_efficiency
    forecast = _forecast_by_start(forecasts)
    confidence = settings.solar_confidence_percent / Decimal("100")
    reserve = calculate_reserve(
        future, forecasts, battery, settings, now, fallback_load_kw=fallback_load_kw
    )

    sources: list[_Source] = []
    sinks: list[_Sink] = []
    slot_values: list[dict[str, Decimal]] = [
        {
            "grid": Decimal("0"),
            "solar": Decimal("0"),
            "self": Decimal("0"),
            "export": Decimal("0"),
            "value": Decimal("0"),
        }
        for _ in future
    ]

    for index, period in enumerate(future):
        fraction = _remaining_fraction(period, now)
        duration_hours = fraction / Decimal("4")
        if duration_hours <= 0:
            continue
        item = forecast.get(period.start)
        solar = (item.solar_kwh * confidence if item else Decimal("0")) * fraction
        load = (
            item.load_kwh
            if item is not None and item.load_kwh > 0
            else fallback_load_kw / Decimal("4")
        ) * fraction
        surplus = max(Decimal("0"), solar - load)
        deficit = max(Decimal("0"), load - solar)
        grid_cap = settings.max_charge_power_kw * duration_hours
        solar_cap = min(grid_cap, surplus)
        if solar_cap > 0:
            sources.append(_Source(index, "solar", solar_cap, period.export_price))
        sources.append(_Source(index, "grid", grid_cap, period.import_price))

        discharge_cap = settings.max_discharge_power_kw * duration_hours
        self_use = min(discharge_cap, deficit)
        if self_use > 0:
            sinks.append(_Sink(index, "self", self_use, period.import_price))
        if settings.allow_grid_export and discharge_cap > self_use:
            sinks.append(_Sink(index, "export", discharge_cap - self_use, period.export_price))

    source_remaining = {index: source.available_kwh for index, source in enumerate(sources)}
    sink_remaining = {index: sink.available_kwh for index, sink in enumerate(sinks)}
    operating_cost = settings.battery_operating_cost

    # Existing stored energy has no new acquisition cost. Use it in the most
    # valuable slots while preserving the forecast-derived reserve.
    stored_output = max(Decimal("0"), battery.stored_energy_kwh - reserve) * discharge_efficiency
    for sink_index in sorted(
        range(len(sinks)), key=lambda item: sinks[item].value_per_kwh, reverse=True
    ):
        sink = sinks[sink_index]
        net_per_kwh = sink.value_per_kwh - operating_cost
        if net_per_kwh < settings.minimum_profit or stored_output <= 0:
            continue
        amount = min(stored_output, sink_remaining[sink_index])
        _assign_sink(slot_values[sink.index], sink.kind, amount)
        slot_values[sink.index]["value"] += amount * net_per_kwh
        sink_remaining[sink_index] -= amount
        stored_output -= amount

    target_input = settings.battery_target_energy_kwh / round_trip
    acquired_input = Decimal("0")

    candidates: list[tuple[Decimal, int, int]] = []
    for source_index, source in enumerate(sources):
        for sink_index, sink in enumerate(sinks):
            if sink.index <= source.index:
                continue
            margin = sink.value_per_kwh * round_trip - source.cost_per_kwh
            margin -= operating_cost * round_trip
            if margin >= settings.minimum_profit:
                candidates.append((margin, source_index, sink_index))
    # Retaining solar is the primary summer objective. Within each source type,
    # still choose the greatest exact economic margin first.
    candidates.sort(
        key=lambda item: (
            sources[item[1]].kind == "solar",
            item[0],
            -sources[item[1]].index,
        ),
        reverse=True,
    )

    for _margin, source_index, sink_index in candidates:
        source = sources[source_index]
        sink = sinks[sink_index]
        if acquired_input >= target_input:
            break
        source_left = source_remaining[source_index]
        sink_left = sink_remaining[sink_index]
        if source_left <= 0 or sink_left <= 0:
            continue
        capacity_input = _capacity_input_limit(
            slot_values,
            source.index,
            sink.index,
            battery.stored_energy_kwh,
            battery.capacity_kwh,
            charge_efficiency,
            discharge_efficiency,
        )
        amount = min(
            source_left,
            sink_left / round_trip,
            target_input - acquired_input,
            capacity_input,
        )
        if amount <= 0:
            continue
        delivered = amount * round_trip
        slot_values[source.index][source.kind] += amount
        _assign_sink(slot_values[sink.index], sink.kind, delivered)
        slot_values[source.index]["value"] -= amount * source.cost_per_kwh
        slot_values[sink.index]["value"] += delivered * (sink.value_per_kwh - operating_cost)
        source_remaining[source_index] -= amount
        sink_remaining[sink_index] -= delivered
        acquired_input += amount

    # A genuinely negative all-in import or export tariff can make retaining
    # energy profitable even when no later sink is visible inside the horizon.
    negative_sources = sorted(
        enumerate(sources),
        key=lambda item: (item[1].kind == "solar", -item[1].cost_per_kwh),
        reverse=True,
    )
    for source_index, source in negative_sources:
        if source.cost_per_kwh >= -settings.minimum_profit or acquired_input >= target_input:
            continue
        amount = min(
            source_remaining[source_index],
            target_input - acquired_input,
            _capacity_input_limit(
                slot_values,
                source.index,
                len(slot_values),
                battery.stored_energy_kwh,
                battery.capacity_kwh,
                charge_efficiency,
                discharge_efficiency,
            ),
        )
        if amount <= 0:
            continue
        slot_values[source.index][source.kind] += amount
        slot_values[source.index]["value"] -= amount * source.cost_per_kwh
        source_remaining[source_index] -= amount
        acquired_input += amount

    planned = tuple(
        PlannedEnergySlot(
            start=period.start,
            end=period.end,
            grid_charge_kwh=values["grid"],
            solar_charge_kwh=values["solar"],
            self_discharge_kwh=values["self"],
            export_discharge_kwh=values["export"],
            value_eur=values["value"],
        )
        for period, values in zip(future, slot_values, strict=True)
    )
    grid_charge = sum((slot.grid_charge_kwh for slot in planned), Decimal("0"))
    solar_charge = sum((slot.solar_charge_kwh for slot in planned), Decimal("0"))
    self_discharge = sum((slot.self_discharge_kwh for slot in planned), Decimal("0"))
    export_discharge = sum((slot.export_discharge_kwh for slot in planned), Decimal("0"))
    by_start = {period.start: period for period in future}
    charge_cost = sum(
        (slot.grid_charge_kwh * by_start[slot.start].import_price for slot in planned),
        Decimal("0"),
    )
    avoided_import = sum(
        (slot.self_discharge_kwh * by_start[slot.start].import_price for slot in planned),
        Decimal("0"),
    )
    export_revenue = sum(
        (slot.export_discharge_kwh * by_start[slot.start].export_price for slot in planned),
        Decimal("0"),
    )
    throughput = self_discharge + export_discharge
    op_cost = throughput * operating_cost
    solar_opportunity_cost = sum(
        (slot.solar_charge_kwh * by_start[slot.start].export_price for slot in planned),
        Decimal("0"),
    )
    net = avoided_import + export_revenue - charge_cost - solar_opportunity_cost - op_cost
    reason = (
        "Profitable schedule available"
        if any(slot.action != "hold" for slot in planned)
        else "No opportunity exceeds the minimum profit"
    )
    return OptimizedEnergyPlan(
        planned,
        reserve,
        grid_charge,
        solar_charge,
        self_discharge,
        export_discharge,
        charge_cost,
        avoided_import,
        export_revenue,
        op_cost,
        net,
        reason,
    )


def _assign_sink(values: dict[str, Decimal], kind: str, amount: Decimal) -> None:
    values["self" if kind == "self" else "export"] += amount


def _capacity_input_limit(
    slots: list[dict[str, Decimal]],
    source_index: int,
    sink_index: int,
    initial_stored_kwh: Decimal,
    capacity_kwh: Decimal,
    charge_efficiency: Decimal,
    discharge_efficiency: Decimal,
) -> Decimal:
    """Return input headroom while a proposed charge remains in storage."""
    stored = initial_stored_kwh
    headroom = capacity_kwh
    for index, slot in enumerate(slots):
        stored += (slot["grid"] + slot["solar"]) * charge_efficiency
        stored -= (slot["self"] + slot["export"]) / discharge_efficiency
        if source_index <= index < sink_index:
            headroom = min(headroom, capacity_kwh - stored)
    return max(Decimal("0"), headroom) / charge_efficiency


def _empty_plan(reason: str) -> OptimizedEnergyPlan:
    zero = Decimal("0")
    return OptimizedEnergyPlan(
        (), zero, zero, zero, zero, zero, zero, zero, zero, zero, zero, reason
    )
