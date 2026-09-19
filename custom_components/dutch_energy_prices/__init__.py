"""Dutch Energy Prices integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import PLATFORMS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dutch Energy Prices from a config entry."""
    from .coordinator import DutchEnergyPricesCoordinator, settings_from_config
    from .providers import create_provider

    config = {**entry.data, **entry.options}
    coordinator = DutchEnergyPricesCoordinator(
        hass, entry, create_provider(hass, config), settings_from_config(config)
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
