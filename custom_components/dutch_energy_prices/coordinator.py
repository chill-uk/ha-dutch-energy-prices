"""Data coordinator for Dutch Energy Prices."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .calculations import calculate_periods
from .const import DOMAIN, UPDATE_INTERVAL_MINUTES
from .models import PriceData, PriceSettings
from .providers.base import PriceProvider, PriceProviderError

_LOGGER = logging.getLogger(__name__)


class DutchEnergyPricesCoordinator(DataUpdateCoordinator[PriceData]):
    """Fetch raw data once and calculate all derived prices centrally."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: PriceProvider,
        settings: PriceSettings,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
            always_update=False,
        )
        self.provider = provider
        self.settings = settings
        from .const import CONF_BATTERY_SOC_ENTITY, CONF_HOUSEHOLD_LOAD_ENTITY

        config = {**entry.data, **entry.options}
        self.soc_entity_id: str | None = config.get(CONF_BATTERY_SOC_ENTITY)
        self.load_entity_id: str | None = config.get(CONF_HOUSEHOLD_LOAD_ENTITY)

    async def _async_update_data(self) -> PriceData:
        try:
            raw_periods = await self.provider.async_get_prices()
            periods = calculate_periods(raw_periods, self.settings)
        except (PriceProviderError, ValueError) as err:
            raise UpdateFailed(str(err)) from err
        return PriceData(
            periods=periods,
            fetched_at=dt_util.utcnow(),
            provider_name=self.provider.name,
        )


def settings_from_config(config: dict[str, Any]) -> PriceSettings:
    """Build precise settings from config-entry primitives."""
    from decimal import Decimal

    from .const import (
        CONF_BATTERY_EFFICIENCY,
        CONF_BATTERY_MIN_RESERVE,
        CONF_BATTERY_RESERVE_BUFFER,
        CONF_BATTERY_TARGET_ENERGY,
        CONF_BATTERY_USABLE_CAPACITY,
        CONF_ENERGY_TAX,
        CONF_MAX_CHARGE_POWER,
        CONF_MAX_DISCHARGE_POWER,
        CONF_OPTIMIZATION_DURATION,
        CONF_SUPPLIER_EXPORT_ADJUSTMENT,
        CONF_SUPPLIER_IMPORT_MARKUP,
        CONF_VAT_ENERGY_TAX,
        CONF_VAT_EXPORT_ADJUSTMENT,
        CONF_VAT_IMPORT_MARKUP,
        CONF_VAT_MARKET_EXPORT,
        CONF_VAT_MARKET_IMPORT,
        CONF_VAT_PERCENTAGE,
        DEFAULT_BATTERY_MIN_RESERVE,
        DEFAULT_BATTERY_RESERVE_BUFFER,
        DEFAULT_BATTERY_TARGET_ENERGY,
        DEFAULT_BATTERY_USABLE_CAPACITY,
        DEFAULT_MAX_CHARGE_POWER,
        DEFAULT_MAX_DISCHARGE_POWER,
        DEFAULT_OPTIMIZATION_DURATION_MINUTES,
    )

    return PriceSettings(
        vat_percentage=Decimal(str(config[CONF_VAT_PERCENTAGE])),
        energy_tax=Decimal(str(config[CONF_ENERGY_TAX])),
        supplier_import_markup=Decimal(str(config[CONF_SUPPLIER_IMPORT_MARKUP])),
        supplier_export_adjustment=Decimal(str(config[CONF_SUPPLIER_EXPORT_ADJUSTMENT])),
        battery_round_trip_efficiency=Decimal(str(config[CONF_BATTERY_EFFICIENCY])),
        optimization_duration_minutes=int(
            config.get(CONF_OPTIMIZATION_DURATION, DEFAULT_OPTIMIZATION_DURATION_MINUTES)
        ),
        max_charge_power_kw=Decimal(
            str(config.get(CONF_MAX_CHARGE_POWER, DEFAULT_MAX_CHARGE_POWER))
        ),
        max_discharge_power_kw=Decimal(
            str(config.get(CONF_MAX_DISCHARGE_POWER, DEFAULT_MAX_DISCHARGE_POWER))
        ),
        battery_target_energy_kwh=Decimal(
            str(config.get(CONF_BATTERY_TARGET_ENERGY, DEFAULT_BATTERY_TARGET_ENERGY))
        ),
        battery_usable_capacity_kwh=Decimal(
            str(config.get(CONF_BATTERY_USABLE_CAPACITY, DEFAULT_BATTERY_USABLE_CAPACITY))
        ),
        battery_min_reserve_percent=Decimal(
            str(config.get(CONF_BATTERY_MIN_RESERVE, DEFAULT_BATTERY_MIN_RESERVE))
        ),
        battery_reserve_buffer_kwh=Decimal(
            str(config.get(CONF_BATTERY_RESERVE_BUFFER, DEFAULT_BATTERY_RESERVE_BUFFER))
        ),
        vat_market_import=bool(config[CONF_VAT_MARKET_IMPORT]),
        vat_import_markup=bool(config[CONF_VAT_IMPORT_MARKUP]),
        vat_energy_tax=bool(config[CONF_VAT_ENERGY_TAX]),
        vat_market_export=bool(config[CONF_VAT_MARKET_EXPORT]),
        vat_export_adjustment=bool(config[CONF_VAT_EXPORT_ADJUSTMENT]),
    )
