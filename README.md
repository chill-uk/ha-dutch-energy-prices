# Dutch Energy Prices

A Home Assistant custom integration for Dutch dynamic electricity contracts, designed around native **15-minute** prices and the post-saldering market from 2027 onward.

## v0.1 scope

- Retrieves Dutch day-ahead prices directly from ENTSO-E or consumes native
  15-minute prices from an existing Home Assistant sensor.
- Keeps all monetary values internally as `Decimal` EUR/kWh.
- Calculates raw market, all-in import, export, energy-tax and import/export-spread sensors.
- Finds the cheapest contiguous 15-minute, 1-hour and 2-hour windows without hourly aggregation.
- Exposes today and tomorrow on the market-price sensor only, avoiding duplicate large attributes.
- Provides editable Netherlands 2026, provisional Netherlands 2027 and custom tax profiles.
- Includes diagnostics, translations, tests, Ruff and HACS metadata.

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

## Installation

### HACS custom repository

1. Add this repository to HACS as an Integration repository.
2. Install **Dutch Energy Prices**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**.
5. Select **Dutch Energy Prices** and choose **ENTSO-E** or a compatible
   15-minute source sensor.

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

Home Assistant may append a suffix if one of these entity IDs already exists.

## Roadmap

v0.2 will expose the already-modelled battery economics: effective charged-energy cost, best charge/discharge periods, grid-arbitrage value, solar opportunity cost and configurable optimisation duration. It will not control a battery until a later, separately reviewed phase.

Future providers can implement `PriceProvider` without changing Dutch pricing logic. Planned candidates include Nord Pool and supplier adapters.

## Development

```bash
python -m pip install pytest ruff
pytest
ruff check .
ruff format --check .
```
