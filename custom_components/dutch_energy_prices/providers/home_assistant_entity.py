"""Consume 15-minute prices exposed by another Home Assistant entity."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..const import SourcePriceUnit
from ..models import MarketPricePeriod
from .base import PriceProvider, PriceProviderError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class HomeAssistantEntityPriceProvider(PriceProvider):
    """Read a documented list format from an existing entity's attributes."""

    name = "Home Assistant entity"

    def __init__(self, hass: HomeAssistant, entity_id: str, unit: SourcePriceUnit) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._unit = unit

    async def async_get_prices(self) -> tuple[MarketPricePeriod, ...]:
        state = self._hass.states.get(self._entity_id)
        if state is None:
            raise PriceProviderError(f"Source entity {self._entity_id} does not exist")

        values: list[Any] = []
        if isinstance(state.attributes.get("prices"), list):
            values.extend(state.attributes["prices"])
        else:
            for key in ("today", "tomorrow"):
                if isinstance(state.attributes.get(key), list):
                    values.extend(state.attributes[key])
        if not values:
            raise PriceProviderError(
                "Source entity must expose a prices list or today/tomorrow lists"
            )

        periods = tuple(self._parse_item(item) for item in values)
        return tuple(sorted(set(periods), key=lambda period: period.start))

    def _parse_item(self, item: Any) -> MarketPricePeriod:
        if not isinstance(item, dict):
            raise PriceProviderError("Every source price item must be an object")
        start_value = item.get("start", item.get("datetime", item.get("time")))
        price_value = item.get("market_price", item.get("price", item.get("value")))
        start = dt_util.parse_datetime(str(start_value)) if start_value is not None else None
        if start is None or start.tzinfo is None:
            raise PriceProviderError("Every source period needs a timezone-aware start")
        end_value = item.get("end")
        end = (
            dt_util.parse_datetime(str(end_value))
            if end_value is not None
            else start + timedelta(minutes=15)
        )
        if end is None or end.tzinfo is None:
            raise PriceProviderError("Every source period needs a timezone-aware end")
        try:
            price = Decimal(str(price_value))
        except (InvalidOperation, TypeError) as err:
            raise PriceProviderError("Every source period needs a numeric price") from err
        if self._unit is SourcePriceUnit.EUR_PER_MWH:
            price /= Decimal("1000")
        try:
            return MarketPricePeriod(start, end, price)
        except ValueError as err:
            raise PriceProviderError(str(err)) from err
