"""The Liftosaur integration: your Liftosaur dashboards as Home Assistant sensors."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import LiftosaurApi
from .backfill import async_backfill, async_clear_store
from .const import ATTR_CONFIG_ENTRY_ID, DOMAIN, LOGGER, SERVICE_BACKFILL
from .coordinator import LiftosaurConfigEntry, LiftosaurCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

BACKFILL_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _backfill(call: ServiceCall) -> ServiceResponse:
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        entries = [
            e
            for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if entry_id is None or e.entry_id == entry_id
        ]
        if not entries:
            raise ServiceValidationError("No loaded Liftosaur entry matches")
        total = 0
        for entry in entries:
            await entry.runtime_data.async_refresh()
            total += await async_backfill(hass, entry, force=True)
        return {"sensors_backfilled": total}

    hass.services.async_register(
        DOMAIN,
        SERVICE_BACKFILL,
        _backfill,
        schema=BACKFILL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LiftosaurConfigEntry) -> bool:
    api = LiftosaurApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = LiftosaurCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    async def _backfill_new(*_: object) -> None:
        try:
            await async_backfill(hass, entry)
        except Exception:  # noqa: BLE001 - never break setup over history
            LOGGER.exception("Liftosaur backfill failed")

    # Backfill in the background once entities exist, and again whenever a
    # refresh brings new or changed series (already-done ones are skipped).
    entry.async_create_background_task(hass, _backfill_new(), f"{DOMAIN}_backfill")

    def _on_update() -> None:
        entry.async_create_background_task(hass, _backfill_new(), f"{DOMAIN}_backfill")

    entry.async_on_unload(coordinator.async_add_listener(_on_update))
    return True


async def _options_updated(hass: HomeAssistant, entry: LiftosaurConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LiftosaurConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: LiftosaurConfigEntry) -> None:
    await async_clear_store(hass, entry.entry_id)
