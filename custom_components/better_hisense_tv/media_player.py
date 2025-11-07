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

    async def _ensure_connection(self) -> bool:
        """Ensure controller is connected before sending commands."""
        if not self._controller.is_connected:
            _LOGGER.info("Controller not connected, attempting to reconnect...")
            try:
                await self._controller.connect_with_access_token()
                _LOGGER.info("Successfully reconnected")
                return True
            except Exception as e:
                _LOGGER.error("Failed to reconnect: %s", e)
                return False
        return True

    @property
    def state(self):
        """Return the state of the device."""
        if not self.coordinator.data:
            _LOGGER.debug("No coordinator data available")
            return STATE_UNKNOWN
        
        if not self._controller.is_connected:
            _LOGGER.debug("Controller not connected, state=OFF")
            return STATE_OFF
            
        data = self.coordinator.data
        statetype = data.get("statetype")
        _LOGGER.debug("TV statetype: %s", statetype)
        
        if statetype == "fake_sleep_0":
            return STATE_OFF
        
        return STATE_ON

    @property
    def volume_level(self) -> float | None:
        """Return the current volume (0–1)."""
        if not self.coordinator.data:
            return None
        
        volume_data = self.coordinator.data.get("volume")
        if volume_data and "volumevalue" in volume_data:
            vol = volume_data["volumevalue"] / 100.0
            _LOGGER.debug("Current volume level: %s", vol)
            return vol
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
            _LOGGER.debug("No coordinator data for source list")
            return []
        
        sources = self.coordinator.data.get("sources") or []
        apps = self.coordinator.data.get("apps") or []
        
        _LOGGER.debug("Available sources: %s, apps: %s", len(sources), len(apps))
        
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
        _LOGGER.info("=== TURN ON command received ===")
        _LOGGER.info("Controller connected: %s", self._controller.is_connected)
        _LOGGER.info("Controller client_id: %s", self._controller.client_id)
        _LOGGER.info("Controller username: %s", self._controller.username)
        _LOGGER.info("Controller IP: %s", self._controller.tv_ip)
        
        try:
            # Check current state
            current_state = await self._controller.get_tv_state()
            _LOGGER.info("Current TV state before turn_on: %s", current_state)
            
            if not await self._ensure_connection():
                _LOGGER.error("Cannot turn on TV - connection failed")
                return
            
            _LOGGER.info("Sending power_cycle_tv command...")
            await self._controller.power_cycle_tv()
            _LOGGER.info("Power cycle command sent successfully")
            
            # Wait for TV to respond
            await asyncio.sleep(3)
            
            # Check new state
            new_state = await self._controller.get_tv_state()
            _LOGGER.info("TV state after turn_on: %s", new_state)
            
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning on TV: %s", e, exc_info=True)

    async def async_turn_off(self):
        """Turn the TV off."""
        _LOGGER.info("=== TURN OFF command received ===")
        _LOGGER.info("Controller connected: %s", self._controller.is_connected)
        
        try:
            # Check current state
            current_state = await self._controller.get_tv_state()
            _LOGGER.info("Current TV state before turn_off: %s", current_state)
            
            if not await self._ensure_connection():
                _LOGGER.error("Cannot turn off TV - connection failed")
                return
            
            _LOGGER.info("Sending power_cycle_tv command...")
            await self._controller.power_cycle_tv()
            _LOGGER.info("Power cycle command sent successfully")
            
            await asyncio.sleep(2)
            
            # Check new state
            new_state = await self._controller.get_tv_state()
            _LOGGER.info("TV state after turn_off: %s", new_state)
            
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning off TV: %s", e, exc_info=True)

    async def async_set_volume_level(self, volume: float):
        """Set the volume level (0-1)."""
        _LOGGER.info("=== SET VOLUME command received: %.2f ===", volume)
        
        try:
            if not await self._ensure_connection():
                _LOGGER.error("Cannot set volume - connection failed")
                return
            
            volume_int = int(volume * 100)
            _LOGGER.info("Setting volume to: %d", volume_int)
            
            result = await self._controller.change_volume(volume_int)
            _LOGGER.info("Volume change result: %s", result)
            
            await asyncio.sleep(0.5)
            
            # Check new volume
            new_volume = await self._controller.get_volume()
            _LOGGER.info("Volume after change: %s", new_volume)
            
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error setting volume: %s", e, exc_info=True)

    async def async_volume_up(self):
        """Volume up the media player."""
        _LOGGER.info("=== VOLUME UP command received ===")
        
        try:
            if not await self._ensure_connection():
                _LOGGER.error("Cannot volume up - connection failed")
                return
            
            result = await self._controller.send_key("KEY_VOLUMEUP")
            _LOGGER.info("Volume up result: %s", result)
            
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error volume up: %s", e, exc_info=True)

    async def async_volume_down(self):
        """Volume down media player."""
        _LOGGER.info("=== VOLUME DOWN command received ===")
        
        try:
            if not await self._ensure_connection():
                _LOGGER.error("Cannot volume down - connection failed")
                return
            
            result = await self._controller.send_key("KEY_VOLUMEDOWN")
            _LOGGER.info("Volume down result: %s", result)
            
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error volume down: %s", e, exc_info=True)

    async def async_mute_volume(self, mute):
        """Send mute command."""
        _LOGGER.info("=== MUTE command received: %s ===", mute)
        
        try:
            if not await self._ensure_connection():
                _LOGGER.error("Cannot mute - connection failed")
                return
            
            result = await self._controller.send_key("KEY_MUTE")
            _LOGGER.info("Mute result: %s", result)
            
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error muting: %s", e, exc_info=True)

    async def async_media_play(self):
        """Send play command."""
        _LOGGER.info("=== PLAY command received ===")
        
        try:
            if not await self._ensure_connection():
                return
            
            result = await self._controller.send_key("KEY_PLAY")
            _LOGGER.info("Play result: %s", result)
            
        except Exception as e:
            _LOGGER.error("Error sending play: %s", e, exc_info=True)

    async def async_media_pause(self):
        """Send pause command."""
        _LOGGER.info("=== PAUSE command received ===")
        
        try:
            if not await self._ensure_connection():
                return
            
            result = await self._controller.send_key("KEY_PAUSE")
            _LOGGER.info("Pause result: %s", result)
            
        except Exception as e:
            _LOGGER.error("Error sending pause: %s", e, exc_info=True)

    async def async_media_stop(self):
        """Send stop command."""
        _LOGGER.info("=== STOP command received ===")
        
        try:
            if not await self._ensure_connection():
                return
            
            result = await self._controller.send_key("KEY_STOP")
            _LOGGER.info("Stop result: %s", result)
            
        except Exception as e:
            _LOGGER.error("Error sending stop: %s", e, exc_info=True)

    async def async_select_source(self, source: str):
        """Select input source."""
        _LOGGER.info("=== SELECT SOURCE command received: %s ===", source)
        
        try:
            if not await self._ensure_connection():
                _LOGGER.error("Cannot select source - connection failed")
                return
            
            if not self.coordinator.data:
                _LOGGER.warning("No coordinator data available")
                return
            
            sources = self.coordinator.data.get("sources") or []
            apps = self.coordinator.data.get("apps") or []
            
            _LOGGER.info("Searching in %d sources and %d apps", len(sources), len(apps))
            
            # Try to find in apps first
            app = next((a for a in apps if a.get("name") == source), None)
            if app:
                _LOGGER.info("Found app: %s", app)
                result = await self._controller.launch_app(app["name"], apps)
                _LOGGER.info("Launch app result: %s", result)
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                return
            
            # Try to find in sources
            src = next((s for s in sources if s.get("displayname") == source), None)
            if src:
                _LOGGER.info("Found source: %s", src)
                result = await self._controller.change_source(src["sourceid"])
                _LOGGER.info("Change source result: %s", result)
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                return
            
            _LOGGER.warning("Source '%s' not found in available sources/apps", source)
            
        except Exception as e:
            _LOGGER.error("Error selecting source: %s", e, exc_info=True)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        attrs = {
            ATTR_ATTRIBUTION: "Better Hisense TV integration",
            "client_id": self._controller.client_id,
            "username": self._controller.username,
            "ip_address": self._controller.tv_ip,
            "is_connected": self._controller.is_connected,
        }
        
        # Add debug info if available
        if self.coordinator.data:
            attrs["statetype"] = self.coordinator.data.get("statetype")
            attrs["raw_data"] = str(self.coordinator.data)
        
        # Add topic paths for debugging
        if hasattr(self._controller, 'topicRemoBasepath'):
            attrs["topic_remo"] = self._controller.topicRemoBasepath
            attrs["topic_tvui"] = self._controller.topicTVUIBasepath
            attrs["topic_tvps"] = self._controller.topicTVPSBasepath
        
        return attrs