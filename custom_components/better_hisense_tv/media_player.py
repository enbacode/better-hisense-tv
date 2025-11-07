from __future__ import annotations
import logging
from typing import Any
import asyncio
import wakeonlan

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, ATTR_ATTRIBUTION, STATE_IDLE, STATE_PLAYING, STATE_PAUSED

from custom_components.better_hisense_tv.tv_controller import HisenseTVController

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Hisense TV media_player entity safely."""
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        _LOGGER.warning("Domain %s not initialized yet", DOMAIN)
        return

    data = domain_data.get(entry.entry_id)
    if not data:
        _LOGGER.warning("No entry data found for %s (entry_id=%s)", DOMAIN, entry.entry_id)
        return

    controller = data.get("controller")
    coordinator = data.get("coordinator")

    if not controller or not coordinator:
        _LOGGER.warning("Controller or coordinator missing for %s", DOMAIN)
        return

    async_add_entities([HisenseTVEntity(controller, coordinator)], True)


class HisenseTVEntity(MediaPlayerEntity):
    """Representation of a Hisense TV as a media_player entity."""

    _attr_name = "Hisense TV"
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, controller: HisenseTVController, coordinator):
        self._controller = controller
        self._coordinator = coordinator
        self._attr_unique_id = controller.client_id or "hisense_tv"
        self._state = STATE_UNKNOWN
        self._volume = None
        self._sources: list[str] = []
        self._apps: list[dict] = []
        self._current_source: str | None = None
        self._current_app: str | None = None
        self._muted: bool = False
        self._title: str | None = None

    async def async_update(self):

        if not self._controller.is_connected:
            _LOGGER.debug("TV not connected, assuming OFF.")
            self._state = STATE_OFF
            return

        try:
            self._coordinator.data = await self._controller.get_tv_state()
        except Exception as e:
            _LOGGER.debug("TV state not available: %s", e)
            self._state = STATE_OFF
            return

        data = self._coordinator.data or {}
        if data.get("statetype") == "fake_sleep_0":
            self._state = STATE_OFF
        else:
            self._state = STATE_ON
            
        self._state = STATE_ON
        self._volume = (data.get("volume") or {}).get("volumevalue", 0) / 100
        self._sources = data.get("sources") or []
        self._apps = data.get("apps") or []
        

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
        """Return the current volume (0–1)."""
        if self._volume is not None:
            return self._volume
        return None

    async def async_turn_on(self):
        _LOGGER.debug("Turning on Hisense TV")
        await self._coordinator.async_request_refresh()
        
        try:
            if self._controller.is_connected:
                await self._controller.turn_on()
            else:
                _LOGGER.debug("TV not connected — sending Wake-on-LAN packet.")
                wakeonlan.send_magic_packet(
                    "bc:5c:17:da:bc:5e", ip_address=self._controller.tv_ip
                )
            self._state = STATE_ON
        except Exception as e:
            _LOGGER.warning("Unable to turn on TV: %s", e)
        finally:
            await self._coordinator.async_request_refresh()

    async def async_turn_off(self):
        _LOGGER.debug("Turning off Hisense TV")
        await self._controller.turn_off()
        self._coordinator.data = await self._controller.get_tv_state()
        await self._coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float):
        """Set the volume level (0-1)."""
        await self._controller.change_volume(volume * 100)
        self._volume = volume
        await self._coordinator.async_request_refresh()

    async def async_volume_up(self):
        """Volume up the media player."""
        if self._volume < 100:
            self._volume = self._volume + 1
        await self._controller.send_key("KEY_VOLUMEUP")

    async def async_volume_down(self):
        """Volume down media player."""
        if self._volume > 0:
            self._volume = self._volume - 1
        await self._controller.send_key("KEY_VOLUMEDOWN")

    async def async_mute_volume(self, mute):
        """Send mute command."""
        self._muted = mute
        await self._controller.send_key("KEY_MUTE")

    async def async_media_play(self):
        await self._controller.send_key("KEY_PLAY")
        self._state = STATE_PLAYING

    async def async_media_pause(self):
        await self._controller.send_key("KEY_PAUSE")
        self._state = STATE_PAUSED

    async def async_media_stop(self):
        await self._controller.send_key("KEY_STOP")
        self._state = STATE_IDLE

    @property
    def source_list(self):
        """Return cached list of available sources."""
        return [
            *[s.get("displayname") for s in self._sources],
            *[s.get("name") for s in self._apps]
        ]

    @property
    def source(self):
        """Return currently selected source."""
        return self._current_source or self._current_app

    async def async_select_source(self, source: str):

        src = next((x for x in self._apps if x["name"] == source), None)
        if src is not None:
            await self._controller.launch_app(src["name"])
            self._current_app = src
            self._current_source = None
        else:
            src = next(x for x in self._sources if x["displayname"] == source)
            await self._controller.change_source(src["sourceid"])
            self._current_source = src
            self._current_app = None
        await self._coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_ATTRIBUTION: "Better Hisense TV integration",
            "client_id": self._controller.client_id,
            "username": self._controller.username,
            "ip_address": self._controller.tv_ip,
            "password": self._controller.password,
        }
