"""Sensor platform for Dutch Energy Prices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .calculations import (
    best_battery_arbitrage,
    best_battery_energy_plan,
    best_solar_storage,
    cheapest_window,
    current_period,
    effective_battery_cost,
)
from .const import (
    ATTR_PRICES_TODAY,
    ATTR_PRICES_TOMORROW,
    CONF_CURRENCY_DISPLAY,
    CURRENCY_UNITS,
    DOMAIN,
    UNIT_CENT_PER_KWH,
    UNIT_EUR_PER_KWH,
    CurrencyDisplay,
)
from .coordinator import DutchEnergyPricesCoordinator
from .models import (
    BatteryArbitrageOpportunity,
    BatteryEnergyPlan,
    OptimizedEnergyPlan,
    PlannedEnergySlot,
    PricePeriod,
    PriceWindow,
    SolarStorageOpportunity,
)
from .rolling_plan import ActionStabilizer, RollingDecision, rolling_decision
from .telemetry import power_kw


@dataclass(frozen=True, kw_only=True)
class DutchPriceSensorDescription(SensorEntityDescription):
    """Describe a current-price sensor."""

    value_fn: Callable[[PricePeriod, DutchEnergyPricesCoordinator], Decimal]
    include_prices: bool = False


SENSOR_DESCRIPTIONS = (
    DutchPriceSensorDescription(
        key="market_price",
        translation_key="market_price",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: period.market_price,
        include_prices=True,
    ),
    DutchPriceSensorDescription(
        key="import_price",
        translation_key="import_price",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: period.import_price,
    ),
    DutchPriceSensorDescription(
        key="export_price",
        translation_key="export_price",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: period.export_price,
    ),
    DutchPriceSensorDescription(
        key="energy_tax",
        translation_key="energy_tax",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: coordinator.settings.energy_tax,
    ),
    DutchPriceSensorDescription(
        key="vat",
        translation_key="vat",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: period.import_vat,
    ),
    DutchPriceSensorDescription(
        key="import_export_spread",
        translation_key="import_export_spread",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: period.import_price - period.export_price,
    ),
    DutchPriceSensorDescription(
        key="effective_battery_cost",
        translation_key="effective_battery_cost",
        suggested_display_precision=5,
        value_fn=lambda period, coordinator: effective_battery_cost(
            period.import_price, coordinator.settings.battery_round_trip_efficiency
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors from the shared coordinator."""
    coordinator: DutchEnergyPricesCoordinator = entry.runtime_data
    config = {**entry.data, **entry.options}
    currency = CurrencyDisplay(config[CONF_CURRENCY_DISPLAY])
    unit = CURRENCY_UNITS[currency]
    entities = [
        DutchCurrentPriceSensor(
            coordinator,
            entry,
            replace(description, native_unit_of_measurement=unit),
            currency,
        )
        for description in SENSOR_DESCRIPTIONS
    ] + [
        DutchCheapestWindowSensor(coordinator, entry, "cheapest_slot", 1, currency),
        DutchCheapestWindowSensor(coordinator, entry, "cheapest_1h", 4, currency),
        DutchCheapestWindowSensor(coordinator, entry, "cheapest_2h", 8, currency),
        DutchBatteryWindowSensor(
            coordinator, entry, "best_battery_charge_period", "charge", currency
        ),
        DutchBatteryWindowSensor(
            coordinator, entry, "best_battery_discharge_period", "discharge", currency
        ),
        DutchArbitrageValueSensor(coordinator, entry, currency),
        DutchSolarStorageValueSensor(coordinator, entry, currency),
        DutchBatteryPlanWindowSensor(coordinator, entry, "charge"),
        DutchBatteryPlanWindowSensor(coordinator, entry, "discharge"),
        DutchBatteryPlanValueSensor(coordinator, entry),
    ]
    if (
        coordinator.soc_entity_ids or coordinator.stored_energy_entity_ids
    ) and coordinator.load_entity_id:
        entities.extend(
            [
                DutchOptimizedPlanMetricSensor(coordinator, entry, "optimized_plan_value"),
                DutchOptimizedPlanMetricSensor(coordinator, entry, "planned_grid_charge_energy"),
                DutchOptimizedPlanMetricSensor(coordinator, entry, "planned_solar_charge_energy"),
                DutchOptimizedPlanMetricSensor(coordinator, entry, "planned_discharge_energy"),
                DutchOptimizedPlanMetricSensor(coordinator, entry, "battery_reserve_energy"),
                DutchOptimizedPlanTimeSensor(coordinator, entry, "next_optimized_charge", "charge"),
                DutchOptimizedPlanTimeSensor(
                    coordinator, entry, "next_optimized_discharge", "discharge"
                ),
            ]
        )
        entities.append(DutchRollingActionSensor(coordinator, entry))
    if coordinator.pv_power_entity_id and coordinator.load_entity_id:
        entities.append(DutchFlexibleLoadSensor(coordinator, entry))
    if coordinator.controller is not None:
        entities.append(DutchControlStatusSensor(coordinator, entry))
    async_add_entities(entities)


