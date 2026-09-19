"""Price-provider factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..const import (
    CONF_PRICE_SOURCE,
    CONF_SOURCE_ENTITY,
    CONF_SOURCE_PRICE_UNIT,
    PriceSource,
    SourcePriceUnit,
)
from .base import PriceProvider
from .home_assistant_entity import HomeAssistantEntityPriceProvider

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def create_provider(hass: HomeAssistant, config: dict[str, Any]) -> PriceProvider:
    """Create the configured provider without leaking it into price logic."""
    source = PriceSource(config[CONF_PRICE_SOURCE])
    if source is PriceSource.HOME_ASSISTANT_ENTITY:
        return HomeAssistantEntityPriceProvider(
            hass,
            config[CONF_SOURCE_ENTITY],
            SourcePriceUnit(config[CONF_SOURCE_PRICE_UNIT]),
        )
    raise ValueError(f"Unsupported price source: {source}")
