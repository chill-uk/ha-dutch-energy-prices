"""Config flow for Dutch Energy Prices."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ACTION_CONFIRMATION_UPDATES,
    CONF_ALLOW_GRID_EXPORT,
    CONF_BATTERY_CAPACITY_ENTITIES,
    CONF_BATTERY_CHARGE_EFFICIENCY,
    CONF_BATTERY_DISCHARGE_EFFICIENCY,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_MIN_RESERVE,
    CONF_BATTERY_OPERATING_COST,
    CONF_BATTERY_POWER_ENTITIES,
    CONF_BATTERY_RESERVE_BUFFER,
    CONF_BATTERY_SOC_ENTITIES,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_SOH_ENTITIES,
    CONF_BATTERY_STORED_ENERGY_ENTITIES,
    CONF_BATTERY_TARGET_ENERGY,
    CONF_BATTERY_USABLE_CAPACITY,
    CONF_CHARGE_POWER_ENTITY,
    CONF_CHARGE_TASK_ENTITY,
    CONF_CONTROL_DRY_RUN,
    CONF_CONTROL_ENABLED,
    CONF_CURRENCY_DISPLAY,
    CONF_DISCHARGE_POWER_ENTITY,
    CONF_DISCHARGE_TASK_ENTITY,
    CONF_ENERGY_TAX,
    CONF_ENTSOE_API_TOKEN,
    CONF_GRID_POWER_ENTITY,
    CONF_HOUSEHOLD_LOAD_ENTITY,
    CONF_MANUAL_OVERRIDE_ENTITY,
    CONF_MAX_CHARGE_POWER,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MINIMUM_ACTION_MINUTES,
    CONF_MINIMUM_PROFIT,
    CONF_OPTIMIZATION_DURATION,
    CONF_PRICE_SOURCE,
    CONF_PV_POWER_ENTITY,
    CONF_SOLAR_CONFIDENCE,
    CONF_SOLAR_FORECAST_ATTRIBUTE,
    CONF_SOLAR_FORECAST_ENTITIES,
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_FORECAST_STRATEGY,
    CONF_SOURCE_ENTITY,
    CONF_SOURCE_PRICE_UNIT,
    CONF_SUPPLIER_EXPORT_ADJUSTMENT,
    CONF_SUPPLIER_IMPORT_MARKUP,
    CONF_TAX_PROFILE,
    CONF_TELEMETRY_STALE_MINUTES,
    CONF_VAT_ENERGY_TAX,
    CONF_VAT_EXPORT_ADJUSTMENT,
    CONF_VAT_IMPORT_MARKUP,
    CONF_VAT_MARKET_EXPORT,
    CONF_VAT_MARKET_IMPORT,
    CONF_VAT_PERCENTAGE,
    DEFAULT_ACTION_CONFIRMATION_UPDATES,
    DEFAULT_BATTERY_CHARGE_EFFICIENCY,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_BATTERY_MIN_RESERVE,
    DEFAULT_BATTERY_OPERATING_COST,
    DEFAULT_BATTERY_RESERVE_BUFFER,
    DEFAULT_BATTERY_TARGET_ENERGY,
    DEFAULT_BATTERY_USABLE_CAPACITY,
    DEFAULT_EXPORT_ADJUSTMENT,
    DEFAULT_IMPORT_MARKUP,
    DEFAULT_MAX_CHARGE_POWER,
    DEFAULT_MAX_DISCHARGE_POWER,
    DEFAULT_MINIMUM_ACTION_MINUTES,
    DEFAULT_MINIMUM_PROFIT,
    DEFAULT_OPTIMIZATION_DURATION_MINUTES,
    DEFAULT_SOLAR_CONFIDENCE,
    DEFAULT_TELEMETRY_STALE_MINUTES,
    DOMAIN,
    TAX_PROFILE_DEFAULTS,
    CurrencyDisplay,
    PriceSource,
    SolarForecastStrategy,
    SourcePriceUnit,
    TaxProfile,
)
from .options import (
    OPTIONS_MENU_STEPS,
    normalise_legacy_options,
    prepare_staged_options,
    select_tax_profile,
    update_staged_category,
)


def _number(default: Decimal, *, minimum: float | None = None, maximum: float | None = None) -> Any:
    config: dict[str, Any] = {"mode": selector.NumberSelectorMode.BOX, "step": "any"}
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _entity(values: dict[str, Any], key: str, *, multiple: bool = False) -> tuple[Any, Any]:
    """Build an optional sensor selector while retaining existing selections."""
    options = {"default": values[key]} if values.get(key) else {}
    return (
        vol.Optional(key, **options),
        selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", multiple=multiple)),
    )


def _typed_entity(values: dict[str, Any], key: str, domain: str) -> tuple[Any, Any]:
    """Build an optional entity selector for a control domain."""
    options = {"default": values[key]} if values.get(key) else {}
    return (
        vol.Optional(key, **options),
        selector.EntitySelector(selector.EntitySelectorConfig(domain=domain)),
    )


def _details_schema(
    profile: TaxProfile,
    source: PriceSource,
    values: dict[str, Any] | None = None,
) -> vol.Schema:
    values = normalise_legacy_options(dict(values or {}))
    profile_defaults = TAX_PROFILE_DEFAULTS[profile]
    fields: dict[Any, Any] = {}
    if source is PriceSource.ENTSOE:
        token_key = (
            vol.Required(CONF_ENTSOE_API_TOKEN, default=values[CONF_ENTSOE_API_TOKEN])
            if values.get(CONF_ENTSOE_API_TOKEN)
            else vol.Required(CONF_ENTSOE_API_TOKEN)
        )
        fields[token_key] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    else:
        fields.update(
            {
                vol.Required(
                    CONF_SOURCE_ENTITY, default=values.get(CONF_SOURCE_ENTITY)
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SOURCE_PRICE_UNIT,
                    default=values.get(CONF_SOURCE_PRICE_UNIT, SourcePriceUnit.EUR_PER_KWH),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[unit.value for unit in SourcePriceUnit],
                        translation_key="source_price_unit",
                    )
                ),
            }
        )

    fields.update(
        {
            vol.Required(
                CONF_VAT_PERCENTAGE,
                default=values.get(
                    CONF_VAT_PERCENTAGE, float(profile_defaults[CONF_VAT_PERCENTAGE])
                ),
            ): _number(profile_defaults[CONF_VAT_PERCENTAGE], minimum=0, maximum=100),
            vol.Required(
                CONF_ENERGY_TAX,
                default=values.get(CONF_ENERGY_TAX, float(profile_defaults[CONF_ENERGY_TAX])),
            ): _number(profile_defaults[CONF_ENERGY_TAX]),
            vol.Required(
                CONF_SUPPLIER_IMPORT_MARKUP,
                default=values.get(CONF_SUPPLIER_IMPORT_MARKUP, float(DEFAULT_IMPORT_MARKUP)),
            ): _number(DEFAULT_IMPORT_MARKUP),
            vol.Required(
                CONF_SUPPLIER_EXPORT_ADJUSTMENT,
                default=values.get(
                    CONF_SUPPLIER_EXPORT_ADJUSTMENT, float(DEFAULT_EXPORT_ADJUSTMENT)
                ),
            ): _number(DEFAULT_EXPORT_ADJUSTMENT),
            vol.Required(
                CONF_BATTERY_EFFICIENCY,
                default=values.get(CONF_BATTERY_EFFICIENCY, float(DEFAULT_BATTERY_EFFICIENCY)),
            ): _number(DEFAULT_BATTERY_EFFICIENCY, minimum=0.01, maximum=1),
            vol.Required(
                CONF_BATTERY_CHARGE_EFFICIENCY,
                default=values.get(
                    CONF_BATTERY_CHARGE_EFFICIENCY,
                    float(DEFAULT_BATTERY_CHARGE_EFFICIENCY),
                ),
            ): _number(DEFAULT_BATTERY_CHARGE_EFFICIENCY, minimum=0.01, maximum=1),
            vol.Optional(
                CONF_BATTERY_DISCHARGE_EFFICIENCY,
                **(
                    {"default": values[CONF_BATTERY_DISCHARGE_EFFICIENCY]}
                    if values.get(CONF_BATTERY_DISCHARGE_EFFICIENCY) is not None
                    else {}
                ),
            ): _number(Decimal("0.95"), minimum=0.01, maximum=1),
            vol.Required(
                CONF_MAX_CHARGE_POWER,
                default=values.get(CONF_MAX_CHARGE_POWER, float(DEFAULT_MAX_CHARGE_POWER)),
            ): _number(DEFAULT_MAX_CHARGE_POWER, minimum=0.01),
            vol.Required(
                CONF_MAX_DISCHARGE_POWER,
                default=values.get(CONF_MAX_DISCHARGE_POWER, float(DEFAULT_MAX_DISCHARGE_POWER)),
            ): _number(DEFAULT_MAX_DISCHARGE_POWER, minimum=0.01),
            vol.Required(
                CONF_BATTERY_TARGET_ENERGY,
                default=values.get(
                    CONF_BATTERY_TARGET_ENERGY, float(DEFAULT_BATTERY_TARGET_ENERGY)
                ),
            ): _number(DEFAULT_BATTERY_TARGET_ENERGY, minimum=0.01),
            vol.Required(
                CONF_BATTERY_USABLE_CAPACITY,
                default=values.get(
                    CONF_BATTERY_USABLE_CAPACITY, float(DEFAULT_BATTERY_USABLE_CAPACITY)
                ),
            ): _number(DEFAULT_BATTERY_USABLE_CAPACITY, minimum=0.01),
            vol.Required(
                CONF_BATTERY_MIN_RESERVE,
                default=values.get(CONF_BATTERY_MIN_RESERVE, float(DEFAULT_BATTERY_MIN_RESERVE)),
            ): _number(DEFAULT_BATTERY_MIN_RESERVE, minimum=0, maximum=100),
            vol.Required(
                CONF_BATTERY_RESERVE_BUFFER,
                default=values.get(
                    CONF_BATTERY_RESERVE_BUFFER, float(DEFAULT_BATTERY_RESERVE_BUFFER)
                ),
            ): _number(DEFAULT_BATTERY_RESERVE_BUFFER, minimum=0),
            vol.Required(
                CONF_SOLAR_CONFIDENCE,
                default=values.get(CONF_SOLAR_CONFIDENCE, float(DEFAULT_SOLAR_CONFIDENCE)),
            ): _number(DEFAULT_SOLAR_CONFIDENCE, minimum=0, maximum=100),
            vol.Required(
                CONF_BATTERY_OPERATING_COST,
                default=values.get(
                    CONF_BATTERY_OPERATING_COST, float(DEFAULT_BATTERY_OPERATING_COST)
                ),
            ): _number(DEFAULT_BATTERY_OPERATING_COST, minimum=0),
            vol.Required(
                CONF_MINIMUM_PROFIT,
                default=values.get(CONF_MINIMUM_PROFIT, float(DEFAULT_MINIMUM_PROFIT)),
            ): _number(DEFAULT_MINIMUM_PROFIT, minimum=0),
            vol.Required(
                CONF_ALLOW_GRID_EXPORT, default=values.get(CONF_ALLOW_GRID_EXPORT, False)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_ACTION_CONFIRMATION_UPDATES,
                default=values.get(
                    CONF_ACTION_CONFIRMATION_UPDATES, DEFAULT_ACTION_CONFIRMATION_UPDATES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_MINIMUM_ACTION_MINUTES,
                default=values.get(CONF_MINIMUM_ACTION_MINUTES, DEFAULT_MINIMUM_ACTION_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=60, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_TELEMETRY_STALE_MINUTES,
                default=values.get(CONF_TELEMETRY_STALE_MINUTES, DEFAULT_TELEMETRY_STALE_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=60, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_OPTIMIZATION_DURATION,
                default=values.get(
                    CONF_OPTIMIZATION_DURATION, DEFAULT_OPTIMIZATION_DURATION_MINUTES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=15,
                    max=1440,
                    step=15,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Required(
                CONF_VAT_MARKET_IMPORT, default=values.get(CONF_VAT_MARKET_IMPORT, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_IMPORT_MARKUP, default=values.get(CONF_VAT_IMPORT_MARKUP, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_ENERGY_TAX, default=values.get(CONF_VAT_ENERGY_TAX, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_MARKET_EXPORT, default=values.get(CONF_VAT_MARKET_EXPORT, False)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_EXPORT_ADJUSTMENT,
                default=values.get(CONF_VAT_EXPORT_ADJUSTMENT, False),
            ): selector.BooleanSelector(),
        }
    )
    for key, multiple in (
        (CONF_BATTERY_SOC_ENTITIES, True),
        (CONF_BATTERY_STORED_ENERGY_ENTITIES, True),
        (CONF_BATTERY_CAPACITY_ENTITIES, True),
        (CONF_BATTERY_SOH_ENTITIES, True),
        (CONF_BATTERY_POWER_ENTITIES, True),
        (CONF_HOUSEHOLD_LOAD_ENTITY, False),
        (CONF_GRID_POWER_ENTITY, False),
        (CONF_PV_POWER_ENTITY, False),
        (CONF_SOLAR_FORECAST_ENTITIES, True),
    ):
        field, field_selector = _entity(values, key, multiple=multiple)
        fields[field] = field_selector
    fields[
        vol.Optional(
            CONF_SOLAR_FORECAST_ATTRIBUTE,
            default=values.get(CONF_SOLAR_FORECAST_ATTRIBUTE, ""),
        )
    ] = selector.TextSelector()
    fields[
        vol.Required(
            CONF_SOLAR_FORECAST_STRATEGY,
            default=values.get(CONF_SOLAR_FORECAST_STRATEGY, SolarForecastStrategy.CONSERVATIVE),
        )
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[strategy.value for strategy in SolarForecastStrategy],
            translation_key="solar_forecast_strategy",
        )
    )
    fields[vol.Required(CONF_CONTROL_ENABLED, default=values.get(CONF_CONTROL_ENABLED, False))] = (
        selector.BooleanSelector()
    )
    fields[vol.Required(CONF_CONTROL_DRY_RUN, default=values.get(CONF_CONTROL_DRY_RUN, True))] = (
        selector.BooleanSelector()
    )
    for key, domain in (
        (CONF_CHARGE_TASK_ENTITY, "switch"),
        (CONF_DISCHARGE_TASK_ENTITY, "switch"),
        (CONF_CHARGE_POWER_ENTITY, "number"),
        (CONF_DISCHARGE_POWER_ENTITY, "number"),
        (CONF_MANUAL_OVERRIDE_ENTITY, "input_boolean"),
    ):
        field, field_selector = _typed_entity(values, key, domain)
        fields[field] = field_selector
    return vol.Schema(fields)


def _price_source_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the price-source selection schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_PRICE_SOURCE, default=values.get(CONF_PRICE_SOURCE, PriceSource.ENTSOE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[source.value for source in PriceSource],
                    translation_key="price_source",
                )
            ),
            vol.Required(
                CONF_CURRENCY_DISPLAY,
                default=values.get(CONF_CURRENCY_DISPLAY, CurrencyDisplay.EUR_PER_KWH),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[currency.value for currency in CurrencyDisplay],
                    translation_key="currency_display",
                )
            ),
        }
    )


def _price_source_details_schema(source: PriceSource, values: dict[str, Any]) -> vol.Schema:
    """Build source-specific credential and entity fields."""
    if source is PriceSource.ENTSOE:
        token_key = (
            vol.Required(CONF_ENTSOE_API_TOKEN, default=values[CONF_ENTSOE_API_TOKEN])
            if values.get(CONF_ENTSOE_API_TOKEN)
            else vol.Required(CONF_ENTSOE_API_TOKEN)
        )
        return vol.Schema(
            {
                token_key: selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                )
            }
        )
    return vol.Schema(
        {
            vol.Required(
                CONF_SOURCE_ENTITY, default=values.get(CONF_SOURCE_ENTITY)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_SOURCE_PRICE_UNIT,
                default=values.get(CONF_SOURCE_PRICE_UNIT, SourcePriceUnit.EUR_PER_KWH),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[unit.value for unit in SourcePriceUnit],
                    translation_key="source_price_unit",
                )
            ),
        }
    )


def _tax_profile_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the tax-profile selection schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_TAX_PROFILE,
                default=values.get(CONF_TAX_PROFILE, TaxProfile.NETHERLANDS_2027),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[profile.value for profile in TaxProfile],
                    translation_key="tax_profile",
                )
            )
        }
    )


def _tax_details_schema(profile: TaxProfile, values: dict[str, Any]) -> vol.Schema:
    """Build tax and supplier price fields."""
    defaults = TAX_PROFILE_DEFAULTS[profile]
    return vol.Schema(
        {
            vol.Required(
                CONF_VAT_PERCENTAGE,
                default=values.get(CONF_VAT_PERCENTAGE, float(defaults[CONF_VAT_PERCENTAGE])),
            ): _number(defaults[CONF_VAT_PERCENTAGE], minimum=0, maximum=100),
            vol.Required(
                CONF_ENERGY_TAX,
                default=values.get(CONF_ENERGY_TAX, float(defaults[CONF_ENERGY_TAX])),
            ): _number(defaults[CONF_ENERGY_TAX]),
            vol.Required(
                CONF_SUPPLIER_IMPORT_MARKUP,
                default=values.get(CONF_SUPPLIER_IMPORT_MARKUP, float(DEFAULT_IMPORT_MARKUP)),
            ): _number(DEFAULT_IMPORT_MARKUP),
            vol.Required(
                CONF_SUPPLIER_EXPORT_ADJUSTMENT,
                default=values.get(
                    CONF_SUPPLIER_EXPORT_ADJUSTMENT, float(DEFAULT_EXPORT_ADJUSTMENT)
                ),
            ): _number(DEFAULT_EXPORT_ADJUSTMENT),
        }
    )


def _vat_rules_schema(values: dict[str, Any]) -> vol.Schema:
    """Build the advanced VAT application fields."""
    return vol.Schema(
        {
            vol.Required(
                CONF_VAT_MARKET_IMPORT, default=values.get(CONF_VAT_MARKET_IMPORT, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_IMPORT_MARKUP, default=values.get(CONF_VAT_IMPORT_MARKUP, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_ENERGY_TAX, default=values.get(CONF_VAT_ENERGY_TAX, True)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_MARKET_EXPORT, default=values.get(CONF_VAT_MARKET_EXPORT, False)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_VAT_EXPORT_ADJUSTMENT,
                default=values.get(CONF_VAT_EXPORT_ADJUSTMENT, False),
            ): selector.BooleanSelector(),
        }
    )


def _battery_schema(values: dict[str, Any]) -> vol.Schema:
    """Build battery specification and efficiency fields."""
    return vol.Schema(
        {
            vol.Required(
                CONF_BATTERY_EFFICIENCY,
                default=values.get(CONF_BATTERY_EFFICIENCY, float(DEFAULT_BATTERY_EFFICIENCY)),
            ): _number(DEFAULT_BATTERY_EFFICIENCY, minimum=0.01, maximum=1),
            vol.Required(
                CONF_BATTERY_CHARGE_EFFICIENCY,
                default=values.get(
                    CONF_BATTERY_CHARGE_EFFICIENCY,
                    float(DEFAULT_BATTERY_CHARGE_EFFICIENCY),
                ),
            ): _number(DEFAULT_BATTERY_CHARGE_EFFICIENCY, minimum=0.01, maximum=1),
            vol.Optional(
                CONF_BATTERY_DISCHARGE_EFFICIENCY,
                **(
                    {"default": values[CONF_BATTERY_DISCHARGE_EFFICIENCY]}
                    if values.get(CONF_BATTERY_DISCHARGE_EFFICIENCY) is not None
                    else {}
                ),
            ): _number(Decimal("0.95"), minimum=0.01, maximum=1),
            vol.Required(
                CONF_MAX_CHARGE_POWER,
                default=values.get(CONF_MAX_CHARGE_POWER, float(DEFAULT_MAX_CHARGE_POWER)),
            ): _number(DEFAULT_MAX_CHARGE_POWER, minimum=0.01),
            vol.Required(
                CONF_MAX_DISCHARGE_POWER,
                default=values.get(CONF_MAX_DISCHARGE_POWER, float(DEFAULT_MAX_DISCHARGE_POWER)),
            ): _number(DEFAULT_MAX_DISCHARGE_POWER, minimum=0.01),
            vol.Required(
                CONF_BATTERY_TARGET_ENERGY,
                default=values.get(
                    CONF_BATTERY_TARGET_ENERGY, float(DEFAULT_BATTERY_TARGET_ENERGY)
                ),
            ): _number(DEFAULT_BATTERY_TARGET_ENERGY, minimum=0.01),
            vol.Required(
                CONF_BATTERY_USABLE_CAPACITY,
                default=values.get(
                    CONF_BATTERY_USABLE_CAPACITY, float(DEFAULT_BATTERY_USABLE_CAPACITY)
                ),
            ): _number(DEFAULT_BATTERY_USABLE_CAPACITY, minimum=0.01),
        }
    )


def _battery_entities_schema(values: dict[str, Any]) -> vol.Schema:
    """Build battery telemetry entity fields."""
    fields: dict[Any, Any] = {}
    for key in (
        CONF_BATTERY_SOC_ENTITIES,
        CONF_BATTERY_STORED_ENERGY_ENTITIES,
        CONF_BATTERY_CAPACITY_ENTITIES,
        CONF_BATTERY_SOH_ENTITIES,
        CONF_BATTERY_POWER_ENTITIES,
    ):
        field, field_selector = _entity(values, key, multiple=True)
        fields[field] = field_selector
    fields[
        vol.Required(
            CONF_TELEMETRY_STALE_MINUTES,
            default=values.get(CONF_TELEMETRY_STALE_MINUTES, DEFAULT_TELEMETRY_STALE_MINUTES),
        )
    ] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=1, max=60, step=1, mode=selector.NumberSelectorMode.BOX)
    )
    return vol.Schema(fields)


def _solar_schema(values: dict[str, Any]) -> vol.Schema:
    """Build live power and solar forecast fields."""
    fields: dict[Any, Any] = {}
    for key, multiple in (
        (CONF_HOUSEHOLD_LOAD_ENTITY, False),
        (CONF_GRID_POWER_ENTITY, False),
        (CONF_PV_POWER_ENTITY, False),
        (CONF_SOLAR_FORECAST_ENTITIES, True),
    ):
        field, field_selector = _entity(values, key, multiple=multiple)
        fields[field] = field_selector
    fields[
        vol.Optional(
            CONF_SOLAR_FORECAST_ATTRIBUTE,
            default=values.get(CONF_SOLAR_FORECAST_ATTRIBUTE, ""),
        )
    ] = selector.TextSelector()
    fields[
        vol.Required(
            CONF_SOLAR_FORECAST_STRATEGY,
            default=values.get(CONF_SOLAR_FORECAST_STRATEGY, SolarForecastStrategy.CONSERVATIVE),
        )
    ] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[strategy.value for strategy in SolarForecastStrategy],
            translation_key="solar_forecast_strategy",
        )
    )
    fields[
        vol.Required(
            CONF_SOLAR_CONFIDENCE,
            default=values.get(CONF_SOLAR_CONFIDENCE, float(DEFAULT_SOLAR_CONFIDENCE)),
        )
    ] = _number(DEFAULT_SOLAR_CONFIDENCE, minimum=0, maximum=100)
    return vol.Schema(fields)


def _optimization_schema(values: dict[str, Any]) -> vol.Schema:
    """Build rolling optimisation and action stability fields."""
    return vol.Schema(
        {
            vol.Required(
                CONF_BATTERY_MIN_RESERVE,
                default=values.get(CONF_BATTERY_MIN_RESERVE, float(DEFAULT_BATTERY_MIN_RESERVE)),
            ): _number(DEFAULT_BATTERY_MIN_RESERVE, minimum=0, maximum=100),
            vol.Required(
                CONF_BATTERY_RESERVE_BUFFER,
                default=values.get(
                    CONF_BATTERY_RESERVE_BUFFER, float(DEFAULT_BATTERY_RESERVE_BUFFER)
                ),
            ): _number(DEFAULT_BATTERY_RESERVE_BUFFER, minimum=0),
            vol.Required(
                CONF_BATTERY_OPERATING_COST,
                default=values.get(
                    CONF_BATTERY_OPERATING_COST, float(DEFAULT_BATTERY_OPERATING_COST)
                ),
            ): _number(DEFAULT_BATTERY_OPERATING_COST, minimum=0),
            vol.Required(
                CONF_MINIMUM_PROFIT,
                default=values.get(CONF_MINIMUM_PROFIT, float(DEFAULT_MINIMUM_PROFIT)),
            ): _number(DEFAULT_MINIMUM_PROFIT, minimum=0),
            vol.Required(
                CONF_ALLOW_GRID_EXPORT, default=values.get(CONF_ALLOW_GRID_EXPORT, False)
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_OPTIMIZATION_DURATION,
                default=values.get(
                    CONF_OPTIMIZATION_DURATION, DEFAULT_OPTIMIZATION_DURATION_MINUTES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=15,
                    max=1440,
                    step=15,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Required(
                CONF_ACTION_CONFIRMATION_UPDATES,
                default=values.get(
                    CONF_ACTION_CONFIRMATION_UPDATES, DEFAULT_ACTION_CONFIRMATION_UPDATES
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_MINIMUM_ACTION_MINUTES,
                default=values.get(CONF_MINIMUM_ACTION_MINUTES, DEFAULT_MINIMUM_ACTION_MINUTES),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=60, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _control_schema(values: dict[str, Any]) -> vol.Schema:
    """Build optional generic battery controller fields."""
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_CONTROL_ENABLED, default=values.get(CONF_CONTROL_ENABLED, False)
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_CONTROL_DRY_RUN, default=values.get(CONF_CONTROL_DRY_RUN, True)
        ): selector.BooleanSelector(),
    }
    for key, domain in (
        (CONF_CHARGE_TASK_ENTITY, "switch"),
        (CONF_DISCHARGE_TASK_ENTITY, "switch"),
        (CONF_CHARGE_POWER_ENTITY, "number"),
        (CONF_DISCHARGE_POWER_ENTITY, "number"),
        (CONF_MANUAL_OVERRIDE_ENTITY, "input_boolean"),
    ):
        field, field_selector = _typed_entity(values, key, domain)
        fields[field] = field_selector
    return vol.Schema(fields)


class DutchEnergyPricesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the integration config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self._base: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the source and tax profile."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._base = user_input
            return await self.async_step_details()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PRICE_SOURCE, default=PriceSource.ENTSOE
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[source.value for source in PriceSource],
                            translation_key="price_source",
                        )
                    ),
                    vol.Required(
                        CONF_TAX_PROFILE, default=TaxProfile.NETHERLANDS_2027
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[profile.value for profile in TaxProfile],
                            translation_key="tax_profile",
                        )
                    ),
                    vol.Required(
                        CONF_CURRENCY_DISPLAY, default=CurrencyDisplay.EUR_PER_KWH
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[currency.value for currency in CurrencyDisplay],
                            translation_key="currency_display",
                        )
                    ),
                }
            ),
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect editable pricing details."""
        if user_input is not None:
            return self.async_create_entry(
                title="Dutch Energy",
                data={
                    **self._base,
                    CONF_BATTERY_SOC_ENTITY: None,
                    CONF_HOUSEHOLD_LOAD_ENTITY: None,
                    **user_input,
                },
            )
        profile = TaxProfile(self._base[CONF_TAX_PROFILE])
        source = PriceSource(self._base[CONF_PRICE_SOURCE])
        return self.async_show_form(step_id="details", data_schema=_details_schema(profile, source))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return DutchEnergyPricesOptionsFlow()