class DutchEnergyBaseSensor(CoordinatorEntity[DutchEnergyPricesCoordinator], SensorEntity):
    """Shared entity metadata."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DutchEnergyPricesCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_suggested_object_id = f"dutch_energy_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dutch Energy",
            manufacturer="Dutch Energy Prices",
            model="Calculated price service",
        )


class DutchCurrentPriceSensor(DutchEnergyBaseSensor):
    """Expose a current price component."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    # Forecast arrays are useful to live dashboard cards but exceed Recorder's
    # attribute size limit once both complete days are available.
    _unrecorded_attributes = frozenset({ATTR_PRICES_TODAY, ATTR_PRICES_TOMORROW})

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        description: DutchPriceSensorDescription,
        currency: CurrencyDisplay,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description
        self._currency = currency

    @property
    def native_value(self) -> Decimal | None:
        period = current_period(self.coordinator.data.periods, dt_util.utcnow())
        if period is None:
            return None
        value = self.entity_description.value_fn(period, self.coordinator)
        return value if self._currency is CurrencyDisplay.EUR_PER_KWH else value * Decimal("100")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.entity_description.include_prices:
            return None
        today = dt_util.now().date()
        tomorrow = today + timedelta(days=1)
        result: dict[str, Any] = {ATTR_PRICES_TODAY: [], ATTR_PRICES_TOMORROW: []}
        for period in self.coordinator.data.periods:
            local_date = dt_util.as_local(period.start).date()
            if local_date == today:
                result[ATTR_PRICES_TODAY].append(period.as_dict())
            elif local_date == tomorrow:
                result[ATTR_PRICES_TOMORROW].append(period.as_dict())
        return result


