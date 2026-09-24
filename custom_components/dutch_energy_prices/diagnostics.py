"""Diagnostics support for Dutch Energy Prices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTSOE_API_TOKEN
from .coordinator import DutchEnergyPricesCoordinator

TO_REDACT = {CONF_ENTSOE_API_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return compact diagnostics without duplicating all price attributes."""
    coordinator: DutchEnergyPricesCoordinator = entry.runtime_data
    periods = coordinator.data.periods
    battery = coordinator.battery_snapshot()
    plan = coordinator.optimized_plan() if battery else None
    return {
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "provider": coordinator.data.provider_name,
        "last_update_success": coordinator.last_update_success,
        "fetched_at": coordinator.data.fetched_at.isoformat(),
        "period_count": len(periods),
        "first_period": periods[0].start.isoformat() if periods else None,
        "last_period": periods[-1].end.isoformat() if periods else None,
        "battery": (
            {
                "bank_count": len(battery.banks),
                "capacity_kwh": str(battery.capacity_kwh),
                "stored_energy_kwh": str(battery.stored_energy_kwh),
                "state_of_charge_percent": str(battery.state_of_charge_percent),
                "banks": [
                    {
                        "name": bank.name,
                        "capacity_kwh": str(bank.capacity_kwh),
                        "stored_energy_kwh": str(bank.stored_energy_kwh),
                        "state_of_health_percent": str(bank.state_of_health_percent),
                        "capacity_source": bank.capacity_source,
                    }
                    for bank in battery.banks
                ],
            }
            if battery
            else None
        ),
        "optimizer": (
            {
                "reason": plan.reason,
                "reserve_kwh": str(plan.reserve_kwh),
                "grid_charge_kwh": str(plan.grid_charge_kwh),
                "solar_charge_kwh": str(plan.solar_charge_kwh),
                "self_discharge_kwh": str(plan.self_discharge_kwh),
                "export_discharge_kwh": str(plan.export_discharge_kwh),
                "net_value_eur": str(plan.net_value_eur),
                "active_slot_count": sum(slot.action != "hold" for slot in plan.slots),
            }
            if plan
            else None
        ),
        "controller_status": (
            coordinator.controller.status if coordinator.controller is not None else "disabled"
        ),
    }
