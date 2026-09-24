"""Tests for device-independent control safety rules."""

from custom_components.dutch_energy_prices.controllers.base import controllable_action


def test_solar_charging_never_becomes_forced_grid_charging() -> None:
    assert controllable_action("solar_charge") == "hold"
    assert controllable_action("charge") == "charge"
    assert controllable_action("discharge") == "discharge"
    assert controllable_action("unknown") == "hold"
