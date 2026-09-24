"""Device-independent battery control contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

BatteryAction = Literal["charge", "discharge", "hold"]


@dataclass(frozen=True, slots=True)
class ControlCommand:
    """A bounded request produced by the optimiser."""

    action: BatteryAction
    power_kw: Decimal
    reason: str


class BatteryController(Protocol):
    """Translate a generic command into integration-specific entity calls."""

    async def async_update(self) -> None:
        """Evaluate and safely apply the current recommendation."""


def controllable_action(planned_action: str) -> BatteryAction:
    """Map optimiser actions without turning solar capture into grid charging."""
    if planned_action == "charge":
        return "charge"
    if planned_action == "discharge":
        return "discharge"
    return "hold"
