from __future__ import annotations
import logging
from typing import Any
import asyncio

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    DEVICE_CLASS_TV
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, ATTR_ATTRIBUTION, STATE_IDLE, STATE_PLAYING, STATE_PAUSED

from custom_components.better_hisense_tv.tv_controller import HisenseTVController

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
        self._coordinator.data = await self._controller.get_tv_state()
        statetype = self._coordinator.data.get("statetype")

        try:
            src_list = await self._controller.get_source_list()
            self._sources = [s for s in src_list if s]
        except Exception as e:
            _LOGGER.debug("Failed to update source list: %s", e)

        try:
            app_list = await self._controller.get_app_list()
            self._apps = [s for s in app_list if s]
        except Exception as e:
            _LOGGER.debug("Failed to update source list: %s", e)

        if statetype == "fake_sleep_0":
            self._state = STATE_OFF
        else:
            self._state = STATE_ON

        if statetype == "app":
            self._current_app = self._coordinator.data.get("name")
            self._title = self._current_app
            self.state = STATE_PLAYING
        elif statetype == "sourceswitch":
            self._current_source = self._coordinator.data.get("displayname")
            self._title = self._current_source
            self.state = STATE_PLAYING
        
        await self._coordinator.async_request_refresh()

    @property
    def device_class(self):
        """Set the device class to TV."""
        _LOGGER.debug("device_class")
        return DEVICE_CLASS_TV
    
    @property
    def media_title(self):
        """Return the title of current playing media."""
        if self._state == STATE_OFF:
            return None

        return self._title

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
        await self._controller.turn_on()
        self._coordinator.data = await self._controller.get_tv_state()
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
        self.state = STATE_PLAYING

    async def async_media_pause(self):
        await self._controller.send_key("KEY_PAUSE")
        self.state = STATE_PAUSED

    async def async_media_stop(self):
        await self._controller.send_key("KEY_STOP")
        self.state = STATE_IDLE

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