class DutchCheapestWindowSensor(DutchEnergyBaseSensor):
    """Expose the start of a cheapest contiguous future window."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        key: str,
        slots: int,
        currency: CurrencyDisplay,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._slots = slots
        self._currency = currency

    @property
    def _window(self) -> PriceWindow | None:
        return cheapest_window(
            self.coordinator.data.periods, self._slots, not_before=dt_util.utcnow()
        )

    @property
    def native_value(self) -> datetime | None:
        window = self._window
        return window.start if window is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        window = self._window
        if window is None:
            return None
        price = window.average_import_price
        if self._currency is CurrencyDisplay.CENT_PER_KWH:
            price *= Decimal("100")
        return {
            "end": window.end.isoformat(),
            "average_import_price": str(price),
            "price_unit": (
                UNIT_EUR_PER_KWH
                if self._currency is CurrencyDisplay.EUR_PER_KWH
                else UNIT_CENT_PER_KWH
            ),
            "slots": self._slots,
        }


def _display_price(value: Decimal, currency: CurrencyDisplay) -> Decimal:
    """Convert an internal EUR/kWh amount to the selected display unit."""
    return value if currency is CurrencyDisplay.EUR_PER_KWH else value * Decimal("100")


def _price_unit(currency: CurrencyDisplay) -> str:
    """Return the configured monetary display unit."""
    return UNIT_EUR_PER_KWH if currency is CurrencyDisplay.EUR_PER_KWH else UNIT_CENT_PER_KWH


class DutchBatteryWindowSensor(DutchEnergyBaseSensor):
    """Expose one side of the best ordered battery-arbitrage opportunity."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        key: str,
        window_kind: Literal["charge", "discharge"],
        currency: CurrencyDisplay,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._window_kind = window_kind
        self._currency = currency

    @property
    def _opportunity(self) -> BatteryArbitrageOpportunity | None:
        settings = self.coordinator.settings
        return best_battery_arbitrage(
            self.coordinator.data.periods,
            settings.optimization_duration_minutes // 15,
            settings.battery_round_trip_efficiency,
            not_before=dt_util.utcnow(),
        )

    @property
    def native_value(self) -> datetime | None:
        opportunity = self._opportunity
        if opportunity is None:
            return None
        window = (
            opportunity.charge_window
            if self._window_kind == "charge"
            else opportunity.discharge_window
        )
        return window.start

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        opportunity = self._opportunity
        if opportunity is None:
            return None
        window = (
            opportunity.charge_window
            if self._window_kind == "charge"
            else opportunity.discharge_window
        )
        paired_window = (
            opportunity.discharge_window
            if self._window_kind == "charge"
            else opportunity.charge_window
        )
        return {
            "end": window.end.isoformat(),
            "duration_minutes": self.coordinator.settings.optimization_duration_minutes,
            "average_import_price": str(
                _display_price(window.average_import_price, self._currency)
            ),
            "paired_period_start": paired_window.start.isoformat(),
            "paired_period_end": paired_window.end.isoformat(),
            "estimated_arbitrage_value": str(
                _display_price(opportunity.profit_per_kwh, self._currency)
            ),
            "profitable": opportunity.profit_per_kwh > 0,
            "price_unit": _price_unit(self._currency),
        }


class DutchArbitrageValueSensor(DutchEnergyBaseSensor):
    """Expose the best forecast grid-arbitrage value per delivered kWh."""

    _attr_suggested_display_precision = 5

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        currency: CurrencyDisplay,
    ) -> None:
        super().__init__(coordinator, entry, "estimated_arbitrage_value")
        self._attr_translation_key = "estimated_arbitrage_value"
        self._currency = currency
        self._attr_native_unit_of_measurement = _price_unit(currency)

    @property
    def _opportunity(self) -> BatteryArbitrageOpportunity | None:
        settings = self.coordinator.settings
        return best_battery_arbitrage(
            self.coordinator.data.periods,
            settings.optimization_duration_minutes // 15,
            settings.battery_round_trip_efficiency,
            not_before=dt_util.utcnow(),
        )

    @property
    def native_value(self) -> Decimal | None:
        opportunity = self._opportunity
        if opportunity is None:
            return None
        return _display_price(opportunity.profit_per_kwh, self._currency)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        opportunity = self._opportunity
        if opportunity is None:
            return None
        return {
            "charge_start": opportunity.charge_window.start.isoformat(),
            "charge_end": opportunity.charge_window.end.isoformat(),
            "discharge_start": opportunity.discharge_window.start.isoformat(),
            "discharge_end": opportunity.discharge_window.end.isoformat(),
            "duration_minutes": self.coordinator.settings.optimization_duration_minutes,
            "average_charge_import_price": str(
                _display_price(opportunity.charge_window.average_import_price, self._currency)
            ),
            "effective_charge_cost": str(
                _display_price(opportunity.effective_charge_cost, self._currency)
            ),
            "average_discharge_import_price": str(
                _display_price(opportunity.discharge_window.average_import_price, self._currency)
            ),
            "round_trip_efficiency": str(self.coordinator.settings.battery_round_trip_efficiency),
            "profitable": opportunity.profit_per_kwh > 0,
        }


