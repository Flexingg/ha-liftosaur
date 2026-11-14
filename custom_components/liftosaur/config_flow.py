"""Config and options flows for Liftosaur."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .api import (
    LiftosaurApi,
    LiftosaurAuthError,
    LiftosaurError,
    LiftosaurSubscriptionError,
)
from .const import (
    CONF_BACKFILL_WEEKS,
    CONF_DASHBOARDS,
    CONF_SCAN_INTERVAL,
    CONF_WORKOUT_END,
    CONF_WORKOUT_INTERVAL,
    CONF_WORKOUT_START,
    CONF_WORKOUT_WINDOW,
    DEFAULT_BACKFILL_WEEKS,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_WORKOUT_END,
    DEFAULT_WORKOUT_INTERVAL,
    DEFAULT_WORKOUT_START,
    DOMAIN,
    LOGGER,
    MAX_BACKFILL_WEEKS,
    MAX_WORKOUT_INTERVAL,
    MIN_SCAN_MINUTES,
)

KEY_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


async def _validate(hass, api_key: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    api = LiftosaurApi(async_get_clientsession(hass), api_key.strip())
    try:
        return {}, await api.list_dashboards()
    except LiftosaurAuthError:
        return {"base": "invalid_auth"}, []
    except LiftosaurSubscriptionError:
        return {"base": "no_subscription"}, []
    except LiftosaurError:
        LOGGER.debug("Cannot reach Liftosaur", exc_info=True)
        return {"base": "cannot_connect"}, []


def _key_id(api_key: str) -> str:
    return hashlib.sha256(api_key.strip().encode()).hexdigest()[:16]


class LiftosaurConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Liftosaur with an API key."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            errors, _ = await _validate(self.hass, key)
            if not errors:
                await self.async_set_unique_id(_key_id(key))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Liftosaur", data={CONF_API_KEY: key})
        return self.async_show_form(step_id="user", data_schema=KEY_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            errors, _ = await _validate(self.hass, key)
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: key}
                )
        return self.async_show_form(step_id="reauth_confirm", data_schema=KEY_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return LiftosaurOptionsFlow()


class LiftosaurOptionsFlow(OptionsFlow):
    """Pick dashboards, polling interval and backfill depth."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            user_input[CONF_BACKFILL_WEEKS] = int(user_input[CONF_BACKFILL_WEEKS])
            user_input[CONF_WORKOUT_INTERVAL] = int(
                user_input.get(CONF_WORKOUT_INTERVAL, DEFAULT_WORKOUT_INTERVAL)
            )
            if user_input.get(CONF_WORKOUT_WINDOW) and user_input.get(
                CONF_WORKOUT_START, DEFAULT_WORKOUT_START
            ) == user_input.get(CONF_WORKOUT_END, DEFAULT_WORKOUT_END):
                errors[CONF_WORKOUT_END] = "window_empty"
            else:
                return self.async_create_entry(data=user_input)

        validate_errors, dashboards = await _validate(self.hass, self.config_entry.data[CONF_API_KEY])
        errors = {**validate_errors, **errors}
        options = [
            SelectOptionDict(value=d["id"], label=d.get("name") or d["id"]) for d in dashboards
        ]
        current = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DASHBOARDS, default=current.get(CONF_DASHBOARDS, [])
                ): SelectSelector(SelectSelectorConfig(options=options, multiple=True)),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_MINUTES),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_MINUTES,
                        max=1440,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_BACKFILL_WEEKS,
                    default=current.get(CONF_BACKFILL_WEEKS, DEFAULT_BACKFILL_WEEKS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=MAX_BACKFILL_WEEKS,
                        step=1,
                        unit_of_measurement="weeks",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_WORKOUT_WINDOW, default=current.get(CONF_WORKOUT_WINDOW, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_WORKOUT_START,
                    default=current.get(CONF_WORKOUT_START, DEFAULT_WORKOUT_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_WORKOUT_END,
                    default=current.get(CONF_WORKOUT_END, DEFAULT_WORKOUT_END),
                ): TimeSelector(),
                vol.Required(
                    CONF_WORKOUT_INTERVAL,
                    default=current.get(CONF_WORKOUT_INTERVAL, DEFAULT_WORKOUT_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=MAX_WORKOUT_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
