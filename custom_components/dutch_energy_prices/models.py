"""Price-domain models used independently of Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

PERIOD_DURATION = timedelta(minutes=15)


def _validate_period(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Price period datetimes must be timezone-aware")
    if end.astimezone(UTC) - start.astimezone(UTC) != PERIOD_DURATION:
        raise ValueError("Price periods must be exactly 15 minutes")


@dataclass(frozen=True, slots=True)
class MarketPricePeriod:
    """A native 15-minute market-price period in EUR/kWh."""

    start: datetime
    end: datetime
    market_price: Decimal

    def __post_init__(self) -> None:
        _validate_period(self.start, self.end)


@dataclass(frozen=True, slots=True)
class PricePeriod:
    """A calculated native 15-minute price period in EUR/kWh."""

    start: datetime
    end: datetime
    market_price: Decimal
    import_price: Decimal
    export_price: Decimal
    import_vat: Decimal = Decimal("0")
    export_vat: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _validate_period(self.start, self.end)

    def as_dict(self) -> dict[str, str]:
        """Return a recorder-safe representation."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "market_price": str(self.market_price),
            "import_price": str(self.import_price),
            "export_price": str(self.export_price),
            "import_vat": str(self.import_vat),
            "export_vat": str(self.export_vat),
        }


@dataclass(frozen=True, slots=True)
class PriceSettings:
    """Variable Dutch price components and VAT applicability."""

    vat_percentage: Decimal
    energy_tax: Decimal
    supplier_import_markup: Decimal
    supplier_export_adjustment: Decimal
    battery_round_trip_efficiency: Decimal = Decimal("0.85")
    optimization_duration_minutes: int = 120
    vat_market_import: bool = True
    vat_import_markup: bool = True
    vat_energy_tax: bool = True
    vat_market_export: bool = False
    vat_export_adjustment: bool = False

    def __post_init__(self) -> None:
        if self.vat_percentage < 0:
            raise ValueError("VAT percentage cannot be negative")
        if not Decimal("0") < self.battery_round_trip_efficiency <= Decimal("1"):
            raise ValueError("Battery round-trip efficiency must be above 0 and at most 1")
        if self.optimization_duration_minutes < 15:
            raise ValueError("Optimisation duration must be at least 15 minutes")
        if self.optimization_duration_minutes % 15:
            raise ValueError("Optimisation duration must use 15-minute increments")

    @property
    def vat_multiplier(self) -> Decimal:
        return Decimal("1") + self.vat_percentage / Decimal("100")


@dataclass(frozen=True, slots=True)
class PriceData:
    """Coordinator result."""

    periods: tuple[PricePeriod, ...]
    fetched_at: datetime
    provider_name: str


@dataclass(frozen=True, slots=True)
class PriceWindow:
    """A contiguous group of 15-minute periods."""

    start: datetime
    end: datetime
    periods: tuple[PricePeriod, ...]
    average_import_price: Decimal


@dataclass(frozen=True, slots=True)
class BatteryArbitrageOpportunity:
    """The best ordered grid-charge and later-discharge window pair."""

    charge_window: PriceWindow
    discharge_window: PriceWindow
    effective_charge_cost: Decimal
    profit_per_kwh: Decimal


@dataclass(frozen=True, slots=True)
class SolarStorageOpportunity:
    """Value of storing current solar surplus for a later window."""

    current_period: PricePeriod
    discharge_window: PriceWindow
    value_per_kwh: Decimal
