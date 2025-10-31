from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, ATTR_ATTRIBUTION

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    controller = data["controller"]
    coordinator = data["coordinator"]

    async_add_entities([HisenseTVEntity(controller, coordinator)], True)


class HisenseTVEntity(MediaPlayerEntity):
    """Representation of a Hisense TV as a media_player entity."""

    _attr_name = "Hisense TV"
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
    )

    def __init__(self, controller, coordinator):
        self._controller = controller
        self._coordinator = coordinator
        self._attr_unique_id = controller.client_id or "hisense_tv"
        self._state = STATE_UNKNOWN
        self._volume = None

    async def async_update(self):
        await self._coordinator.async_request_refresh()

    @property
    def state(self):
        data = self._coordinator.data or {}
        if not data:
            return self._state
        if data.get("statetype") == "fake_sleep_0":
            self._state = STATE_OFF
        else:
            self._state = STATE_ON
        return self._state

    @property
    def volume_level(self) -> float | None:
        """Return the current volume (0.0–1.0)."""
        if self._volume is not None:
            return self._volume
        return None

    async def async_turn_on(self):
        _LOGGER.debug("Turning on Hisense TV")
        await self._controller.async_turn_on()
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self):
        _LOGGER.debug("Turning off Hisense TV")
        await self._controller.async_turn_off()
        await self._coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float):
        """Set the volume level (0.0–1.0)."""
        level = int(volume * 100)
        await self._controller.async_set_volume(level)
        self._volume = volume
        await self._coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_ATTRIBUTION: "Better Hisense TV integration",
            "client_id": self._controller.client_id,
        }
