"""Provider abstraction for native Dutch market prices."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import MarketPricePeriod


class PriceProviderError(Exception):
    """Base provider error."""


class PriceProvider(ABC):
    """Interface implemented by all market-data providers."""

    name: str

    @abstractmethod
    async def async_get_prices(self) -> tuple[MarketPricePeriod, ...]:
        """Return timezone-aware, native 15-minute prices in EUR/kWh."""
