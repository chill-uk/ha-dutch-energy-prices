"""Tests for provider-neutral solar forecast parsing."""

from decimal import Decimal

from custom_components.dutch_energy_prices.forecast import (
    combine_solar_forecasts,
    normalize_solar_forecast,
)


def test_solcast_half_hour_kw_is_split_into_quarter_hours() -> None:
    forecast = normalize_solar_forecast(
        [
            {"period_start": "2027-06-01T10:00:00+00:00", "pv_estimate": 4},
            {"period_start": "2027-06-01T10:30:00+00:00", "pv_estimate": 2},
        ]
    )

    assert len(forecast) == 4
    assert forecast[0].solar_kwh == Decimal("1")
    assert forecast[1].solar_kwh == Decimal("1")
    assert forecast[2].solar_kwh == Decimal("0.5")


def test_invalid_or_naive_forecast_entries_are_ignored() -> None:
    assert normalize_solar_forecast([{"period_start": "2027-01-01", "pv_estimate": 1}]) == ()


def test_multiple_forecasts_can_use_conservative_or_average_values() -> None:
    low = normalize_solar_forecast(
        [{"period_start": "2027-06-01T10:00:00+00:00", "pv_estimate": 2}]
    )
    high = normalize_solar_forecast(
        [{"period_start": "2027-06-01T10:00:00+00:00", "pv_estimate": 4}]
    )

    conservative = combine_solar_forecasts((low, high), "conservative")
    average = combine_solar_forecasts((low, high), "average")
    assert conservative[0].solar_kwh == Decimal("0.5")
    assert average[0].solar_kwh == Decimal("0.75")
