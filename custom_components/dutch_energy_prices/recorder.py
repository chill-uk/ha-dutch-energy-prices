"""Recorder migrations for Dutch Energy Prices."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CURRENCY_DISPLAY,
    CURRENCY_UNITS,
    DOMAIN,
    PRICE_SENSOR_KEYS,
    CurrencyDisplay,
)


@callback
def async_custom_equivalent_units(
    hass: HomeAssistant,
) -> dict[str, dict[str | None, str]]:
    """Map legacy unitless price statistics to their configured price unit."""
    registry = er.async_get(hass)
    equivalent_units: dict[str, dict[str | None, str]] = {}

    for config_entry in hass.config_entries.async_entries(DOMAIN):
        config = {**config_entry.data, **config_entry.options}
        currency = CurrencyDisplay(config[CONF_CURRENCY_DISPLAY])
        unit = CURRENCY_UNITS[currency]
        price_unique_ids = {f"{config_entry.entry_id}_{key}" for key in PRICE_SENSOR_KEYS}

        for entity_entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
            if entity_entry.domain != "sensor":
                continue
            if entity_entry.unique_id not in price_unique_ids:
                continue
            equivalent_units[entity_entry.entity_id] = {None: unit, "": unit}

    return equivalent_units
