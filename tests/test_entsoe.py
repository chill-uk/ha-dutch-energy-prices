"""Tests for the native ENTSO-E day-ahead provider."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from custom_components.dutch_energy_prices.providers.base import PriceProviderError
from custom_components.dutch_energy_prices.providers.entsoe import (
    API_URL,
    EntsoePriceProvider,
    _query_interval,
    parse_price_document,
)

PRICE_DOCUMENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <TimeSeries>
    <currency_Unit.name>EUR</currency_Unit.name>
    <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
    <Period>
      <timeInterval>
        <start>2027-01-10T00:00Z</start>
        <end>2027-01-10T01:00Z</end>
      </timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><price.amount>63.20</price.amount></Point>
      <Point><position>2</position><price.amount>-10.50</price.amount></Point>
      <Point><position>3</position><price.amount>0</price.amount></Point>
      <Point><position>4</position><price.amount>100.123</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""


class FakeResponse:
    """Minimal aiohttp response context manager."""

    charset = "utf-8"

    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode()
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def read(self) -> bytes:
        return self._body


class FakeSession:
    """Record the ENTSO-E request and return a fixture."""

    def __init__(self, body: str, status: int = 200) -> None:
        self.response = FakeResponse(body, status)
        self.url = ""
        self.params: dict[str, str] = {}

    def get(self, url: str, *, params: dict[str, str]) -> FakeResponse:
        self.url = url
        self.params = params
        return self.response


def test_parse_native_quarter_hour_prices() -> None:
    periods = parse_price_document(PRICE_DOCUMENT)

    assert len(periods) == 4
    assert periods[0].start == datetime(2027, 1, 10, tzinfo=UTC)
    assert periods[0].market_price == Decimal("0.06320")
    assert periods[1].market_price == Decimal("-0.0105")
    assert periods[-1].market_price == Decimal("0.100123")


def test_rejects_hourly_response() -> None:
    hourly = PRICE_DOCUMENT.replace("PT15M", "PT60M")

    with pytest.raises(PriceProviderError, match="instead of PT15M"):
        parse_price_document(hourly)


def test_surfaces_entsoe_acknowledgement() -> None:
    acknowledgement = """\
    <Acknowledgement_MarketDocument
      xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:8:1">
      <Reason><code>999</code><text>No matching data found</text></Reason>
    </Acknowledgement_MarketDocument>
    """

    with pytest.raises(PriceProviderError, match="No matching data found"):
        parse_price_document(acknowledgement)


@pytest.mark.parametrize(
    ("now", "expected_hours"),
    [
        (datetime(2027, 3, 28, 12, tzinfo=UTC), 47),
        (datetime(2027, 10, 31, 12, tzinfo=UTC), 49),
    ],
)
def test_query_interval_respects_dutch_dst(now: datetime, expected_hours: int) -> None:
    start, end = _query_interval(now)

    assert (end - start).total_seconds() == expected_hours * 3600


def test_provider_queries_the_netherlands_for_today_and_tomorrow() -> None:
    session = FakeSession(PRICE_DOCUMENT)
    provider = EntsoePriceProvider(
        None,  # type: ignore[arg-type]
        "secret-token",
        session=session,  # type: ignore[arg-type]
        now=lambda: datetime(2027, 1, 10, 12, tzinfo=UTC),
    )

    periods = asyncio.run(provider.async_get_prices())

    assert len(periods) == 4
    assert session.url == API_URL
    assert session.params == {
        "securityToken": "secret-token",
        "documentType": "A44",
        "in_Domain": "10YNL----------L",
        "out_Domain": "10YNL----------L",
        "periodStart": "202701092300",
        "periodEnd": "202701112300",
    }


def test_provider_reports_rejected_token_without_exposing_it() -> None:
    session = FakeSession("not authorised", status=401)
    provider = EntsoePriceProvider(
        None,  # type: ignore[arg-type]
        "super-secret",
        session=session,  # type: ignore[arg-type]
    )

    with pytest.raises(PriceProviderError, match="rejected the API token") as error:
        asyncio.run(provider.async_get_prices())

    assert "super-secret" not in str(error.value)
