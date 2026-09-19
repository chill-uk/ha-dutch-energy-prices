"""Pure monetary and optimisation calculations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from .models import MarketPricePeriod, PricePeriod, PriceSettings, PriceWindow


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
    if slots < 1:
        raise ValueError("slots must be at least 1")

    candidates = sorted(
        (period for period in periods if not_before is None or period.start >= not_before),
        key=lambda period: period.start,
    )
    best: PriceWindow | None = None
    for index in range(len(candidates) - slots + 1):
        window = tuple(candidates[index : index + slots])
        if any(left.end != right.start for left, right in zip(window, window[1:], strict=False)):
            continue
        average = sum((period.import_price for period in window), Decimal("0")) / Decimal(slots)
        candidate = PriceWindow(window[0].start, window[-1].end, window, average)
        if best is None or candidate.average_import_price < best.average_import_price:
            best = candidate
    return best


def effective_battery_cost(import_price: Decimal, efficiency: Decimal) -> Decimal:
    """Return effective delivered cost after round-trip losses."""
    if not Decimal("0") < efficiency <= Decimal("1"):
        raise ValueError("efficiency must be above 0 and at most 1")
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
    if not Decimal("0") < efficiency <= Decimal("1"):
        raise ValueError("efficiency must be above 0 and at most 1")
    return future_import_price * efficiency - current_export_price
