"""Diagnostics for Liftosaur (the API key is redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import LiftosaurConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LiftosaurConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data.data or {}
    return {
        "entry": async_redact_data(entry.as_dict(), {CONF_API_KEY}),
        "dashboards": {
            dash_id: {
                "name": dash.name,
                "errors": dash.errors,
                "text": dash.text,
                "sensors": {k: asdict(s) for k, s in dash.sensors.items()},
            }
            for dash_id, dash in data.items()
        },
    }
