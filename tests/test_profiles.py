"""Tests for applying editable Netherlands tax profiles."""

from custom_components.dutch_energy_prices.const import (
    CONF_ENERGY_TAX,
    CONF_TAX_PROFILE,
    CONF_VAT_PERCENTAGE,
    TAX_PROFILE_DEFAULTS,
    TaxProfile,
    values_for_profile,
)


def test_same_profile_preserves_user_tax_overrides() -> None:
    current = {
        CONF_TAX_PROFILE: TaxProfile.NETHERLANDS_2026.value,
        CONF_ENERGY_TAX: 0.1234,
        CONF_VAT_PERCENTAGE: 9.0,
        "supplier_import_markup": 0.025,
    }

    assert values_for_profile(TaxProfile.NETHERLANDS_2026, current) == current


def test_changed_profile_loads_editable_defaults_without_changing_markup() -> None:
    current = {
        CONF_TAX_PROFILE: TaxProfile.CUSTOM.value,
        CONF_ENERGY_TAX: 0.25,
        CONF_VAT_PERCENTAGE: 9.0,
        "supplier_import_markup": 0.025,
    }

    result = values_for_profile(TaxProfile.NETHERLANDS_2027, current)

    assert result[CONF_ENERGY_TAX] == float(
        TAX_PROFILE_DEFAULTS[TaxProfile.NETHERLANDS_2027][CONF_ENERGY_TAX]
    )
    assert result[CONF_VAT_PERCENTAGE] == 21.0
    assert result["supplier_import_markup"] == 0.025
    assert current[CONF_ENERGY_TAX] == 0.25


def test_custom_profile_defaults_are_editable_from_zero() -> None:
    current = {
        CONF_TAX_PROFILE: TaxProfile.NETHERLANDS_2026.value,
        CONF_ENERGY_TAX: 0.09161,
        CONF_VAT_PERCENTAGE: 21.0,
    }

    result = values_for_profile(TaxProfile.CUSTOM, current)

    assert result[CONF_ENERGY_TAX] == 0.0
