"""Diagnostics support for Dutch Energy Prices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTSOE_API_TOKEN
from .coordinator import DutchEnergyPricesCoordinator

TO_REDACT = {CONF_ENTSOE_API_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return compact diagnostics without duplicating all price attributes."""
    coordinator: DutchEnergyPricesCoordinator = entry.runtime_data
    periods = coordinator.data.periods
    return {
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "provider": coordinator.data.provider_name,
        "last_update_success": coordinator.last_update_success,
        "fetched_at": coordinator.data.fetched_at.isoformat(),
        "period_count": len(periods),
        "first_period": periods[0].start.isoformat() if periods else None,
        "last_period": periods[-1].end.isoformat() if periods else None,
    }
