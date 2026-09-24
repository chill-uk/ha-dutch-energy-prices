"""Data coordinator for Dutch Energy Prices."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .calculations import calculate_periods
from .const import DOMAIN, UPDATE_INTERVAL_MINUTES
from .forecast import combine_solar_forecasts, find_forecast_items, normalize_solar_forecast
from .models import (
    BatterySnapshot,
    EnergyForecastPeriod,
    OptimizedEnergyPlan,
    PriceData,
    PriceSettings,
)
from .optimizer import optimize_energy_plan
from .providers.base import PriceProvider, PriceProviderError
from .telemetry import Measurement, build_battery_snapshot, power_kw

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
        from .const import (
            CONF_BATTERY_CAPACITY_ENTITIES,
            CONF_BATTERY_POWER_ENTITIES,
            CONF_BATTERY_SOC_ENTITIES,
            CONF_BATTERY_SOC_ENTITY,
            CONF_BATTERY_SOH_ENTITIES,
            CONF_BATTERY_STORED_ENERGY_ENTITIES,
            CONF_GRID_POWER_ENTITY,
            CONF_HOUSEHOLD_LOAD_ENTITY,
            CONF_PV_POWER_ENTITY,
            CONF_SOLAR_FORECAST_ATTRIBUTE,
            CONF_SOLAR_FORECAST_ENTITIES,
            CONF_SOLAR_FORECAST_ENTITY,
            CONF_SOLAR_FORECAST_STRATEGY,
            SolarForecastStrategy,
        )

        config = {**entry.data, **entry.options}
        self.soc_entity_ids = _entity_ids(
            config.get(CONF_BATTERY_SOC_ENTITIES) or config.get(CONF_BATTERY_SOC_ENTITY)
        )
        self.soc_entity_id: str | None = self.soc_entity_ids[0] if self.soc_entity_ids else None
        self.capacity_entity_ids = _entity_ids(config.get(CONF_BATTERY_CAPACITY_ENTITIES))
        self.soh_entity_ids = _entity_ids(config.get(CONF_BATTERY_SOH_ENTITIES))
        self.stored_energy_entity_ids = _entity_ids(config.get(CONF_BATTERY_STORED_ENERGY_ENTITIES))
        self.battery_power_entity_ids = _entity_ids(config.get(CONF_BATTERY_POWER_ENTITIES))
        self.load_entity_id: str | None = config.get(CONF_HOUSEHOLD_LOAD_ENTITY)
        self.grid_power_entity_id: str | None = config.get(CONF_GRID_POWER_ENTITY)
        self.pv_power_entity_id: str | None = config.get(CONF_PV_POWER_ENTITY)
        self.solar_forecast_entity_ids = _entity_ids(
            config.get(CONF_SOLAR_FORECAST_ENTITIES) or config.get(CONF_SOLAR_FORECAST_ENTITY)
        )
        self.solar_forecast_entity_id: str | None = (
            self.solar_forecast_entity_ids[0] if self.solar_forecast_entity_ids else None
        )
        self.solar_forecast_attribute = str(config.get(CONF_SOLAR_FORECAST_ATTRIBUTE, ""))
        self.solar_forecast_strategy = SolarForecastStrategy(
            config.get(CONF_SOLAR_FORECAST_STRATEGY, SolarForecastStrategy.CONSERVATIVE)
        )
        self._last_measurements: dict[str, tuple[object, Measurement]] = {}
        self._plan_cache_key: object = None
        self._plan_cache: OptimizedEnergyPlan | None = None

    @property
    def telemetry_entity_ids(self) -> tuple[str, ...]:
        """Return every configured entity that can change planning output."""
        return tuple(
            item
            for item in dict.fromkeys(
                (
                    *self.soc_entity_ids,
                    *self.capacity_entity_ids,
                    *self.soh_entity_ids,
                    *self.stored_energy_entity_ids,
                    *self.battery_power_entity_ids,
                    self.load_entity_id,
                    self.grid_power_entity_id,
                    self.pv_power_entity_id,
                    *self.solar_forecast_entity_ids,
                )
            )
            if item
        )

    def measurement(self, entity_id: str | None) -> Measurement | None:
        """Return current telemetry, retaining a recent last-good measurement."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        now = dt_util.utcnow()
        if state is not None and state.state not in ("unknown", "unavailable", ""):
            measurement = Measurement(
                state.state,
                state.attributes.get("unit_of_measurement"),
                state.attributes.get("friendly_name", entity_id),
            )
            self._last_measurements[entity_id] = (now, measurement)
            return measurement
        cached = self._last_measurements.get(entity_id)
        if cached is None:
            return None
        cached_at, measurement = cached
        age = now - cached_at
        if age <= timedelta(minutes=self.settings.telemetry_stale_minutes):
            return measurement
        return None

    def battery_snapshot(self) -> BatterySnapshot | None:
        """Normalise all selected battery entities into one aggregate snapshot."""
        return build_battery_snapshot(
            tuple(self.measurement(item) for item in self.soc_entity_ids),
            configured_capacity_kwh=self.settings.battery_usable_capacity_kwh,
            capacities=tuple(self.measurement(item) for item in self.capacity_entity_ids),
            stored_energy=tuple(self.measurement(item) for item in self.stored_energy_entity_ids),
            state_of_health=tuple(self.measurement(item) for item in self.soh_entity_ids),
        )

    def household_load_kw(self) -> Decimal:
        """Return total household consumption, never net grid import."""
        return power_kw(self.measurement(self.load_entity_id)) or Decimal("0")

    def solar_forecast(self) -> tuple[EnergyForecastPeriod, ...]:
        """Read a supported forecast attribute without coupling to its provider."""
        if not self.solar_forecast_entity_ids:
            return ()
        forecasts = []
        for entity_id in self.solar_forecast_entity_ids:
            state = self.hass.states.get(entity_id)
            if state is not None:
                forecast = normalize_solar_forecast(
                    find_forecast_items(state.attributes, self.solar_forecast_attribute)
                )
                if forecast:
                    forecasts.append(forecast)
        if not forecasts:
            return ()
        return combine_solar_forecasts(forecasts, self.solar_forecast_strategy.value)

    def optimized_plan(self) -> OptimizedEnergyPlan | None:
        """Return one cached plan shared by all optimiser sensors."""
        battery = self.battery_snapshot()
        if battery is None:
            return None
        forecast = self.solar_forecast()
        load = self.household_load_kw()
        now = dt_util.utcnow()
        minute_key = now.replace(second=0, microsecond=0)
        key = (self.data.fetched_at, minute_key, battery, forecast, load)
        if key != self._plan_cache_key:
            self._plan_cache = optimize_energy_plan(
                self.data.periods,
                battery,
                self.settings,
                now=now,
                forecasts=forecast,
                fallback_load_kw=load,
            )
            self._plan_cache_key = key
        return self._plan_cache

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
    from .const import (
        CONF_ACTION_CONFIRMATION_UPDATES,
        CONF_ALLOW_GRID_EXPORT,
        CONF_BATTERY_CHARGE_EFFICIENCY,
        CONF_BATTERY_DISCHARGE_EFFICIENCY,
        CONF_BATTERY_EFFICIENCY,
        CONF_BATTERY_MIN_RESERVE,
        CONF_BATTERY_OPERATING_COST,
        CONF_BATTERY_RESERVE_BUFFER,
        CONF_BATTERY_TARGET_ENERGY,
        CONF_BATTERY_USABLE_CAPACITY,
        CONF_ENERGY_TAX,
        CONF_MAX_CHARGE_POWER,
        CONF_MAX_DISCHARGE_POWER,
        CONF_MINIMUM_ACTION_MINUTES,
        CONF_MINIMUM_PROFIT,
        CONF_OPTIMIZATION_DURATION,
        CONF_SOLAR_CONFIDENCE,
        CONF_SUPPLIER_EXPORT_ADJUSTMENT,
        CONF_SUPPLIER_IMPORT_MARKUP,
        CONF_TELEMETRY_STALE_MINUTES,
        CONF_VAT_ENERGY_TAX,
        CONF_VAT_EXPORT_ADJUSTMENT,
        CONF_VAT_IMPORT_MARKUP,
        CONF_VAT_MARKET_EXPORT,
        CONF_VAT_MARKET_IMPORT,
        CONF_VAT_PERCENTAGE,
        DEFAULT_ACTION_CONFIRMATION_UPDATES,
        DEFAULT_BATTERY_CHARGE_EFFICIENCY,
        DEFAULT_BATTERY_MIN_RESERVE,
        DEFAULT_BATTERY_OPERATING_COST,
        DEFAULT_BATTERY_RESERVE_BUFFER,
        DEFAULT_BATTERY_TARGET_ENERGY,
        DEFAULT_BATTERY_USABLE_CAPACITY,
        DEFAULT_MAX_CHARGE_POWER,
        DEFAULT_MAX_DISCHARGE_POWER,
        DEFAULT_MINIMUM_ACTION_MINUTES,
        DEFAULT_MINIMUM_PROFIT,
        DEFAULT_OPTIMIZATION_DURATION_MINUTES,
        DEFAULT_SOLAR_CONFIDENCE,
        DEFAULT_TELEMETRY_STALE_MINUTES,
    )

    return PriceSettings(
        vat_percentage=Decimal(str(config[CONF_VAT_PERCENTAGE])),
        energy_tax=Decimal(str(config[CONF_ENERGY_TAX])),
        supplier_import_markup=Decimal(str(config[CONF_SUPPLIER_IMPORT_MARKUP])),
        supplier_export_adjustment=Decimal(str(config[CONF_SUPPLIER_EXPORT_ADJUSTMENT])),
        battery_round_trip_efficiency=Decimal(str(config[CONF_BATTERY_EFFICIENCY])),
        battery_charge_efficiency=Decimal(
            str(config.get(CONF_BATTERY_CHARGE_EFFICIENCY, DEFAULT_BATTERY_CHARGE_EFFICIENCY))
        ),
        battery_discharge_efficiency=(
            Decimal(str(config[CONF_BATTERY_DISCHARGE_EFFICIENCY]))
            if config.get(CONF_BATTERY_DISCHARGE_EFFICIENCY) not in (None, "")
            else None
        ),
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
        solar_confidence_percent=Decimal(
            str(config.get(CONF_SOLAR_CONFIDENCE, DEFAULT_SOLAR_CONFIDENCE))
        ),
        battery_operating_cost=Decimal(
            str(config.get(CONF_BATTERY_OPERATING_COST, DEFAULT_BATTERY_OPERATING_COST))
        ),
        minimum_profit=Decimal(str(config.get(CONF_MINIMUM_PROFIT, DEFAULT_MINIMUM_PROFIT))),
        allow_grid_export=bool(config.get(CONF_ALLOW_GRID_EXPORT, False)),
        action_confirmation_updates=int(
            config.get(CONF_ACTION_CONFIRMATION_UPDATES, DEFAULT_ACTION_CONFIRMATION_UPDATES)
        ),
        minimum_action_minutes=int(
            config.get(CONF_MINIMUM_ACTION_MINUTES, DEFAULT_MINIMUM_ACTION_MINUTES)
        ),
        telemetry_stale_minutes=int(
            config.get(CONF_TELEMETRY_STALE_MINUTES, DEFAULT_TELEMETRY_STALE_MINUTES)
        ),
        vat_market_import=bool(config[CONF_VAT_MARKET_IMPORT]),
        vat_import_markup=bool(config[CONF_VAT_IMPORT_MARKUP]),
        vat_energy_tax=bool(config[CONF_VAT_ENERGY_TAX]),
        vat_market_export=bool(config[CONF_VAT_MARKET_EXPORT]),
        vat_export_adjustment=bool(config[CONF_VAT_EXPORT_ADJUSTMENT]),
    )


def _entity_ids(value: Any) -> tuple[str, ...]:
    """Normalise legacy single and new multiple entity selectors."""
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()
