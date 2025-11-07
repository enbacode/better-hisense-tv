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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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


class HisenseTVEntity(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a Hisense TV as a media_player entity."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, controller: HisenseTVController, coordinator):
        """Initialize the Hisense TV entity."""
        super().__init__(coordinator)
        self._controller = controller
        self._attr_unique_id = f"hisense_tv_{controller.client_id or 'unknown'}"
        self._attr_name = "Hisense TV"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, controller.client_id or "unknown")},
            "name": "Hisense TV",
            "manufacturer": "Hisense",
            "model": "VIDAa TV",
        }

    @property
    def state(self):
        """Return the state of the device."""
        if not self.coordinator.data:
            return STATE_UNKNOWN
        
        if not self._controller.is_connected:
            return STATE_OFF
            
        data = self.coordinator.data
        if data.get("statetype") == "fake_sleep_0":
            return STATE_OFF
        
        return STATE_ON

    @property
    def volume_level(self) -> float | None:
        """Return the current volume (0–1)."""
        if not self.coordinator.data:
            return None
        
        volume_data = self.coordinator.data.get("volume")
        if volume_data and "volumevalue" in volume_data:
            return volume_data["volumevalue"] / 100.0
        return None

    @property
    def is_volume_muted(self) -> bool | None:
        """Return boolean if volume is currently muted."""
        if not self.coordinator.data:
            return None
        
        volume_data = self.coordinator.data.get("volume")
        if volume_data:
            return volume_data.get("mute", False)
        return None

    @property
    def source_list(self):
        """Return cached list of available sources."""
        if not self.coordinator.data:
            return []
        
        sources = self.coordinator.data.get("sources") or []
        apps = self.coordinator.data.get("apps") or []
        
        source_names = [s.get("displayname") for s in sources if s.get("displayname")]
        app_names = [a.get("name") for a in apps if a.get("name")]
        
        return source_names + app_names

    @property
    def source(self):
        """Return currently selected source."""
        if not self.coordinator.data:
            return None
        
        data = self.coordinator.data
        
        # Try to get current source from TV state
        current_source_id = data.get("sourceid")
        if current_source_id:
            sources = data.get("sources") or []
            for src in sources:
                if src.get("sourceid") == current_source_id:
                    return src.get("displayname")
        
        return None

    async def async_turn_on(self):
        """Turn the TV on."""
        _LOGGER.debug("Turning on Hisense TV")
        
        try:
            if self._controller.is_connected:
                await self._controller.turn_on()
            else:
                # Fallback to Wake-on-LAN
                _LOGGER.debug("TV not connected — sending Wake-on-LAN packet.")
                # TODO: Make MAC address configurable
                wakeonlan.send_magic_packet(
                    "bc:5c:17:da:bc:5e", ip_address=self._controller.tv_ip
                )
            
            # Wait a bit for TV to wake up
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Unable to turn on TV: %s", e)

    async def async_turn_off(self):
        """Turn the TV off."""
        _LOGGER.debug("Turning off Hisense TV")
        try:
            await self._controller.turn_off()
            await asyncio.sleep(1)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Unable to turn off TV: %s", e)

    async def async_set_volume_level(self, volume: float):
        """Set the volume level (0-1)."""
        try:
            volume_int = int(volume * 100)
            await self._controller.change_volume(volume_int)
            # Small delay before refresh
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Unable to set volume: %s", e)

    async def async_volume_up(self):
        """Volume up the media player."""
        try:
            await self._controller.send_key("KEY_VOLUMEUP")
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Unable to increase volume: %s", e)

    async def async_volume_down(self):
        """Volume down media player."""
        try:
            await self._controller.send_key("KEY_VOLUMEDOWN")
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Unable to decrease volume: %s", e)

    async def async_mute_volume(self, mute):
        """Send mute command."""
        try:
            await self._controller.send_key("KEY_MUTE")
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error("Unable to mute/unmute: %s", e)

    async def async_media_play(self):
        """Send play command."""
        try:
            await self._controller.send_key("KEY_PLAY")
        except Exception as e:
            _LOGGER.error("Unable to send play command: %s", e)

    async def async_media_pause(self):
        """Send pause command."""
        try:
            await self._controller.send_key("KEY_PAUSE")
        except Exception as e:
            _LOGGER.error("Unable to send pause command: %s", e)

    async def async_media_stop(self):
        """Send stop command."""
        try:
            await self._controller.send_key("KEY_STOP")
        except Exception as e:
            _LOGGER.error("Unable to send stop command: %s", e)

    async def async_select_source(self, source: str):
        """Select input source."""
        try:
            if not self.coordinator.data:
                _LOGGER.warning("No coordinator data available")
                return
            
            sources = self.coordinator.data.get("sources") or []
            apps = self.coordinator.data.get("apps") or []
            
            # Try to find in apps first
            app = next((a for a in apps if a.get("name") == source), None)
            if app:
                await self._controller.launch_app(app["name"], apps)
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                return
            
            # Try to find in sources
            src = next((s for s in sources if s.get("displayname") == source), None)
            if src:
                await self._controller.change_source(src["sourceid"])
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                return
            
            _LOGGER.warning("Source '%s' not found", source)
            
        except Exception as e:
            _LOGGER.error("Unable to select source: %s", e)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            ATTR_ATTRIBUTION: "Better Hisense TV integration",
            "client_id": self._controller.client_id,
            "username": self._controller.username,
            "ip_address": self._controller.tv_ip,
        }
        
        # Add debug info if available
        if self.coordinator.data:
            attrs["statetype"] = self.coordinator.data.get("statetype")
            attrs["connected"] = self._controller.is_connected
        
        return attrs