"""Sensor platform for Dutch Energy Prices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

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

from .calculations import cheapest_window, current_period
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
from .models import PricePeriod


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
    async_add_entities(
        [
            DutchCurrentPriceSensor(
                coordinator,
                entry,
                replace(description, native_unit_of_measurement=unit),
                currency,
            )
            for description in SENSOR_DESCRIPTIONS
        ]
        + [
            DutchCheapestWindowSensor(coordinator, entry, "cheapest_slot", 1, currency),
            DutchCheapestWindowSensor(coordinator, entry, "cheapest_1h", 4, currency),
            DutchCheapestWindowSensor(coordinator, entry, "cheapest_2h", 8, currency),
        ]
    )


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
    def _window(self):
        return cheapest_window(
            self.coordinator.data.periods, self._slots, not_before=dt_util.utcnow()
        )

    @property
    def native_value(self):
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