class DutchSolarStorageValueSensor(DutchEnergyBaseSensor):
    """Expose the value of storing current solar surplus instead of exporting it."""

    _attr_suggested_display_precision = 5

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        currency: CurrencyDisplay,
    ) -> None:
        super().__init__(coordinator, entry, "solar_storage_value")
        self._attr_translation_key = "solar_storage_value"
        self._currency = currency
        self._attr_native_unit_of_measurement = _price_unit(currency)

    @property
    def _opportunity(self) -> SolarStorageOpportunity | None:
        settings = self.coordinator.settings
        return best_solar_storage(
            self.coordinator.data.periods,
            settings.optimization_duration_minutes // 15,
            settings.battery_round_trip_efficiency,
            now=dt_util.utcnow(),
        )

    @property
    def native_value(self) -> Decimal | None:
        opportunity = self._opportunity
        if opportunity is None:
            return None
        return _display_price(opportunity.value_per_kwh, self._currency)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        opportunity = self._opportunity
        if opportunity is None:
            return None
        return {
            "current_export_price": str(
                _display_price(opportunity.current_period.export_price, self._currency)
            ),
            "future_import_price": str(
                _display_price(opportunity.discharge_window.average_import_price, self._currency)
            ),
            "best_use_start": opportunity.discharge_window.start.isoformat(),
            "best_use_end": opportunity.discharge_window.end.isoformat(),
            "duration_minutes": self.coordinator.settings.optimization_duration_minutes,
            "round_trip_efficiency": str(self.coordinator.settings.battery_round_trip_efficiency),
            "worth_storing": opportunity.value_per_kwh > 0,
            "price_unit": _price_unit(self._currency),
        }


def _battery_energy_plan(coordinator: DutchEnergyPricesCoordinator) -> BatteryEnergyPlan | None:
    settings = coordinator.settings
    return best_battery_energy_plan(
        coordinator.data.periods,
        settings.battery_target_energy_kwh,
        settings.max_charge_power_kw,
        settings.max_discharge_power_kw,
        settings.battery_round_trip_efficiency,
        not_before=dt_util.utcnow(),
    )


