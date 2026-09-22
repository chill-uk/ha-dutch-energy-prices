"""Dutch Energy Prices integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import PLATFORMS

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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
