"""Pure monetary and optimisation calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

from .models import (
    BatteryArbitrageOpportunity,
    BatteryEnergyPlan,
    MarketPricePeriod,
    PricePeriod,
    PriceSettings,
    PriceWindow,
    SolarStorageOpportunity,
)


def _with_configurable_vat(
    components: Iterable[tuple[Decimal, bool]], multiplier: Decimal
) -> Decimal:
    return sum(
        (value * multiplier if is_taxable else value for value, is_taxable in components),
        start=Decimal("0"),
    )


def _vat_amount(components: Iterable[tuple[Decimal, bool]], multiplier: Decimal) -> Decimal:
    return sum(
        (value * (multiplier - Decimal("1")) for value, is_taxable in components if is_taxable),
        start=Decimal("0"),
    )


def calculate_period(raw: MarketPricePeriod, settings: PriceSettings) -> PricePeriod:
    """Apply supplier components, energy tax and component-specific VAT."""
    import_components = (
        (raw.market_price, settings.vat_market_import),
        (settings.supplier_import_markup, settings.vat_import_markup),
        (settings.energy_tax, settings.vat_energy_tax),
    )
    export_components = (
        (raw.market_price, settings.vat_market_export),
        (settings.supplier_export_adjustment, settings.vat_export_adjustment),
    )
    import_price = _with_configurable_vat(import_components, settings.vat_multiplier)
    export_price = _with_configurable_vat(export_components, settings.vat_multiplier)
    return PricePeriod(
        start=raw.start,
        end=raw.end,
        market_price=raw.market_price,
        import_price=import_price,
        export_price=export_price,
        import_vat=_vat_amount(import_components, settings.vat_multiplier),
        export_vat=_vat_amount(export_components, settings.vat_multiplier),
    )


def calculate_periods(
    raw_periods: Iterable[MarketPricePeriod], settings: PriceSettings
) -> tuple[PricePeriod, ...]:
    """Calculate and chronologically sort price periods."""
    calculated = tuple(
        calculate_period(item, settings) for item in sorted(raw_periods, key=lambda p: p.start)
    )
    if any(left.end > right.start for left, right in zip(calculated, calculated[1:], strict=False)):
        raise ValueError("Price periods must not overlap")
    return calculated


def current_period(periods: Iterable[PricePeriod], now: datetime) -> PricePeriod | None:
    """Find the period containing now."""
    return next((period for period in periods if period.start <= now < period.end), None)


def cheapest_window(
    periods: Iterable[PricePeriod], slots: int, *, not_before: datetime | None = None
) -> PriceWindow | None:
    """Return the cheapest contiguous window, preserving 15-minute resolution."""
    windows = _contiguous_windows(periods, slots, not_before=not_before)
    return min(windows, key=lambda window: window.average_import_price, default=None)


def _contiguous_windows(
    periods: Iterable[PricePeriod], slots: int, *, not_before: datetime | None = None
) -> tuple[PriceWindow, ...]:
    """Build every complete contiguous window at native 15-minute resolution."""
    if slots < 1:
        raise ValueError("slots must be at least 1")

    candidates = sorted(
        (period for period in periods if not_before is None or period.start >= not_before),
        key=lambda period: period.start,
    )
    windows: list[PriceWindow] = []
    for index in range(len(candidates) - slots + 1):
        window = tuple(candidates[index : index + slots])
        if any(left.end != right.start for left, right in zip(window, window[1:], strict=False)):
            continue
        average = sum((period.import_price for period in window), Decimal("0")) / Decimal(slots)
        windows.append(PriceWindow(window[0].start, window[-1].end, window, average))
    return tuple(windows)


def best_battery_arbitrage(
    periods: Iterable[PricePeriod],
    slots: int,
    efficiency: Decimal,
    *,
    not_before: datetime | None = None,
) -> BatteryArbitrageOpportunity | None:
    """Return the most valuable charge-then-discharge window pair."""
    _validate_efficiency(efficiency)
    windows = _contiguous_windows(periods, slots, not_before=not_before)
    best: BatteryArbitrageOpportunity | None = None
    for charge_window in windows:
        for discharge_window in windows:
            if discharge_window.start < charge_window.end:
                continue
            effective_cost = effective_battery_cost(charge_window.average_import_price, efficiency)
            profit = discharge_window.average_import_price - effective_cost
            candidate = BatteryArbitrageOpportunity(
                charge_window=charge_window,
                discharge_window=discharge_window,
                effective_charge_cost=effective_cost,
                profit_per_kwh=profit,
            )
            if best is None or candidate.profit_per_kwh > best.profit_per_kwh:
                best = candidate
    return best


def _allocate_window(
    window: PriceWindow, energy_kwh: Decimal, per_slot_kwh: Decimal, *, charge: bool
) -> tuple[tuple[Decimal, ...], Decimal]:
    """Fill full slots and place the partial slot at the least costly price."""
    remainder = energy_kwh % per_slot_kwh
    allocation = [per_slot_kwh] * len(window.periods)
    if remainder:
        # A charge window benefits from reducing its most expensive slot;
        # a discharge window benefits from reducing its least valuable slot.
        partial_index = (max if charge else min)(
            range(len(window.periods)), key=lambda index: window.periods[index].import_price
        )
        allocation[partial_index] = remainder
    prices = (period.import_price for period in window.periods)
    value = sum(
        (amount * price for amount, price in zip(allocation, prices, strict=True)), Decimal("0")
    )
    return tuple(allocation), value


def best_battery_energy_plan(
    periods: Iterable[PricePeriod],
    target_delivered_kwh: Decimal,
    max_charge_kw: Decimal,
    max_discharge_kw: Decimal,
    efficiency: Decimal,
    *,
    not_before: datetime | None = None,
) -> BatteryEnergyPlan | None:
    """Maximise avoided import less charging cost for a fixed energy target.

    Uses the fewest contiguous 15-minute slots at the configured power caps.
    Output assumes enough household demand to use every discharged kWh.
    """
    _validate_efficiency(efficiency)
    if min(target_delivered_kwh, max_charge_kw, max_discharge_kw) <= 0:
        raise ValueError("Target energy and charge/discharge power must be positive")
    grid_kwh = target_delivered_kwh / efficiency
    charge_per_slot = max_charge_kw / Decimal("4")
    discharge_per_slot = max_discharge_kw / Decimal("4")
    charge_slots = int((grid_kwh / charge_per_slot).to_integral_value(rounding=ROUND_CEILING))
    discharge_slots = int(
        (target_delivered_kwh / discharge_per_slot).to_integral_value(rounding=ROUND_CEILING)
    )
    available = tuple(periods)
    charge_windows = _contiguous_windows(available, charge_slots, not_before=not_before)
    discharge_windows = _contiguous_windows(available, discharge_slots, not_before=not_before)
    charge_candidates = [
        (window, *_allocate_window(window, grid_kwh, charge_per_slot, charge=True))
        for window in charge_windows
    ]
    discharge_candidates = [
        (window, *_allocate_window(window, target_delivered_kwh, discharge_per_slot, charge=False))
        for window in discharge_windows
    ]
    best: BatteryEnergyPlan | None = None
    for charge_window, charge_allocation, charge_cost in charge_candidates:
        for discharge_window, discharge_allocation, avoided_import in discharge_candidates:
            if discharge_window.start < charge_window.end:
                continue
            net_value = avoided_import - charge_cost
            if best is None or net_value > best.net_value_eur:
                best = BatteryEnergyPlan(
                    charge_window=charge_window,
                    discharge_window=discharge_window,
                    charge_slot_kwh=charge_allocation,
                    discharge_slot_kwh=discharge_allocation,
                    grid_energy_kwh=grid_kwh,
                    delivered_energy_kwh=target_delivered_kwh,
                    charge_cost_eur=charge_cost,
                    avoided_import_eur=avoided_import,
                    net_value_eur=net_value,
                )
    return best


def best_solar_storage(
    periods: Iterable[PricePeriod],
    slots: int,
    efficiency: Decimal,
    *,
    now: datetime,
) -> SolarStorageOpportunity | None:
    """Value current solar export against the best complete later usage window."""
    _validate_efficiency(efficiency)
    ordered = tuple(sorted(periods, key=lambda period: period.start))
    current = current_period(ordered, now)
    if current is None:
        return None

    windows = _contiguous_windows(ordered, slots, not_before=current.end)
    if not windows:
        return None
    discharge_window = max(windows, key=lambda window: window.average_import_price)
    value = solar_storage_value(
        current.export_price, discharge_window.average_import_price, efficiency
    )
    return SolarStorageOpportunity(current, discharge_window, value)


def effective_battery_cost(import_price: Decimal, efficiency: Decimal) -> Decimal:
    """Return effective delivered cost after round-trip losses."""
    _validate_efficiency(efficiency)
    return import_price / efficiency


def grid_arbitrage_profit(
    charge_import_price: Decimal, future_import_price: Decimal, efficiency: Decimal
) -> Decimal:
    """Return avoided future import cost per delivered kWh."""
    return future_import_price - effective_battery_cost(charge_import_price, efficiency)


def solar_storage_value(
    current_export_price: Decimal, future_import_price: Decimal, efficiency: Decimal
) -> Decimal:
    """Return the value of storing one kWh of solar instead of exporting it."""
    _validate_efficiency(efficiency)
    return future_import_price * efficiency - current_export_price


def _validate_efficiency(efficiency: Decimal) -> None:
    """Validate a round-trip efficiency fraction."""
    if not Decimal("0") < efficiency <= Decimal("1"):
        raise ValueError("efficiency must be above 0 and at most 1")
