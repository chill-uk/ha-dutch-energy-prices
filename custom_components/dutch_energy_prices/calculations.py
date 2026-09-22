"""Pure monetary and optimisation calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from .models import (
    BatteryArbitrageOpportunity,
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
