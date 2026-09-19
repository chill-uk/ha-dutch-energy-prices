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
    CONF_BATTERY_EFFICIENCY,
    CONF_CURRENCY_DISPLAY,
    CONF_ENERGY_TAX,
    CONF_ENTSOE_API_TOKEN,
    CONF_PRICE_SOURCE,
    CONF_SOURCE_ENTITY,
    CONF_SOURCE_PRICE_UNIT,
    CONF_SUPPLIER_EXPORT_ADJUSTMENT,
    CONF_SUPPLIER_IMPORT_MARKUP,
    CONF_TAX_PROFILE,
    CONF_VAT_ENERGY_TAX,
    CONF_VAT_EXPORT_ADJUSTMENT,
    CONF_VAT_IMPORT_MARKUP,
    CONF_VAT_MARKET_EXPORT,
    CONF_VAT_MARKET_IMPORT,
    CONF_VAT_PERCENTAGE,
    DEFAULT_BATTERY_EFFICIENCY,
    DEFAULT_EXPORT_ADJUSTMENT,
    DEFAULT_IMPORT_MARKUP,
    DOMAIN,
    TAX_PROFILE_DEFAULTS,
    CurrencyDisplay,
    PriceSource,
    SourcePriceUnit,
    TaxProfile,
)


def _number(default: Decimal, *, minimum: float | None = None, maximum: float | None = None) -> Any:
    config: dict[str, Any] = {"mode": selector.NumberSelectorMode.BOX, "step": "any"}
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _details_schema(
    profile: TaxProfile,
    source: PriceSource,
    values: dict[str, Any] | None = None,
) -> vol.Schema:
    values = values or {}
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
    return vol.Schema(fields)


class DutchEnergyPricesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the integration config flow."""

    VERSION = 1

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
            return self.async_create_entry(title="Dutch Energy", data={**self._base, **user_input})
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
        self._base: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose source and display/profile settings before source-specific details."""
        if user_input is not None:
            self._base = user_input
            return await self.async_step_details()
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PRICE_SOURCE, default=current[CONF_PRICE_SOURCE]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[source.value for source in PriceSource],
                            translation_key="price_source",
                        )
                    ),
                    vol.Required(
                        CONF_TAX_PROFILE, default=current[CONF_TAX_PROFILE]
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[item.value for item in TaxProfile],
                            translation_key="tax_profile",
                        )
                    ),
                    vol.Required(
                        CONF_CURRENCY_DISPLAY,
                        default=current[CONF_CURRENCY_DISPLAY],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[item.value for item in CurrencyDisplay],
                            translation_key="currency_display",
                        )
                    ),
                }
            ),
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit source credentials and price components."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._base, **user_input})
        profile = TaxProfile(self._base[CONF_TAX_PROFILE])
        source = PriceSource(self._base[CONF_PRICE_SOURCE])
        return self.async_show_form(
            step_id="details",
            data_schema=_details_schema(profile, source, current),
        )
