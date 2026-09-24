"""Read-only battery recommendations from 15-minute prices and live telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from .calculations import _contiguous_windows, current_period
from .models import PricePeriod, PriceSettings


@dataclass(frozen=True, slots=True)
class RollingDecision:
    """Recommendation for the remaining part of the current 15-minute slot."""

    action: Literal["charge", "discharge", "hold"]
    reserve_kwh: Decimal
    available_kwh: Decimal
    next_charge_start: datetime
    recommended_power_kw: Decimal
    slot_energy_kwh: Decimal
    estimated_value_eur: Decimal


@dataclass(slots=True)
class ActionStabilizer:
    """Prevent short telemetry changes from repeatedly flipping an action."""

    confirmations: int = 2
    minimum_dwell: timedelta = timedelta(minutes=5)
    action: str | None = None
    action_since: datetime | None = None
    candidate: str | None = None
    candidate_updates: int = 0

    def update(self, proposed: str | None, now: datetime) -> str | None:
        """Publish a change only after confirmation and minimum dwell time."""
        if proposed is None:
            return self.action
        if self.action is None:
            self.action = proposed
            self.action_since = now
            return self.action
        if proposed == self.action:
            self.candidate = None
            self.candidate_updates = 0
            return self.action
        if proposed != self.candidate:
            self.candidate = proposed
            self.candidate_updates = 1
        else:
            self.candidate_updates += 1
        dwell_complete = self.action_since is None or now - self.action_since >= self.minimum_dwell
        if self.candidate_updates >= self.confirmations and dwell_complete:
            self.action = proposed
            self.action_since = now
            self.candidate = None
            self.candidate_updates = 0
        return self.action


def rolling_decision(
    periods: tuple[PricePeriod, ...],
    now: datetime,
    state_of_charge_percent: Decimal,
    household_load_kw: Decimal,
    settings: PriceSettings,
) -> RollingDecision | None:
    """Plan the current slot; never recommend using energy reserved until recharge.

    Household load is treated as a constant baseline, not a forecast. The
    decision assumes all battery discharge offsets imports (no export).
    Missing price coverage or a future charging opportunity yields no action.
    """
    if not 0 <= state_of_charge_percent <= 100 or household_load_kw < 0:
        return None
    current = current_period(periods, now)
    if current is None:
        return None
    energy = settings.battery_target_energy_kwh / settings.battery_round_trip_efficiency
    slot_cap = settings.max_charge_power_kw / Decimal("4")
    slots = int((energy / slot_cap).to_integral_value(rounding=ROUND_CEILING))
    # Include a charge window already in progress; exclude completed windows.
    windows = _contiguous_windows(
        periods, slots, not_before=current.start - timedelta(minutes=15 * (slots - 1))
    )
    next_charge = min(
        (window for window in windows if window.end > now),
        key=lambda window: window.average_import_price,
        default=None,
    )
    if next_charge is None:
        return None
    between = tuple(p for p in periods if current.start <= p.start < next_charge.start)
    if between and (
        between[0].start != current.start
        or between[-1].end != next_charge.start
        or any(a.end != b.start for a, b in zip(between, between[1:], strict=False))
    ):
        return None

    capacity = settings.battery_usable_capacity_kwh
    stored = capacity * state_of_charge_percent / Decimal("100")
    hours_to_charge = Decimal(str((next_charge.start - now).total_seconds())) / Decimal("3600")
    reserve = min(
        capacity,
        capacity * settings.battery_min_reserve_percent / Decimal("100")
        + settings.battery_reserve_buffer_kwh
        + household_load_kw * max(Decimal("0"), hours_to_charge),
    )
    available = max(Decimal("0"), stored - reserve)
    remaining_hours = Decimal(str((current.end - now).total_seconds())) / Decimal("3600")
    charge_cost = next_charge.average_import_price / settings.battery_round_trip_efficiency
    action: Literal["charge", "discharge", "hold"] = "hold"
    power = Decimal("0")
    slot_energy = Decimal("0")
    value = Decimal("0")

    if current.start < next_charge.end and next_charge.start <= now:
        future = [p.import_price for p in periods if p.start >= next_charge.end]
        # Only charge from the grid when a valuable later use is visible.
        if future and max(future) > charge_cost:
            slot_energy = min(
                settings.max_charge_power_kw * remaining_hours,
                (capacity - stored) / settings.battery_round_trip_efficiency,
                energy,
            )
            if slot_energy > 0:
                action = "charge"
                power = slot_energy / remaining_hours
                value = slot_energy * (
                    max(future) * settings.battery_round_trip_efficiency
                    - next_charge.average_import_price
                )
    elif between:
        # Save limited energy for the highest import-price slot before recharging.
        peak = max(between, key=lambda p: p.import_price)
        if peak.start == current.start and current.import_price > charge_cost:
            slot_energy = min(
                available,
                settings.max_discharge_power_kw * remaining_hours,
                household_load_kw * remaining_hours,
            )
            if slot_energy > 0:
                action = "discharge"
                power = slot_energy / remaining_hours
                value = slot_energy * (current.import_price - charge_cost)

    return RollingDecision(action, reserve, available, next_charge.start, power, slot_energy, value)
