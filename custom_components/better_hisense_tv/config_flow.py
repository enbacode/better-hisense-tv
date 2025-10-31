from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_IP, CONF_NAME
from homeassistant.core import callback

from .const import DOMAIN
from .tv_controller import HisenseTVController

_LOGGER = logging.getLogger(__name__)


class BetterHisenseTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Better Hisense TV (automatic pairing)."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._ip: str | None = None
        self._controller: HisenseTVController | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: ask for IP address."""
        errors = {}
        if user_input is not None:
            ip = user_input[CONF_IP]
            self._ip = ip

            # initialize controller
            controller = HisenseTVController(ip)
            self._controller = controller

            try:
                _LOGGER.debug("Starting pairing with Hisense TV at %s", ip)
                code_needed = await controller.async_start_pairing()
                if code_needed:
                    return await self.async_step_authcode()
                else:
                    errors["base"] = "pairing_failed"
            except Exception as e:
                _LOGGER.error("Failed to connect to TV at %s: %s", ip, e)
                errors["base"] = "connection_failed"

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default="Hisense TV"): str,
            vol.Required(CONF_IP): str,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_authcode(self, user_input=None):
        """Step 2: user enters the 4-digit code from the TV screen."""
        errors = {}
        if user_input is not None:
            auth_code = user_input["auth_code"]

            try:
                credentials = await self._controller.async_finish_pairing(auth_code)
                if credentials:
                    return self.async_create_entry(
                        title=f"Hisense TV ({self._ip})",
                        data={
                            "ip": self._ip,
                            "credentials": credentials,
                        },
                    )
                errors["base"] = "auth_failed"
            except Exception as e:
                _LOGGER.error("Authentication failed: %s", e)
                errors["base"] = "auth_failed"

        schema = vol.Schema({
            vol.Required("auth_code", description="Code shown on your TV"): str,
        })
        return self.async_show_form(step_id="authcode", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BetterHisenseTVOptionsFlow(config_entry)


class BetterHisenseTVOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow (edit existing entry)."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Allow changing only the IP address."""
        if user_input is not None:
            data = self.config_entry.data.copy()
            data["ip"] = user_input["ip"]
            return self.async_create_entry(title="", data=data)

        schema = vol.Schema({
            vol.Required("ip", default=self.config_entry.data.get("ip", "")): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
