"""Test staged options-menu helpers without requiring Home Assistant."""

from custom_components.dutch_energy_prices.const import (
    CONF_BATTERY_SOC_ENTITIES,
    CONF_BATTERY_SOC_ENTITY,
    CONF_ENERGY_TAX,
    CONF_SOLAR_FORECAST_ENTITIES,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_TAX_PROFILE,
    CONF_VAT_PERCENTAGE,
    TaxProfile,
)
from custom_components.dutch_energy_prices.options import (
    OPTIONS_MENU_STEPS,
    prepare_staged_options,
    select_tax_profile,
    update_staged_category,
)


def test_options_menu_exposes_focused_categories_and_explicit_save() -> None:
    assert OPTIONS_MENU_STEPS == (
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


def test_prepare_staged_options_preserves_data_and_migrates_legacy_entities() -> None:
    data = {
        "price_source": "entsoe",
        CONF_BATTERY_SOC_ENTITY: "sensor.battery_level",
        CONF_SOLAR_FORECAST_ENTITY: "sensor.solcast",
    }
    options = {"minimum_profit": 0.03}

    staged = prepare_staged_options(data, options)

    assert staged["price_source"] == "entsoe"
    assert staged["minimum_profit"] == 0.03
    assert staged[CONF_BATTERY_SOC_ENTITIES] == ["sensor.battery_level"]
    assert staged[CONF_SOLAR_FORECAST_ENTITIES] == ["sensor.solcast"]
    staged["minimum_profit"] = 0.04
    assert options["minimum_profit"] == 0.03


def test_select_tax_profile_loads_defaults_only_when_profile_changes() -> None:
    custom_values = {
        CONF_TAX_PROFILE: TaxProfile.CUSTOM.value,
        CONF_VAT_PERCENTAGE: 9,
        CONF_ENERGY_TAX: 0.04,
        "unrelated": "preserved",
    }

    unchanged = select_tax_profile(custom_values, TaxProfile.CUSTOM)
    assert unchanged[CONF_VAT_PERCENTAGE] == 9
    assert unchanged[CONF_ENERGY_TAX] == 0.04

    changed = select_tax_profile(custom_values, TaxProfile.NETHERLANDS_2027)
    assert changed[CONF_TAX_PROFILE] == TaxProfile.NETHERLANDS_2027.value
    assert changed[CONF_VAT_PERCENTAGE] == 21
    assert changed[CONF_ENERGY_TAX] == 0.09161
    assert changed["unrelated"] == "preserved"


def test_update_staged_category_removes_cleared_optional_values() -> None:
    values = {
        "required": 1,
        "optional_entity": "sensor.old",
        "unrelated": "preserved",
    }

    updated = update_staged_category(
        values,
        {"required": 2},
        ("optional_entity",),
    )

    assert updated == {"required": 2, "unrelated": "preserved"}
    assert values["optional_entity"] == "sensor.old"
