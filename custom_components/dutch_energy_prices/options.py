"""Pure helpers for the staged options menu."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_BATTERY_SOC_ENTITIES,
    CONF_BATTERY_SOC_ENTITY,
    CONF_SOLAR_FORECAST_ENTITIES,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_TAX_PROFILE,
    TaxProfile,
    values_for_profile,
)

OPTIONS_MENU_STEPS = (
    "price_source",
    "taxes",
    "vat_rules",
    "battery",
    "battery_entities",
    "solar",
    "optimization",
    "control",
    "save",
)


def normalise_legacy_options(values: Mapping[str, Any]) -> dict[str, Any]:
    """Convert legacy single-entity settings to current list settings."""
    normalised = dict(values)
    if not normalised.get(CONF_BATTERY_SOC_ENTITIES) and normalised.get(CONF_BATTERY_SOC_ENTITY):
        normalised[CONF_BATTERY_SOC_ENTITIES] = [normalised[CONF_BATTERY_SOC_ENTITY]]
    if not normalised.get(CONF_SOLAR_FORECAST_ENTITIES) and normalised.get(
        CONF_SOLAR_FORECAST_ENTITY
    ):
        normalised[CONF_SOLAR_FORECAST_ENTITIES] = [normalised[CONF_SOLAR_FORECAST_ENTITY]]
    return normalised


def prepare_staged_options(data: Mapping[str, Any], options: Mapping[str, Any]) -> dict[str, Any]:
    """Merge persisted values into a detached working copy."""
    return normalise_legacy_options({**data, **options})


def update_staged_category(
    values: Mapping[str, Any],
    user_input: Mapping[str, Any],
    clearable_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Update one category, removing optional values cleared in the form."""
    updated = dict(values)
    for key in clearable_keys:
        if key not in user_input:
            updated.pop(key, None)
    updated.update(user_input)
    return updated


def select_tax_profile(values: Mapping[str, Any], profile: TaxProfile) -> dict[str, Any]:
    """Select a profile and load defaults only when the profile changes."""
    current = dict(values)
    return {
        **values_for_profile(profile, current),
        CONF_TAX_PROFILE: profile.value,
    }
