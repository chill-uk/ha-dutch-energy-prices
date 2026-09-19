"""Fetch native Dutch day-ahead prices from the ENTSO-E Transparency API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from aiohttp import ClientError

from ..models import MarketPricePeriod
from .base import PriceProvider, PriceProviderError

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from homeassistant.core import HomeAssistant

API_URL = "https://web-api.tp.entsoe.eu/api"
DOCUMENT_TYPE_DAY_AHEAD_PRICES = "A44"
NETHERLANDS_BIDDING_ZONE = "10YNL----------L"
NETHERLANDS_TIME_ZONE = ZoneInfo("Europe/Amsterdam")
REQUEST_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
EUR_PER_MWH_TO_EUR_PER_KWH = Decimal("1000")


class EntsoePriceProvider(PriceProvider):
    """Retrieve Dutch day-ahead prices directly from ENTSO-E."""

    name = "ENTSO-E"

    def __init__(
        self,
        hass: HomeAssistant,
        api_token: str,
        *,
        session: ClientSession | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if session is None:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            session = async_get_clientsession(hass)
        self._session = session
        self._api_token = api_token
        self._now = now or (lambda: datetime.now(UTC))

    async def async_get_prices(self) -> tuple[MarketPricePeriod, ...]:
        period_start, period_end = _query_interval(self._now())
        params = {
            "securityToken": self._api_token,
            "documentType": DOCUMENT_TYPE_DAY_AHEAD_PRICES,
            "in_Domain": NETHERLANDS_BIDDING_ZONE,
            "out_Domain": NETHERLANDS_BIDDING_ZONE,
            "periodStart": period_start.strftime("%Y%m%d%H%M"),
            "periodEnd": period_end.strftime("%Y%m%d%H%M"),
        }

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                async with self._session.get(API_URL, params=params) as response:
                    body = await response.read()
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise PriceProviderError("ENTSO-E response is unexpectedly large")
                    text = body.decode(response.charset or "utf-8", errors="replace")
                    if response.status in (401, 403):
                        raise PriceProviderError("ENTSO-E rejected the API token")
                    if response.status >= 400:
                        raise PriceProviderError(
                            _acknowledgement_reason(text)
                            or f"ENTSO-E request failed with HTTP {response.status}"
                        )
        except PriceProviderError:
            raise
        except TimeoutError as err:
            raise PriceProviderError("ENTSO-E request timed out") from err
        except (ClientError, UnicodeError) as err:
            raise PriceProviderError("Unable to retrieve prices from ENTSO-E") from err

        return parse_price_document(text)


def _query_interval(now: datetime) -> tuple[datetime, datetime]:
    """Return UTC boundaries for today and tomorrow in the Dutch timezone."""
    if now.tzinfo is None:
        raise ValueError("Current time must be timezone-aware")
    local_date = now.astimezone(NETHERLANDS_TIME_ZONE).date()
    start = datetime.combine(local_date, time.min, tzinfo=NETHERLANDS_TIME_ZONE)
    end = datetime.combine(local_date + timedelta(days=2), time.min, tzinfo=NETHERLANDS_TIME_ZONE)
    return start.astimezone(UTC), end.astimezone(UTC)


def parse_price_document(xml_text: str) -> tuple[MarketPricePeriod, ...]:
    """Parse an ENTSO-E day-ahead document into exact EUR/kWh periods."""
    if "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper():
        raise PriceProviderError("ENTSO-E response contains unsupported XML declarations")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as err:
        raise PriceProviderError("ENTSO-E returned malformed XML") from err

    reason = _reason_from_root(root)
    if _local_name(root.tag) == "Acknowledgement_MarketDocument":
        raise PriceProviderError(reason or "ENTSO-E rejected the request")

    by_start: dict[datetime, MarketPricePeriod] = {}
    for series in root.findall(".//{*}TimeSeries"):
        currency = _child_text(series, "currency_Unit.name")
        measure = _child_text(series, "price_Measure_Unit.name")
        if currency != "EUR" or measure != "MWH":
            raise PriceProviderError(
                f"Unsupported ENTSO-E price unit: {currency or '?'} per {measure or '?'}"
            )

        for period in series.findall("./{*}Period"):
            resolution = _child_text(period, "resolution")
            if resolution != "PT15M":
                raise PriceProviderError(
                    f"ENTSO-E returned {resolution or 'unknown'} data instead of PT15M"
                )
            period_start = _parse_datetime(
                _nested_text(period, "timeInterval", "start"), "period start"
            )
            period_end = _parse_datetime(_nested_text(period, "timeInterval", "end"), "period end")
            if period_end <= period_start:
                raise PriceProviderError("ENTSO-E returned an invalid period interval")

            for point in period.findall("./{*}Point"):
                try:
                    position = int(_child_text(point, "position"))
                    price = Decimal(_child_text(point, "price.amount"))
                except (InvalidOperation, TypeError, ValueError) as err:
                    raise PriceProviderError("ENTSO-E returned an invalid price point") from err
                if position < 1:
                    raise PriceProviderError("ENTSO-E returned an invalid point position")
                start = period_start + timedelta(minutes=15 * (position - 1))
                end = start + timedelta(minutes=15)
                if end > period_end:
                    raise PriceProviderError("ENTSO-E price point exceeds its period interval")
                item = MarketPricePeriod(start, end, price / EUR_PER_MWH_TO_EUR_PER_KWH)
                existing = by_start.get(start)
                if existing is not None and existing != item:
                    raise PriceProviderError("ENTSO-E returned conflicting prices for one period")
                by_start[start] = item

    if not by_start:
        raise PriceProviderError(reason or "ENTSO-E returned no Dutch day-ahead prices")
    return tuple(by_start[start] for start in sorted(by_start))


def _acknowledgement_reason(xml_text: str) -> str | None:
    try:
        return _reason_from_root(ElementTree.fromstring(xml_text))
    except ElementTree.ParseError:
        return None


def _reason_from_root(root: ElementTree.Element) -> str | None:
    value = root.findtext(".//{*}Reason/{*}text")
    return value.strip() if value and value.strip() else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str:
    value = element.findtext(f"./{{*}}{name}")
    if value is None or not value.strip():
        raise PriceProviderError(f"ENTSO-E response is missing {name}")
    return value.strip()


def _nested_text(element: ElementTree.Element, parent: str, child: str) -> str:
    value = element.findtext(f"./{{*}}{parent}/{{*}}{child}")
    if value is None or not value.strip():
        raise PriceProviderError(f"ENTSO-E response is missing {parent}/{child}")
    return value.strip()


def _parse_datetime(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise PriceProviderError(f"ENTSO-E returned an invalid {label}") from err
    if parsed.tzinfo is None:
        raise PriceProviderError(f"ENTSO-E returned a timezone-naive {label}")
    return parsed.astimezone(UTC)