class DutchEnergyPricesOptionsFlow(config_entries.OptionsFlow):
    """Edit all values without recreating the entry."""

    def __init__(self) -> None:
        self._values: dict[str, Any] | None = None

    def _staged_values(self) -> dict[str, Any]:
        """Return the working copy, initializing it from the config entry once."""
        if self._values is None:
            self._values = prepare_staged_options(self.config_entry.data, self.config_entry.options)
        return self._values

    async def _async_category_step(
        self,
        step_id: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
        clearable_keys: tuple[str, ...] = (),
    ) -> ConfigFlowResult:
        """Stage one category and return to the options menu."""
        if user_input is not None:
            self._values = update_staged_category(self._staged_values(), user_input, clearable_keys)
            return await self.async_step_init()
        return self.async_show_form(step_id=step_id, data_schema=schema)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show a category menu instead of one long settings form."""
        self._staged_values()
        return self.async_show_menu(
            step_id="init",
            menu_options=list(OPTIONS_MENU_STEPS),
        )

    async def async_step_price_source(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the source type and display currency."""
        values = self._staged_values()
        if user_input is not None:
            values.update(user_input)
            return await self.async_step_price_source_details()
        return self.async_show_form(
            step_id="price_source", data_schema=_price_source_schema(values)
        )

    async def async_step_price_source_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit settings for the selected source type."""
        values = self._staged_values()
        source = PriceSource(values[CONF_PRICE_SOURCE])
        return await self._async_category_step(
            "price_source_details",
            _price_source_details_schema(source, values),
            user_input,
        )

    async def async_step_taxes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose a tax profile before editing its user-overridable values."""
        values = self._staged_values()
        if user_input is not None:
            profile = TaxProfile(user_input[CONF_TAX_PROFILE])
            self._values = select_tax_profile(values, profile)
            return await self.async_step_tax_details()
        return self.async_show_form(step_id="taxes", data_schema=_tax_profile_schema(values))

    async def async_step_tax_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit tax and supplier price values."""
        values = self._staged_values()
        profile = TaxProfile(values[CONF_TAX_PROFILE])
        return await self._async_category_step(
            "tax_details", _tax_details_schema(profile, values), user_input
        )

    async def async_step_vat_rules(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit advanced component-level VAT rules."""
        values = self._staged_values()
        return await self._async_category_step("vat_rules", _vat_rules_schema(values), user_input)

    async def async_step_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit battery specifications and efficiencies."""
        values = self._staged_values()
        return await self._async_category_step(
            "battery",
            _battery_schema(values),
            user_input,
            (CONF_BATTERY_DISCHARGE_EFFICIENCY,),
        )

    async def async_step_battery_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit battery telemetry entities."""
        values = self._staged_values()
        return await self._async_category_step(
            "battery_entities",
            _battery_entities_schema(values),
            user_input,
            (
                CONF_BATTERY_SOC_ENTITIES,
                CONF_BATTERY_STORED_ENERGY_ENTITIES,
                CONF_BATTERY_CAPACITY_ENTITIES,
                CONF_BATTERY_SOH_ENTITIES,
                CONF_BATTERY_POWER_ENTITIES,
            ),
        )

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Edit live consumption, grid, PV and forecast entities."""
        values = self._staged_values()
        return await self._async_category_step(
            "solar",
            _solar_schema(values),
            user_input,
            (
                CONF_HOUSEHOLD_LOAD_ENTITY,
                CONF_GRID_POWER_ENTITY,
                CONF_PV_POWER_ENTITY,
                CONF_SOLAR_FORECAST_ENTITIES,
                CONF_SOLAR_FORECAST_ATTRIBUTE,
            ),
        )

    async def async_step_optimization(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit rolling optimiser thresholds and safeguards."""
        values = self._staged_values()
        return await self._async_category_step(
            "optimization", _optimization_schema(values), user_input
        )

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit optional generic controller settings."""
        values = self._staged_values()
        return await self._async_category_step(
            "control",
            _control_schema(values),
            user_input,
            (
                CONF_CHARGE_TASK_ENTITY,
                CONF_DISCHARGE_TASK_ENTITY,
                CONF_CHARGE_POWER_ENTITY,
                CONF_DISCHARGE_POWER_ENTITY,
                CONF_MANUAL_OVERRIDE_ENTITY,
            ),
        )

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Persist all staged options and reload the integration once."""
        values = {
            **self._staged_values(),
            CONF_BATTERY_SOC_ENTITY: None,
            CONF_SOLAR_FORECAST_ENTITY: None,
        }
        return self.async_create_entry(
            title="",
            data=values,
        )
