"""Constants for Dutch Energy Prices."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

DOMAIN = "dutch_energy_prices"
NAME = "Dutch Energy Prices"
PLATFORMS = ["sensor"]

CONF_PRICE_SOURCE = "price_source"
CONF_SOURCE_ENTITY = "source_entity"
CONF_SOURCE_PRICE_UNIT = "source_price_unit"
CONF_TAX_PROFILE = "tax_profile"
CONF_VAT_PERCENTAGE = "vat_percentage"
CONF_ENERGY_TAX = "energy_tax"
CONF_SUPPLIER_IMPORT_MARKUP = "supplier_import_markup"
CONF_SUPPLIER_EXPORT_ADJUSTMENT = "supplier_export_adjustment"
CONF_BATTERY_EFFICIENCY = "battery_round_trip_efficiency"
CONF_CURRENCY_DISPLAY = "currency_display"
CONF_VAT_MARKET_IMPORT = "vat_market_import"
CONF_VAT_IMPORT_MARKUP = "vat_import_markup"
CONF_VAT_ENERGY_TAX = "vat_energy_tax"
CONF_VAT_MARKET_EXPORT = "vat_market_export"
CONF_VAT_EXPORT_ADJUSTMENT = "vat_export_adjustment"

ATTR_PRICES_TODAY = "prices_today"
ATTR_PRICES_TOMORROW = "prices_tomorrow"

UPDATE_INTERVAL_MINUTES = 15
PERIOD_MINUTES = 15


class PriceSource(StrEnum):
    """Supported price sources."""

    HOME_ASSISTANT_ENTITY = "home_assistant_entity"


class SourcePriceUnit(StrEnum):
    """Supported source units."""

    EUR_PER_KWH = "eur_per_kwh"
    EUR_PER_MWH = "eur_per_mwh"


class CurrencyDisplay(StrEnum):
    """Display units. Calculations always use EUR/kWh."""

    EUR_PER_KWH = "eur_per_kwh"
    CENT_PER_KWH = "cent_per_kwh"


class TaxProfile(StrEnum):
    """Tax profile identifiers."""

    NETHERLANDS_2027 = "netherlands_2027"
    NETHERLANDS_2026 = "netherlands_2026"
    CUSTOM = "custom"


# The 2027 rate is intentionally a user-editable provisional value until the
# final statutory rate is published. The 2026 amount is exclusive of 21% VAT.
TAX_PROFILE_DEFAULTS: dict[TaxProfile, dict[str, Decimal]] = {
    TaxProfile.NETHERLANDS_2027: {
        CONF_VAT_PERCENTAGE: Decimal("21"),
        CONF_ENERGY_TAX: Decimal("0.09161"),
    },
    TaxProfile.NETHERLANDS_2026: {
        CONF_VAT_PERCENTAGE: Decimal("21"),
        CONF_ENERGY_TAX: Decimal("0.09161"),
    },
    TaxProfile.CUSTOM: {
        CONF_VAT_PERCENTAGE: Decimal("21"),
        CONF_ENERGY_TAX: Decimal("0"),
    },
}

DEFAULT_IMPORT_MARKUP = Decimal("0")
DEFAULT_EXPORT_ADJUSTMENT = Decimal("0")
DEFAULT_BATTERY_EFFICIENCY = Decimal("0.85")
