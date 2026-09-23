"""Verify Home Assistant update hooks without requiring a full HA installation."""

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from custom_components.dutch_energy_prices import async_setup_entry


@pytest.mark.parametrize("source_entity_id", [None, "sensor.external_prices"])
@pytest.mark.parametrize("telemetry", [False, True])
def test_price_boundaries_and_source_changes_register_once(
    monkeypatch: pytest.MonkeyPatch, source_entity_id: str | None, telemetry: bool
) -> None:
    callbacks = {}

    def track_time(_hass, action, *, minute, second):
        assert list(minute) == [0, 15, 30, 45]
        assert second == 0
        callbacks["boundary"] = action
        return lambda: None

    def track_state(_hass, entity_id, action):
        if isinstance(entity_id, tuple):
            assert entity_id == ("sensor.battery", "sensor.load")
            callbacks["telemetry"] = action
        else:
            assert entity_id == "sensor.external_prices"
            callbacks["source"] = action
        return lambda: None

    class FakeCoordinator:
        def __init__(self, _hass, _entry, provider, _settings):
            self.provider = provider
            self.soc_entity_id = "sensor.battery" if telemetry else None
            self.load_entity_id = "sensor.load" if telemetry else None
            self.listener_updates = 0
            self.source_refreshes = 0

        async def async_config_entry_first_refresh(self):
            return None

        async def async_request_refresh(self):
            self.source_refreshes += 1

        def async_update_listeners(self):
            self.listener_updates += 1

    def fake_module(name: str, **members):
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)

    fake_module("homeassistant")
    fake_module("homeassistant.core", callback=lambda fn: fn)
    fake_module("homeassistant.helpers")
    fake_module(
        "homeassistant.helpers.event",
        async_track_state_change_event=track_state,
        async_track_utc_time_change=track_time,
    )
    fake_module(
        "custom_components.dutch_energy_prices.coordinator",
        DutchEnergyPricesCoordinator=FakeCoordinator,
        settings_from_config=lambda _config: object(),
    )
    provider = SimpleNamespace()
    if source_entity_id is not None:
        provider.source_entity_id = source_entity_id
    fake_module(
        "custom_components.dutch_energy_prices.providers",
        create_provider=lambda _hass, _config: provider,
    )

    class FakeEntry:
        data = {}
        options = {}

        def __init__(self):
            self.unload_callbacks = []

        def add_update_listener(self, _callback):
            return lambda: None

        def async_on_unload(self, callback):
            self.unload_callbacks.append(callback)

    async def run():
        entry = FakeEntry()
        hass = SimpleNamespace(
            async_create_task=asyncio.create_task,
            config_entries=SimpleNamespace(
                async_forward_entry_setups=lambda _entry, _platforms: asyncio.sleep(0)
            ),
        )
        assert await async_setup_entry(hass, entry)
        callbacks["boundary"](object())
        assert entry.runtime_data.listener_updates == 1

        if source_entity_id is not None:
            callbacks["source"](object())
            await asyncio.sleep(0)
            assert entry.runtime_data.source_refreshes == 1
            assert len(entry.unload_callbacks) == 3 + int(telemetry)
        else:
            assert "source" not in callbacks
            assert len(entry.unload_callbacks) == 2 + int(telemetry)
        if telemetry:
            callbacks["telemetry"](object())
            assert entry.runtime_data.listener_updates == 2

    asyncio.run(run())