class DutchBatteryPlanWindowSensor(DutchEnergyBaseSensor):
    """Show a feasible power-limited charge or discharge window."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        kind: Literal["charge", "discharge"],
    ) -> None:
        key = f"battery_plan_{kind}_start"
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._kind = kind

    @property
    def native_value(self) -> datetime | None:
        plan = _battery_energy_plan(self.coordinator)
        if plan is None:
            return None
        return (plan.charge_window if self._kind == "charge" else plan.discharge_window).start

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = _battery_energy_plan(self.coordinator)
        if plan is None:
            return None
        window = plan.charge_window if self._kind == "charge" else plan.discharge_window
        allocation = plan.charge_slot_kwh if self._kind == "charge" else plan.discharge_slot_kwh
        return {
            "end": window.end.isoformat(),
            "energy_kwh": str(
                plan.grid_energy_kwh if self._kind == "charge" else plan.delivered_energy_kwh
            ),
            "max_power_kw": str(
                self.coordinator.settings.max_charge_power_kw
                if self._kind == "charge"
                else self.coordinator.settings.max_discharge_power_kw
            ),
            "slots": [
                {
                    "start": period.start.isoformat(),
                    "energy_kwh": str(amount),
                    "power_kw": str(amount * 4),
                }
                for period, amount in zip(window.periods, allocation, strict=True)
            ],
        }


class DutchBatteryPlanValueSensor(DutchEnergyBaseSensor):
    """Show estimated EUR savings for the entire planned energy transfer."""

    _attr_native_unit_of_measurement = "€"
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: DutchEnergyPricesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "battery_plan_value")
        self._attr_translation_key = "battery_plan_value"

    @property
    def native_value(self) -> Decimal | None:
        plan = _battery_energy_plan(self.coordinator)
        return plan.net_value_eur if plan is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = _battery_energy_plan(self.coordinator)
        if plan is None:
            return None
        return {
            "grid_energy_kwh": str(plan.grid_energy_kwh),
            "delivered_energy_kwh": str(plan.delivered_energy_kwh),
            "charge_cost_eur": str(plan.charge_cost_eur),
            "avoided_import_eur": str(plan.avoided_import_eur),
            "charge_start": plan.charge_window.start.isoformat(),
            "discharge_start": plan.discharge_window.start.isoformat(),
            "profitable": plan.net_value_eur > 0,
            "assumes_full_household_use": True,
        }


def _rolling_recommendation(coordinator: DutchEnergyPricesCoordinator) -> RollingDecision | None:
    """Use configured live telemetry only when units and states are valid."""
    soc = coordinator.hass.states.get(coordinator.soc_entity_id)
    load = coordinator.hass.states.get(coordinator.load_entity_id)
    if soc is None or load is None:
        return None
    try:
        if soc.attributes.get("unit_of_measurement") not in (None, "%"):
            return None
        percentage = Decimal(soc.state)
        watts = Decimal(load.state)
        unit = load.attributes.get("unit_of_measurement")
        if unit == "W":
            load_kw = watts / Decimal("1000")
        elif unit == "kW":
            load_kw = watts
        else:
            return None
        if not percentage.is_finite() or not load_kw.is_finite():
            return None
    except InvalidOperation:
        return None
    return rolling_decision(
        coordinator.data.periods,
        dt_util.utcnow(),
        percentage,
        load_kw,
        coordinator.settings,
    )


class DutchRollingActionSensor(DutchEnergyBaseSensor):
    """Expose the suggested action for the current slot without controlling devices."""

    def __init__(self, coordinator: DutchEnergyPricesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "battery_rolling_action")
        self._attr_translation_key = "battery_rolling_action"
        self._stabilizer = ActionStabilizer(
            confirmations=coordinator.settings.action_confirmation_updates,
            minimum_dwell=timedelta(minutes=coordinator.settings.minimum_action_minutes),
        )
        self._last_plan: OptimizedEnergyPlan | None = None
        self._last_slot: PlannedEnergySlot | None = None
        self._last_proposal_signature: tuple[int, datetime | None, str] | None = None

    def _evaluate(self) -> tuple[OptimizedEnergyPlan | None, PlannedEnergySlot | None]:
        plan = self.coordinator.optimized_plan()
        now = dt_util.utcnow()
        slot = (
            next((item for item in plan.slots if item.start <= now < item.end), None)
            if plan is not None
            else None
        )
        proposed = slot.action if slot is not None else "hold"
        signature = (id(plan), slot.start if slot else None, proposed)
        if signature != self._last_proposal_signature:
            self._stabilizer.update(proposed, now)
            self._last_proposal_signature = signature
        self._last_plan = plan
        self._last_slot = slot
        return plan, slot

    @property
    def native_value(self) -> str | None:
        self._evaluate()
        return self._stabilizer.action

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan, slot = self._evaluate()
        battery = self.coordinator.battery_snapshot()
        if plan is None or battery is None:
            return None
        remaining_hours = (
            Decimal(str((slot.end - dt_util.utcnow()).total_seconds())) / Decimal("3600")
            if slot is not None
            else Decimal("0")
        )
        energy = (
            slot.grid_charge_kwh
            + slot.solar_charge_kwh
            + slot.self_discharge_kwh
            + slot.export_discharge_kwh
            if slot is not None
            else Decimal("0")
        )
        next_charge = next(
            (
                item.start
                for item in plan.slots
                if item.start > dt_util.utcnow() and item.action == "charge"
            ),
            None,
        )
        return {
            "reason": plan.reason,
            "raw_action": slot.action if slot else "hold",
            "action_changed_at": (
                self._stabilizer.action_since.isoformat() if self._stabilizer.action_since else None
            ),
            "pending_action": self._stabilizer.candidate,
            "pending_confirmations": self._stabilizer.candidate_updates,
            "reserve_kwh": str(plan.reserve_kwh),
            "stored_energy_kwh": str(battery.stored_energy_kwh),
            "available_to_discharge_kwh": str(
                max(Decimal("0"), battery.stored_energy_kwh - plan.reserve_kwh)
            ),
            "next_charge_start": next_charge.isoformat() if next_charge else None,
            "recommended_power_kw": str(energy / remaining_hours if remaining_hours > 0 else 0),
            "energy_this_slot_kwh": str(energy),
            "estimated_value_this_slot_eur": str(slot.value_eur if slot else 0),
            "forecast_aware": bool(self.coordinator.solar_forecast()),
            "bank_count": len(battery.banks),
        }


class DutchOptimizedPlanMetricSensor(DutchEnergyBaseSensor):
    """Expose compact totals from the full-horizon optimiser."""

    def __init__(
        self, coordinator: DutchEnergyPricesCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._key = key
        self._attr_suggested_display_precision = 3
        self._attr_native_unit_of_measurement = "€" if key == "optimized_plan_value" else "kWh"

    @property
    def native_value(self) -> Decimal | None:
        plan = self.coordinator.optimized_plan()
        if plan is None:
            return None
        return {
            "optimized_plan_value": plan.net_value_eur,
            "planned_grid_charge_energy": plan.grid_charge_kwh,
            "planned_solar_charge_energy": plan.solar_charge_kwh,
            "planned_discharge_energy": plan.self_discharge_kwh + plan.export_discharge_kwh,
            "battery_reserve_energy": plan.reserve_kwh,
        }[self._key]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        plan = self.coordinator.optimized_plan()
        if plan is None:
            return None
        return {
            "reason": plan.reason,
            "charge_cost_eur": str(plan.charge_cost_eur),
            "avoided_import_eur": str(plan.avoided_import_eur),
            "export_revenue_eur": str(plan.export_revenue_eur),
            "operating_cost_eur": str(plan.operating_cost_eur),
            "self_discharge_kwh": str(plan.self_discharge_kwh),
            "export_discharge_kwh": str(plan.export_discharge_kwh),
        }


class DutchOptimizedPlanTimeSensor(DutchEnergyBaseSensor):
    """Expose the next charge or discharge slot without a large schedule attribute."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        coordinator: DutchEnergyPricesCoordinator,
        entry: ConfigEntry,
        key: str,
        kind: Literal["charge", "discharge"],
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_translation_key = key
        self._kind = kind

    @property
    def _slot(self) -> PlannedEnergySlot | None:
        plan = self.coordinator.optimized_plan()
        if plan is None:
            return None
        if self._kind == "charge":
            return next(
                (slot for slot in plan.slots if slot.action in ("charge", "solar_charge")), None
            )
        return next((slot for slot in plan.slots if slot.action == "discharge"), None)

    @property
    def native_value(self) -> datetime | None:
        slot = self._slot
        return slot.start if slot else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        slot = self._slot
        if slot is None:
            return None
        return {
            "end": slot.end.isoformat(),
            "action": slot.action,
            "grid_charge_kwh": str(slot.grid_charge_kwh),
            "solar_charge_kwh": str(slot.solar_charge_kwh),
            "self_discharge_kwh": str(slot.self_discharge_kwh),
            "export_discharge_kwh": str(slot.export_discharge_kwh),
            "estimated_value_eur": str(slot.value_eur),
        }


