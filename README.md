# Dutch Energy Prices

[![GitHub release](https://img.shields.io/github/release/chill-uk/ha-dutch-energy-prices?include_prereleases=&sort=semver&color=blue)](https://github.com/chill-uk/ha-dutch-energy-prices/releases/)
[![issues - ecoflow-p1-ha](https://img.shields.io/github/issues/chill-uk/ha-dutch-energy-prices)](https://github.com/chill-uk/ha-dutch-energy-prices/issues)
[![GH-code-size](https://img.shields.io/github/languages/code-size/chill-uk/ha-dutch-energy-prices?color=red)](https://github.com/chill-uk/ha-dutch-energy-prices)
[![GH-last-commit](https://img.shields.io/github/last-commit/chill-uk/ha-dutch-energy-prices?style=flat-square)](https://github.com/chill-uk/ha-dutch-energy-prices/commits/main)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validation](https://github.com/chill-uk/ha-dutch-energy-prices/actions/workflows/hacs.yml/badge.svg)](https://github.com/chill-uk/ha-dutch-energy-prices/actions/workflows/hacs.yml)
![GitHub Downloads](https://img.shields.io/github/downloads/chill-uk/ha-dutch-energy-prices/total)

A Home Assistant custom integration for Dutch dynamic electricity contracts, designed around native **15-minute** prices and the post-saldering market from 2027 onward.

## Features

- Retrieves Dutch day-ahead prices directly from ENTSO-E or consumes native
  15-minute prices from an existing Home Assistant sensor.
- Keeps all monetary values internally as `Decimal` EUR/kWh.
- Calculates raw market, all-in import, export, energy-tax and import/export-spread sensors.
- Finds the cheapest contiguous 15-minute, 1-hour and 2-hour windows without hourly aggregation.
- Exposes today and tomorrow on the market-price sensor only, avoiding duplicate large attributes.
- The live forecast arrays are excluded from Recorder history so a complete
  two-day price schedule does not exceed its state-attribute size limit.
- Provides editable Netherlands 2026, provisional Netherlands 2027 and custom tax profiles.
- Includes diagnostics, translations, tests, Ruff and HACS metadata.
- Calculates battery losses, the best ordered charge/discharge windows, expected
  grid-arbitrage value and the value of storing solar instead of exporting it.
- Supports an editable optimisation duration from 15 minutes to 24 hours in
  native 15-minute increments.
- Plans a configurable delivered-energy target using separate maximum charging
  and discharging power limits, including partial 15-minute slots.
- Scans the complete today/tomorrow horizon for non-contiguous, power-limited
  15-minute charging and discharging slots and costs every allocation exactly.
- Supports multiple battery banks, live stored energy/capacity/SOH entities,
  split charge/discharge efficiency, battery operating cost and minimum profit.
- Normalises common Solcast and Open-Meteo forecast attributes, keeps capacity
  available for conservative solar production, and handles negative import and
  export prices explicitly.
- Stabilises rolling recommendations with telemetry retention, confirmation
  counts and a minimum action duration.
- Optionally controls generic Home Assistant switch/number entities. Control is
  disabled by default and can be tested in dry-run mode before any device write.

The fixed annual energy-tax rebate is deliberately excluded because it does not alter the marginal cost of charging one additional kWh.

## ENTSO-E source

The recommended source retrieves today and tomorrow directly from the ENTSO-E
Transparency Platform. Create an ENTSO-E account, request REST API access, and
enter the resulting security token during setup. The integration queries the
Netherlands bidding zone (`10YNL----------L`) and accepts only native `PT15M`
prices in EUR/MWh. Values are converted to EUR/kWh before any Dutch tax or
supplier calculations are applied.

Tomorrow's prices are not real-time quotes: they appear after the day-ahead
auction publishes them. Before that publication, the current day's periods
remain available. Negative prices and 23/25-hour daylight-saving days are
handled without hourly expansion.

## Home Assistant entity source

The selected sensor must expose either a `prices` list, or `today` and `tomorrow` lists. Each list item must contain a timezone-aware start, a numeric market price, and optionally an end. Missing ends are derived as start + 15 minutes.

```yaml
prices:
  - start: "2027-01-10T13:00:00+01:00"
    end: "2027-01-10T13:15:00+01:00"
    market_price: 0.0632
```

Accepted aliases are `datetime` or `time` for `start`, and `price` or `value` for `market_price`. Configure whether the source uses EUR/kWh or EUR/MWh. Any period that is not exactly 15 minutes is rejected; hourly values are never expanded or averaged.

## Price model

VAT applicability is configurable for every component. With all import components taxable and export components untaxed, the defaults reduce to:

```text
import = (market + supplier import markup + energy tax) × (1 + VAT)
export = market + supplier export adjustment
```

The display unit is selected when the integration is created and then remains
fixed for that config entry. This prevents Home Assistant long-term statistics
from being invalidated by switching an existing sensor between EUR/kWh and
ct/kWh.

The 2026 profile uses the household electricity energy-tax rate of **€0.09161/kWh excluding VAT** (equivalent to €0.11085 including 21% VAT). The 2027 value is explicitly provisional and user-editable until final statutory rates are available.

Changing the profile in integration options loads that profile's VAT and
energy-tax defaults in the next screen; review or edit them before saving.
Keeping the same profile preserves your previously edited tax values.

Current price and future-window sensors update at every Dutch 15-minute price
boundary. ENTSO-E forecasts are fetched every 15 minutes; an existing Home
Assistant price-entity source also refreshes when that source changes.

## Installation

### HACS custom repository

1. Add this repository to HACS as an Integration repository.
2. Install **Dutch Energy Prices**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**.
5. Select **Dutch Energy Prices** and choose **ENTSO-E** or a compatible
   15-minute source sensor.

Tagged releases (`v0.4.0`, etc.) attach `dutch_energy_prices.zip`. HACS
installs that ZIP as the integration; it contains the contents of
`custom_components/dutch_energy_prices` at the archive root.

### Manual

Copy `custom_components/dutch_energy_prices` into your Home Assistant `custom_components` directory and restart Home Assistant.

## Sensors

- `sensor.dutch_energy_market_price`
- `sensor.dutch_energy_import_price`
- `sensor.dutch_energy_export_price`
- `sensor.dutch_energy_energy_tax`
- `sensor.dutch_energy_vat`
- `sensor.dutch_energy_cheapest_slot`
- `sensor.dutch_energy_cheapest_1h`
- `sensor.dutch_energy_cheapest_2h`
- `sensor.dutch_energy_import_export_spread`
- `sensor.dutch_energy_effective_battery_cost`
- `sensor.dutch_energy_best_battery_charge_period`
- `sensor.dutch_energy_best_battery_discharge_period`
- `sensor.dutch_energy_estimated_arbitrage_value`
- `sensor.dutch_energy_solar_storage_value`
- `sensor.dutch_energy_battery_plan_charge_start`
- `sensor.dutch_energy_battery_plan_discharge_start`
- `sensor.dutch_energy_battery_plan_value`
- `sensor.dutch_energy_battery_rolling_action` (when both telemetry sensors are configured)
- `sensor.dutch_energy_optimized_plan_value`
- `sensor.dutch_energy_planned_grid_charge_energy`
- `sensor.dutch_energy_planned_solar_charge_energy`
- `sensor.dutch_energy_planned_discharge_energy`
- `sensor.dutch_energy_battery_reserve_energy`
- `sensor.dutch_energy_next_optimized_charge`
- `sensor.dutch_energy_next_optimized_discharge`
- `sensor.dutch_energy_flexible_load_action` (when live PV and load are configured)
- `sensor.dutch_energy_battery_control_status` (when optional control is enabled)

Home Assistant may append a suffix if one of these entity IDs already exists.

## Full-horizon battery optimiser

The legacy opportunity sensors retain their contiguous-window calculations for
dashboard compatibility. The optimized plan uses every available 15-minute
period across today and tomorrow. Charge slots may be non-contiguous, and the
current and final slots can contain partial energy allocations.

```text
charge cost = Σ(grid energy in slot × exact import price in slot)
self-use value = Σ(discharged energy × avoided import price)
export value = Σ(exported energy × export price)
net value = self-use value + export value - charge cost
            - forgone solar export - battery operating cost
```

The effective battery cost sensor applies the same efficiency loss to the
current import price. Solar storage value compares exporting one kWh now with
storing it for the most valuable later usage window:

```text
solar storage value = later average import price × round-trip efficiency
                      - current export price
```

Only transactions meeting the configured minimum profit are selected. This
naturally supports negative prices: a negative market price is not assumed to
be a negative consumer import price, and a negative export tariff increases the
value of retaining solar instead of exporting it.

Configure round-trip and charging efficiency. Unless an explicit discharging
efficiency is entered, it is derived as:

```text
discharging efficiency = round-trip efficiency / charging efficiency
```

For example, 85% round-trip and 90% charging efficiency gives approximately
94.44% discharging efficiency.

### Battery entities

Select either a combined battery sensor or one sensor per battery bank. Lists
are positional: the first SOC, stored-energy, capacity and SOH entities describe
the same bank. Live stored energy is preferred; otherwise stored energy is
calculated from SOC and SOH-adjusted capacity. The configured capacity remains
the fallback when no capacity sensor exists.

Use a **total household consumption** entity such as EcoFlow `System Load`, not
a P1 net-import entity. Grid flow, total PV power and battery power are separate
optional measurements.

### Solar forecast

Select the Solcast and/or Open-Meteo sensors that expose detailed forecast lists.
The integration detects the common `detailedForecast`, `detailedHourly`,
`forecast` and `data` attributes, or you can enter the attribute explicitly.
Forecast power/energy is normalised to 15-minute kWh periods. The confidence
percentage deliberately derates forecast solar before reserving battery space.
When both providers are selected, choose the lowest forecast, their average or
the highest forecast; conservative/lowest is the default.

### Rolling recommendation

On the second configuration screen, select one or more battery level/stored
energy sensors and a household-load sensor reporting W or kW. Also configure
fallback capacity, a minimum reserve percentage and an additional reserve
buffer in kWh. Existing single-SOC entries migrate automatically.

The rolling action follows the full optimized schedule. It preserves the
minimum SOC, configured kWh buffer and forecast net consumption until solar
surplus is expected. Brief `unknown`/`unavailable` telemetry retains the last
valid reading for a configurable period. Changes require repeated confirmation
and respect a minimum action duration, preventing rapid hold/discharge flips.

The `dutch_energy_prices.get_plan` action returns the complete non-hold schedule
on demand. Detailed schedules are deliberately not stored as sensor attributes,
which keeps Recorder state rows small.

### Optional control

Control is manufacturer-independent and maps the plan to selected charging and
discharging task switches plus optional power-limit number entities. It is
disabled by default. Enable **dry run** first and inspect the rolling action and
control-status sensor for several days.

The controller turns both task switches off for `hold`, never treats forecast
solar charging as forced grid charging, stops acting when telemetry expires,
and supports an `input_boolean` manual override. Planned grid export is also
disabled unless explicitly enabled. Device-specific modes such as EcoFlow
Self-Powered should still be configured correctly before control is enabled.

## Roadmap

Future providers can implement `PriceProvider` without changing Dutch pricing logic. Planned candidates include Nord Pool and supplier adapters.

## Development

```bash
python -m pip install pytest ruff
pytest
ruff check .
ruff format --check .
```
