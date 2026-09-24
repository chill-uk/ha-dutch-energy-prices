"""Dutch Energy Prices integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import (
    CONF_BATTERY_SOC_ENTITIES,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CONTROL_ENABLED,
    CONF_SOLAR_FORECAST_ENTITIES,
    CONF_SOLAR_FORECAST_ENTITY,
    DOMAIN,
    PLATFORMS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dutch Energy Prices from a config entry."""
    from homeassistant.core import callback
    from homeassistant.helpers.event import (
        async_track_state_change_event,
        async_track_utc_time_change,
    )

    from .coordinator import DutchEnergyPricesCoordinator, settings_from_config
    from .providers import create_provider

    config = {**entry.data, **entry.options}
    coordinator = DutchEnergyPricesCoordinator(
        hass, entry, create_provider(hass, config), settings_from_config(config)
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    @callback
    def _on_price_boundary(_now: object) -> None:
        """Publish the next pre-fetched 15-minute price on time."""
        coordinator.async_update_listeners()

    entry.async_on_unload(
        async_track_utc_time_change(hass, _on_price_boundary, minute=range(0, 60, 15), second=0)
    )

    if hasattr(coordinator.provider, "source_entity_id"):

        @callback
        def _on_source_change(_event: Event) -> None:
            """Refresh immediately when the configured HA price entity changes."""
            hass.async_create_task(coordinator.async_request_refresh())

        entry.async_on_unload(
            async_track_state_change_event(
                hass, coordinator.provider.source_entity_id, _on_source_change
            )
        )

    telemetry_entities = getattr(
        coordinator,
        "telemetry_entity_ids",
        tuple(
            entity_id
            for entity_id in (coordinator.soc_entity_id, coordinator.load_entity_id)
            if entity_id
        ),
    )
    if telemetry_entities:

        @callback
        def _on_battery_telemetry_change(_event: Event) -> None:
            """Recalculate live battery guidance without fetching prices again."""
            coordinator.async_update_listeners()

        entry.async_on_unload(
            async_track_state_change_event(hass, telemetry_entities, _on_battery_telemetry_change)
        )

    coordinator.controller = None
    if config.get(CONF_CONTROL_ENABLED, False):
        from .controllers.generic import GenericBatteryController

        controller = GenericBatteryController(hass, coordinator, config)
        coordinator.controller = controller

        @callback
        def _on_control_update() -> None:
            hass.async_create_task(controller.async_update())

        entry.async_on_unload(coordinator.async_add_listener(_on_control_update))
        await controller.async_update()

    if hasattr(hass, "services"):
        from homeassistant.core import ServiceCall, SupportsResponse

        async def _get_plan(_call: ServiceCall) -> dict[str, object]:
            plan = coordinator.optimized_plan()
            if plan is None:
                return {"available": False, "slots": []}
            return {
                "available": True,
                "reason": plan.reason,
                "reserve_kwh": str(plan.reserve_kwh),
                "net_value_eur": str(plan.net_value_eur),
                "slots": [
                    {
                        "start": slot.start.isoformat(),
                        "end": slot.end.isoformat(),
                        "action": slot.action,
                        "grid_charge_kwh": str(slot.grid_charge_kwh),
                        "solar_charge_kwh": str(slot.solar_charge_kwh),
                        "self_discharge_kwh": str(slot.self_discharge_kwh),
                        "export_discharge_kwh": str(slot.export_discharge_kwh),
                        "value_eur": str(slot.value_eur),
                    }
                    for slot in plan.slots
                    if slot.action != "hold"
                ],
            }

        hass.services.async_register(
            DOMAIN,
            "get_plan",
            _get_plan,
            supports_response=SupportsResponse.ONLY,
        )
        entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, "get_plan"))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the legacy single battery sensor to the multi-bank schema."""
    if entry.version >= 2:
        return True
    data = dict(entry.data)
    options = dict(entry.options)
    legacy = options.get(CONF_BATTERY_SOC_ENTITY, data.get(CONF_BATTERY_SOC_ENTITY))
    if legacy and not options.get(CONF_BATTERY_SOC_ENTITIES):
        options[CONF_BATTERY_SOC_ENTITIES] = [legacy]
    legacy_forecast = options.get(CONF_SOLAR_FORECAST_ENTITY, data.get(CONF_SOLAR_FORECAST_ENTITY))
    if legacy_forecast and not options.get(CONF_SOLAR_FORECAST_ENTITIES):
        options[CONF_SOLAR_FORECAST_ENTITIES] = [legacy_forecast]
    hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
    return True