class DutchFlexibleLoadSensor(DutchEnergyBaseSensor):
    """Recommend when flexible consumption can absorb live PV surplus."""

    def __init__(self, coordinator: DutchEnergyPricesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "flexible_load_action")
        self._attr_translation_key = "flexible_load_action"

    @property
    def native_value(self) -> str:
        pv = power_kw(self.coordinator.measurement(self.coordinator.pv_power_entity_id))
        load = self.coordinator.household_load_kw()
        surplus = max(Decimal("0"), (pv or Decimal("0")) - load)
        current = current_period(self.coordinator.data.periods, dt_util.utcnow())
        if surplus >= Decimal("0.1") and current is not None and current.export_price <= 0:
            return "run_now"
        if surplus >= Decimal("0.1"):
            return "solar_available"
        return "delay"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pv = power_kw(self.coordinator.measurement(self.coordinator.pv_power_entity_id)) or Decimal(
            "0"
        )
        load = self.coordinator.household_load_kw()
        return {
            "pv_power_kw": str(pv),
            "household_load_kw": str(load),
            "estimated_surplus_kw": str(max(Decimal("0"), pv - load)),
        }


class DutchControlStatusSensor(DutchEnergyBaseSensor):
    """Make optional controller state and its last bounded command visible."""

    def __init__(self, coordinator: DutchEnergyPricesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "battery_control_status")
        self._attr_translation_key = "battery_control_status"

    @property
    def native_value(self) -> str:
        return self.coordinator.controller.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        command = self.coordinator.controller.last_command
        if command is None:
            return {"last_command": None}
        return {
            "last_command": command.action,
            "requested_power_kw": str(command.power_kw),
            "reason": command.reason,
            "dry_run": self.coordinator.controller.dry_run,
        }
