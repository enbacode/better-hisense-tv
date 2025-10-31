from __future__ import annotations
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .tv_controller import HisenseTVController
from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Better Hisense TV from a config entry."""

    ip = entry.data["ip"]
    credentials = entry.data["credentials"]  # dict from config_flow or YAML

    controller = HisenseTVController(ip)
    controller.apply_credentials(credentials)

    async def async_update_data():
        """Fetch TV state periodically."""
        try:
            state = await controller.async_get_state()
            return state or {}
        except Exception as err:
            _LOGGER.warning("Failed to update Hisense TV state: %s", err)
            return {}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Hisense TV Coordinator",
        update_method=async_update_data,
        update_interval=timedelta(seconds=30),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "controller": controller,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload integration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
