"""Tests for serialisable price models."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.dutch_energy_prices.models import PricePeriod, PriceSettings


def test_period_attribute_shape() -> None:
    start = datetime(2027, 1, 10, 13, tzinfo=UTC)
    period = PricePeriod(
        start,
        start + timedelta(minutes=15),
        Decimal("0.0632"),
        Decimal("0.1803"),
        Decimal("0.0632"),
    )

    assert period.as_dict() == {
        "start": "2027-01-10T13:00:00+00:00",
        "end": "2027-01-10T13:15:00+00:00",
        "market_price": "0.0632",
        "import_price": "0.1803",
        "export_price": "0.0632",
        "import_vat": "0",
        "export_vat": "0",
    }


@pytest.mark.parametrize("duration", [0, 14, 16, 121])
def test_optimization_duration_requires_quarter_hour_increments(duration: int) -> None:
    with pytest.raises(ValueError, match="Optimisation duration"):
        PriceSettings(
            vat_percentage=Decimal("21"),
            energy_tax=Decimal("0.1"),
            supplier_import_markup=Decimal("0"),
            supplier_export_adjustment=Decimal("0"),
            optimization_duration_minutes=duration,
        )


@pytest.mark.parametrize(
    "field", ["max_charge_power_kw", "max_discharge_power_kw", "battery_target_energy_kwh"]
)
def test_battery_plan_settings_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        PriceSettings(
            vat_percentage=Decimal("21"),
            energy_tax=Decimal("0.1"),
            supplier_import_markup=Decimal("0"),
            supplier_export_adjustment=Decimal("0"),
            **{field: Decimal("0")},
        )
