"""Opt-in control through generic Home Assistant switch and number entities."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_CHARGE_POWER_ENTITY,
    CONF_CHARGE_TASK_ENTITY,
    CONF_CONTROL_DRY_RUN,
    CONF_DISCHARGE_POWER_ENTITY,
    CONF_DISCHARGE_TASK_ENTITY,
    CONF_MANUAL_OVERRIDE_ENTITY,
)
from ..coordinator import DutchEnergyPricesCoordinator
from ..rolling_plan import ActionStabilizer
from .base import ControlCommand, controllable_action


class GenericBatteryController:
    """Apply stable commands without depending on a battery manufacturer."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DutchEnergyPricesCoordinator,
        config: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.dry_run = bool(config.get(CONF_CONTROL_DRY_RUN, True))
        self.charge_task = config.get(CONF_CHARGE_TASK_ENTITY)
        self.discharge_task = config.get(CONF_DISCHARGE_TASK_ENTITY)
        self.charge_power = config.get(CONF_CHARGE_POWER_ENTITY)
        self.discharge_power = config.get(CONF_DISCHARGE_POWER_ENTITY)
        self.manual_override = config.get(CONF_MANUAL_OVERRIDE_ENTITY)
        self.stabilizer = ActionStabilizer(
            confirmations=coordinator.settings.action_confirmation_updates,
            minimum_dwell=timedelta(minutes=coordinator.settings.minimum_action_minutes),
        )
        self.last_command: ControlCommand | None = None
        self.status = "dry_run" if self.dry_run else "ready"

    async def async_update(self) -> None:
        """Apply the current slot only after telemetry and hysteresis checks."""
        if not self.dry_run and not (self.charge_task or self.discharge_task):
            self.status = "not_configured"
            return
        now = dt_util.utcnow()
        plan = self.coordinator.optimized_plan()
        battery = self.coordinator.battery_snapshot()
        if plan is None or battery is None:
            command = ControlCommand("hold", Decimal("0"), "Battery telemetry unavailable")
        else:
            slot = next((item for item in plan.slots if item.start <= now < item.end), None)
            raw_action = slot.action if slot is not None else "hold"
            proposed = controllable_action(raw_action)
            action = self.stabilizer.update(proposed, now) or "hold"
            if action != proposed:
                self.status = f"pending_{proposed}"
                return
            remaining = (
                Decimal(str((slot.end - now).total_seconds())) / Decimal("3600")
                if slot is not None
                else Decimal("0")
            )
            energy = Decimal("0")
            if slot is not None:
                energy = (
                    slot.grid_charge_kwh + slot.solar_charge_kwh
                    if action == "charge"
                    else slot.self_discharge_kwh + slot.export_discharge_kwh
                )
            power = energy / remaining if remaining > 0 else Decimal("0")
            command = ControlCommand(action, power, plan.reason)

        if self._manual_override_active():
            self.status = "manual_override"
            return
        if command == self.last_command:
            return
        self.last_command = command
        if self.dry_run:
            self.status = f"dry_run_{command.action}"
            return
        await self._async_apply(command)
        self.status = command.action

    def _manual_override_active(self) -> bool:
        if not self.manual_override:
            return False
        state = self.hass.states.get(self.manual_override)
        return state is not None and state.state == "on"

    async def _async_apply(self, command: ControlCommand) -> None:
        if command.action == "charge":
            await self._async_switch(self.discharge_task, False)
            await self._async_number(self.charge_power, command.power_kw)
            await self._async_switch(self.charge_task, True)
        elif command.action == "discharge":
            await self._async_switch(self.charge_task, False)
            await self._async_number(self.discharge_power, command.power_kw)
            await self._async_switch(self.discharge_task, True)
        else:
            await self._async_switch(self.charge_task, False)
            await self._async_switch(self.discharge_task, False)

    async def _async_switch(self, entity_id: str | None, enabled: bool) -> None:
        if not entity_id:
            return
        await self.hass.services.async_call(
            "switch",
            "turn_on" if enabled else "turn_off",
            {"entity_id": entity_id},
            blocking=True,
        )

    async def _async_number(self, entity_id: str | None, power_kw: Decimal) -> None:
        if not entity_id:
            return
        state = self.hass.states.get(entity_id)
        unit = state.attributes.get("unit_of_measurement") if state else None
        value = power_kw * Decimal("1000") if unit == "W" else power_kw
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": float(value)},
            blocking=True,
        )
