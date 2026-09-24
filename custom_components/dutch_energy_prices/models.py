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
    battery_charge_efficiency: Decimal = Decimal("0.90")
    battery_discharge_efficiency: Decimal | None = None
    optimization_duration_minutes: int = 120
    max_charge_power_kw: Decimal = Decimal("3")
    max_discharge_power_kw: Decimal = Decimal("2.4")
    battery_target_energy_kwh: Decimal = Decimal("10")
    battery_usable_capacity_kwh: Decimal = Decimal("17")
    battery_min_reserve_percent: Decimal = Decimal("15")
    battery_reserve_buffer_kwh: Decimal = Decimal("1")
    solar_confidence_percent: Decimal = Decimal("80")
    battery_operating_cost: Decimal = Decimal("0.02")
    minimum_profit: Decimal = Decimal("0.01")
    allow_grid_export: bool = False
    action_confirmation_updates: int = 2
    minimum_action_minutes: int = 5
    telemetry_stale_minutes: int = 10
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
        if not Decimal("0") < self.battery_charge_efficiency <= Decimal("1"):
            raise ValueError("Battery charging efficiency must be above 0 and at most 1")
        discharge_efficiency = self.resolved_discharge_efficiency
        if not Decimal("0") < discharge_efficiency <= Decimal("1"):
            raise ValueError("Battery discharging efficiency must be above 0 and at most 1")
        if self.optimization_duration_minutes < 15:
            raise ValueError("Optimisation duration must be at least 15 minutes")
        if self.optimization_duration_minutes % 15:
            raise ValueError("Optimisation duration must use 15-minute increments")
        if (
            min(
                self.max_charge_power_kw,
                self.max_discharge_power_kw,
                self.battery_target_energy_kwh,
            )
            <= 0
        ):
            raise ValueError("Battery power limits and target energy must be positive")
        if self.battery_usable_capacity_kwh <= 0:
            raise ValueError("Usable battery capacity must be positive")
        if not 0 <= self.battery_min_reserve_percent <= 100:
            raise ValueError("Battery minimum reserve must be between 0 and 100%")
        if self.battery_reserve_buffer_kwh < 0:
            raise ValueError("Battery reserve buffer cannot be negative")
        if not 0 <= self.solar_confidence_percent <= 100:
            raise ValueError("Solar confidence must be between 0 and 100%")
        if self.battery_operating_cost < 0 or self.minimum_profit < 0:
            raise ValueError("Battery cost and minimum profit cannot be negative")
        if (
            min(
                self.action_confirmation_updates,
                self.minimum_action_minutes,
                self.telemetry_stale_minutes,
            )
            < 1
        ):
            raise ValueError("Action stability values must be at least one")

    @property
    def vat_multiplier(self) -> Decimal:
        return Decimal("1") + self.vat_percentage / Decimal("100")

    @property
    def resolved_discharge_efficiency(self) -> Decimal:
        """Return explicit discharge efficiency or derive it from round trip."""
        if self.battery_discharge_efficiency is not None:
            return self.battery_discharge_efficiency
        return self.battery_round_trip_efficiency / self.battery_charge_efficiency

    @property
    def resolved_round_trip_efficiency(self) -> Decimal:
        """Return the product of the independently modelled conversion stages."""
        return self.battery_charge_efficiency * self.resolved_discharge_efficiency


@dataclass(frozen=True, slots=True)
class BatteryBank:
    """Normalised live state for one battery bank."""

    name: str
    capacity_kwh: Decimal
    stored_energy_kwh: Decimal
    state_of_health_percent: Decimal = Decimal("100")
    max_charge_power_kw: Decimal | None = None
    max_discharge_power_kw: Decimal | None = None
    capacity_source: str = "configured"

    def __post_init__(self) -> None:
        if self.capacity_kwh <= 0:
            raise ValueError("Battery bank capacity must be positive")
        if not 0 <= self.stored_energy_kwh <= self.capacity_kwh:
            raise ValueError("Stored battery energy must be within bank capacity")
        if not 0 < self.state_of_health_percent <= 100:
            raise ValueError("Battery state of health must be above 0 and at most 100%")


@dataclass(frozen=True, slots=True)
class BatterySnapshot:
    """Aggregate one or more independently measured battery banks."""

    banks: tuple[BatteryBank, ...]

    @property
    def capacity_kwh(self) -> Decimal:
        return sum((bank.capacity_kwh for bank in self.banks), Decimal("0"))

    @property
    def stored_energy_kwh(self) -> Decimal:
        return sum((bank.stored_energy_kwh for bank in self.banks), Decimal("0"))

    @property
    def state_of_charge_percent(self) -> Decimal:
        if not self.banks:
            return Decimal("0")
        return self.stored_energy_kwh / self.capacity_kwh * Decimal("100")


@dataclass(frozen=True, slots=True)
class EnergyForecastPeriod:
    """A 15-minute solar and household-consumption forecast in kWh."""

    start: datetime
    end: datetime
    solar_kwh: Decimal = Decimal("0")
    load_kwh: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _validate_period(self.start, self.end)
        if self.solar_kwh < 0 or self.load_kwh < 0:
            raise ValueError("Forecast energy cannot be negative")


@dataclass(frozen=True, slots=True)
class PlannedEnergySlot:
    """Optimiser allocation for one native price period."""

    start: datetime
    end: datetime
    grid_charge_kwh: Decimal = Decimal("0")
    solar_charge_kwh: Decimal = Decimal("0")
    self_discharge_kwh: Decimal = Decimal("0")
    export_discharge_kwh: Decimal = Decimal("0")
    value_eur: Decimal = Decimal("0")

    @property
    def action(self) -> str:
        if self.grid_charge_kwh > 0:
            return "charge"
        if self.solar_charge_kwh > 0:
            return "solar_charge"
        if self.self_discharge_kwh > 0 or self.export_discharge_kwh > 0:
            return "discharge"
        return "hold"


@dataclass(frozen=True, slots=True)
class OptimizedEnergyPlan:
    """Full-horizon plan composed of native 15-minute allocations."""

    slots: tuple[PlannedEnergySlot, ...]
    reserve_kwh: Decimal
    grid_charge_kwh: Decimal
    solar_charge_kwh: Decimal
    self_discharge_kwh: Decimal
    export_discharge_kwh: Decimal
    charge_cost_eur: Decimal
    avoided_import_eur: Decimal
    export_revenue_eur: Decimal
    operating_cost_eur: Decimal
    net_value_eur: Decimal
    reason: str


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
class BatteryEnergyPlan:
    """Power-limited plan for a target amount of delivered energy."""

    charge_window: PriceWindow
    discharge_window: PriceWindow
    charge_slot_kwh: tuple[Decimal, ...]
    discharge_slot_kwh: tuple[Decimal, ...]
    grid_energy_kwh: Decimal
    delivered_energy_kwh: Decimal
    charge_cost_eur: Decimal
    avoided_import_eur: Decimal
    net_value_eur: Decimal


@dataclass(frozen=True, slots=True)
class SolarStorageOpportunity:
    """Value of storing current solar surplus for a later window."""

    current_period: PricePeriod
    discharge_window: PriceWindow
    value_per_kwh: Decimal
