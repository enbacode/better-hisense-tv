from __future__ import annotations
import logging
from typing import Any
import asyncio
import wakeonlan

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerDeviceClass,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, ATTR_ATTRIBUTION
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.better_hisense_tv.tv_controller import HisenseTVController

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Hisense TV media_player entity safely."""
    _LOGGER.warning("=== ASYNC_SETUP_ENTRY CALLED FOR MEDIA_PLAYER ===")
    
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        _LOGGER.error("Domain %s not initialized yet", DOMAIN)
        return

    data = domain_data.get(entry.entry_id)
    if not data:
        _LOGGER.error("No entry data found for %s (entry_id=%s)", DOMAIN, entry.entry_id)
        return

    controller = data.get("controller")
    coordinator = data.get("coordinator")

    if not controller or not coordinator:
        _LOGGER.error("Controller or coordinator missing for %s", DOMAIN)
        return

    entity = HisenseTVEntity(controller, coordinator)
    _LOGGER.warning("Creating HisenseTVEntity with unique_id: %s", entity.unique_id)
    
    async_add_entities([entity], True)
    _LOGGER.warning("=== MEDIA_PLAYER ENTITY ADDED ===")


class HisenseTVEntity(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a Hisense TV as a media_player entity."""

    # WICHTIG: Diese Attribute MÜSSEN gesetzt sein
    _attr_has_entity_name = False
    _attr_device_class = MediaPlayerDeviceClass.TV
    
    def __init__(self, controller: HisenseTVController, coordinator):
        """Initialize the Hisense TV entity."""
        super().__init__(coordinator)
        self._controller = controller
        
        # Unique ID ist KRITISCH - ohne diese funktioniert nichts!
        self._attr_unique_id = f"hisense_tv_{controller.client_id}"
        self._attr_name = "Hisense TV"
        
        _LOGGER.warning("=== HisenseTVEntity.__init__ called ===")
        _LOGGER.warning("Unique ID: %s", self._attr_unique_id)
        _LOGGER.warning("Name: %s", self._attr_name)
        _LOGGER.warning("Controller IP: %s", controller.tv_ip)
        _LOGGER.warning("Controller connected: %s", controller.is_connected)

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return self._attr_unique_id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._attr_name

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Entity sollte immer verfügbar sein, auch wenn TV aus ist
        return True

    @property
    def supported_features(self) -> int:
        """Flag media player features that are supported."""
        _LOGGER.debug("supported_features called")
        return (
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
            return []
        
        sources = self.coordinator.data.get("sources") or []
        apps = self.coordinator.data.get("apps") or []
        
        source_names = [s.get("displayname") for s in sources if s.get("displayname")]
        app_names = [a.get("name") for a in apps if a.get("name")]
        
        result = source_names + app_names
        _LOGGER.debug("source_list property called, returning %d sources", len(result))
        return result

    @property
    def source(self):
        """Return currently selected source."""
        if not self.coordinator.data:
            return None
        
        data = self.coordinator.data
        current_source_id = data.get("sourceid")
        if current_source_id:
            sources = data.get("sources") or []
            for src in sources:
                if src.get("sourceid") == current_source_id:
                    return src.get("displayname")
        
        return None

    async def async_turn_on(self):
        """Turn the TV on."""
        _LOGGER.warning("=== ASYNC_TURN_ON CALLED ===")
        _LOGGER.warning("Controller connected: %s", self._controller.is_connected)
        _LOGGER.warning("Controller IP: %s", self._controller.tv_ip)
        
        try:
            current_state = await self._controller.get_tv_state()
            _LOGGER.warning("Current TV state: %s", current_state)
            
            if not await self._ensure_connection():
                _LOGGER.error("Cannot turn on TV - connection failed")
                return
            
            _LOGGER.warning("Calling power_cycle_tv()...")
            await self._controller.power_cycle_tv()
            _LOGGER.warning("Power cycle command sent")
            
            await asyncio.sleep(3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning on TV: %s", e, exc_info=True)

    async def async_turn_off(self):
        """Turn the TV off."""
        _LOGGER.warning("=== ASYNC_TURN_OFF CALLED ===")
        
        try:
            if not await self._ensure_connection():
                _LOGGER.error("Cannot turn off TV - connection failed")
                return
            
            await self._controller.power_cycle_tv()
            await asyncio.sleep(2)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error turning off TV: %s", e, exc_info=True)

    async def async_set_volume_level(self, volume: float):
        """Set the volume level (0-1)."""
        _LOGGER.warning("=== ASYNC_SET_VOLUME_LEVEL CALLED: %.2f ===", volume)
        
        try:
            if not await self._ensure_connection():
                return
            
            volume_int = int(volume * 100)
            await self._controller.change_volume(volume_int)
            await asyncio.sleep(0.5)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error setting volume: %s", e, exc_info=True)

    async def async_volume_up(self):
        """Volume up the media player."""
        _LOGGER.warning("=== ASYNC_VOLUME_UP CALLED ===")
        
        try:
            if not await self._ensure_connection():
                return
            
            await self._controller.send_key("KEY_VOLUMEUP")
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error volume up: %s", e, exc_info=True)

    async def async_volume_down(self):
        """Volume down media player."""
        _LOGGER.warning("=== ASYNC_VOLUME_DOWN CALLED ===")
        
        try:
            if not await self._ensure_connection():
                return
            
            await self._controller.send_key("KEY_VOLUMEDOWN")
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error volume down: %s", e, exc_info=True)

    async def async_mute_volume(self, mute):
        """Send mute command."""
        _LOGGER.warning("=== ASYNC_MUTE_VOLUME CALLED: %s ===", mute)
        
        try:
            if not await self._ensure_connection():
                return
            
            await self._controller.send_key("KEY_MUTE")
            await asyncio.sleep(0.3)
            await self.coordinator.async_request_refresh()
            
        except Exception as e:
            _LOGGER.error("Error muting: %s", e, exc_info=True)

    async def async_media_play(self):
        """Send play command."""
        _LOGGER.warning("=== ASYNC_MEDIA_PLAY CALLED ===")
        
        try:
            if not await self._ensure_connection():
                return
            await self._controller.send_key("KEY_PLAY")
        except Exception as e:
            _LOGGER.error("Error sending play: %s", e, exc_info=True)

    async def async_media_pause(self):
        """Send pause command."""
        _LOGGER.warning("=== ASYNC_MEDIA_PAUSE CALLED ===")
        
        try:
            if not await self._ensure_connection():
                return
            await self._controller.send_key("KEY_PAUSE")
        except Exception as e:
            _LOGGER.error("Error sending pause: %s", e, exc_info=True)

    async def async_media_stop(self):
        """Send stop command."""
        _LOGGER.warning("=== ASYNC_MEDIA_STOP CALLED ===")
        
        try:
            if not await self._ensure_connection():
                return
            await self._controller.send_key("KEY_STOP")
        except Exception as e:
            _LOGGER.error("Error sending stop: %s", e, exc_info=True)

    async def async_select_source(self, source: str):
        """Select input source."""
        _LOGGER.warning("=== ASYNC_SELECT_SOURCE CALLED: %s ===", source)
        
        try:
            if not await self._ensure_connection():
                return
            
            if not self.coordinator.data:
                _LOGGER.warning("No coordinator data available")
                return
            
            sources = self.coordinator.data.get("sources") or []
            apps = self.coordinator.data.get("apps") or []
            
            # Try apps first
            app = next((a for a in apps if a.get("name") == source), None)
            if app:
                await self._controller.launch_app(app["name"], apps)
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                return
            
            # Try sources
            src = next((s for s in sources if s.get("displayname") == source), None)
            if src:
                await self._controller.change_source(src["sourceid"])
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                return
            
            _LOGGER.warning("Source '%s' not found", source)
            
        except Exception as e:
            _LOGGER.error("Error selecting source: %s", e, exc_info=True)

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._controller.client_id or "unknown")},
            "name": "Hisense TV",
            "manufacturer": "Hisense",
            "model": "VIDAa TV",
        }

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
        
        if self.coordinator.data:
            attrs["statetype"] = self.coordinator.data.get("statetype")
        
        if hasattr(self._controller, 'topicRemoBasepath'):
            attrs["topic_remo"] = self._controller.topicRemoBasepath
            attrs["topic_tvui"] = self._controller.topicTVUIBasepath
        
        return attrs

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.warning("=== ENTITY ADDED TO HASS ===")
        _LOGGER.warning("Entity ID: %s", self.entity_id)
        _LOGGER.warning("Unique ID: %s", self.unique_id)
        _LOGGER.warning("Name: %s", self.name)