# Dutch Energy Prices

[![GitHub release](https://img.shields.io/github/release/chill-uk/ha-dutch-energy-prices?include_prereleases=&sort=semver&color=blue)](https://github.com/chill-uk/ha-dutch-energy-prices/releases/)
[![issues - ecoflow-p1-ha](https://img.shields.io/github/issues/chill-uk/ha-dutch-energy-prices)](https://github.com/chill-uk/ha-dutch-energy-prices/issues)
[![GH-code-size](https://img.shields.io/github/languages/code-size/chill-uk/ha-dutch-energy-prices?color=red)](https://github.com/chill-uk/ha-dutch-energy-prices)
[![GH-last-commit](https://img.shields.io/github/last-commit/chill-uk/ha-dutch-energy-prices?style=flat-square)](https://github.com/chill-uk/ha-dutch-energy-prices/commits/main)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validation](https://github.com/chill-uk/ha-dutch-energy-prices/actions/workflows/hacs.yml/badge.svg)](https://github.com/chill-uk/ha-dutch-energy-prices/actions/workflows/hacs.yml)
![GitHub Downloads](https://img.shields.io/github/downloads/chill-uk/ha-dutch-energy-prices/total)

A Home Assistant custom integration for Dutch dynamic electricity contracts, designed around native **15-minute** prices and the post-saldering market from 2027 onward.

## Installation

The quickest way to install this integration is via [HACS](https://github.com/hacs/integration) by clicking the button below:

[![Add to HACS via My Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=chill-uk&repository=ha-dutch-energy-prices&category=integration)



### HACS custom repository

1. Click the button above to add this repository to HACS as a custom integration.
2. Install `Dutch Energy Prices` from HACS.
4. In Home Assistant, go to `Settings -> Devices & Services`.
5. Add the `EcoFlow P1 Energy Tracker` integration.
6. Restart Home Assistant.
7. Select `Dutch Energy Prices` and choose `ENTSO-E` or a compatible
   15-minute source sensor.

### Manual installation

1. Copy `custom_components/dutch_energy_prices` into your Home Assistant config directory.
2. Restart Home Assistant.
3. In Home Assistant, add the `Dutch Energy Prices` integration from `Settings -> Devices & Services`.


## Features

- Retrieves Dutch day-ahead prices directly from ENTSO-E or consumes native
  15-minute prices from an existing Home Assistant sensor.
- Keeps all monetary values internally as `Decimal` EUR/kWh.
- Calculates raw market, all-in import, export, energy-tax and import/export-spread sensors.
- Finds the cheapest contiguous 15-minute, 1-hour and 2-hour windows without hourly aggregation.
- Exposes today and tomorrow on the market-price sensor only, avoiding duplicate large attributes.
- Provides editable Netherlands 2026, provisional Netherlands 2027 and custom tax profiles.
- Calculates battery losses, the best ordered charge/discharge windows, expected
  grid-arbitrage value and the value of storing solar instead of exporting it.
- Supports an editable optimisation duration from 15 minutes to 24 hours in
  native 15-minute increments.
- Plans a configurable delivered-energy target using separate maximum charging
  and discharging power limits, including partial 15-minute slots.
- Provides a live, read-only charge/discharge/hold recommendation using optional
  battery-level and household-load sensors, with an energy reserve until the
  next forecast cheap charging window.

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

## Battery economics

The configured optimisation duration is applied to equal-length, contiguous
charge and discharge windows. The integration considers only ordered pairs: the
charge window must finish before the discharge window starts. It then maximises:

```text
arbitrage value = later average import price
                  - charge average import price / round-trip efficiency
```

The effective battery cost sensor applies the same efficiency loss to the
current import price. Solar storage value compares exporting one kWh now with
storing it for the most valuable later usage window:

```text
solar storage value = later average import price × round-trip efficiency
                      - current export price
```

Values may be negative. The opportunity sensors expose `profitable` or
`worth_storing` attributes so an automation can distinguish a recommendation
from the least-bad unprofitable window. Calculations use the currently available
day-ahead forecast and do not control a battery. The forecast-value sensors do
not opt in to Home Assistant's long-term measurement statistics.

The separate battery plan takes a delivered-energy target (default 10 kWh),
maximum grid charging power (default 3 kW), maximum battery output power
(default 2.4 kW), and round-trip efficiency. All three new values are editable
on the second screen under **Settings → Devices & services → Dutch Energy Prices
→ Configure**. It finds ordered, contiguous 15-minute charging and discharging
windows, using full power except for one partial slot in each window. The
window sensors expose per-slot `energy_kwh` and `power_kw`; the plan value is
the estimated total savings in euros. At 85% efficiency, delivering 10 kWh
requires approximately 11.765 kWh from the grid: 16 charging slots at up to
3 kW and 17 discharging slots at up to 2.4 kW.

This is a price and power feasibility estimate. It assumes the battery has
room to charge and that household demand can consume all planned output. The
integration does not yet read battery state of charge, usable capacity or a
household-load forecast. If household demand is lower than battery output,
actual savings will be lower; export revenue, import/export constraints, solar
forecast and battery control are outside this plan.

### Rolling recommendation

On the second configuration screen you can optionally select a battery level
sensor reporting percent and a household load sensor reporting W or kW. Also
configure usable battery capacity, a minimum reserve percentage and an
additional reserve buffer in kWh. Existing installations retain all earlier
sensors when these optional entities are not selected.

The rolling action sensor recommends `charge`, `discharge` or `hold` for the
remaining portion of the current 15-minute slot. It considers only complete
contiguous charging windows, charging power, round-trip efficiency and
profitable later import avoidance. A discharge recommendation cannot exceed
the live household load or configured output power; it preserves the minimum
reserve plus an estimate of household use until the next available cheap
charging window. Attributes include the reserve, currently available energy,
suggested power, and estimated value for the slot. It updates on quarter-hour
boundaries and on changes to either telemetry sensor.

This is a **read-only estimate**, not a battery automation. It treats the
current household load as a constant baseline until the next cheap period;
that is not a load forecast. It does not account for solar production, future
household load changes, standby losses or battery wear. If the telemetry is
invalid or price coverage is missing, the sensor is unavailable instead of
recommending an action. Review its recommendations before using them in an
automation. Battery controls remain outside the integration.

## Roadmap

Future providers can implement `PriceProvider` without changing Dutch pricing logic. Planned candidates include Nord Pool and supplier adapters.

## Development

```bash
python -m pip install pytest ruff
pytest
ruff check .
ruff format --check .
```
