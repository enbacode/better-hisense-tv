import asyncio
import json
import logging
import time
import random
import re
import uuid
import hashlib
from typing import Optional

import paho.mqtt.client as mqtt
from .keys import hisense_key, hisense_cert

_LOGGER = logging.getLogger(__name__)


class HisenseTVController:
    """Async controller for communicating with Hisense Smart TVs via MQTT."""

    def __init__(
        self,
        ip: str,
        use_random_mac: bool = True,
    ):
        self.tv_ip = ip
        self.use_random_mac = use_random_mac

        # Credentials / Auth data (set via apply_credentials)
        self.client_id: Optional[str] = None
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.accesstoken: Optional[str] = None
        self.refreshtoken: Optional[str] = None
        self.accesstoken_time: Optional[int] = None
        self.accesstoken_duration_day: Optional[int] = None
        self.refreshtoken_time: Optional[int] = None
        self.refreshtoken_duration_day: Optional[int] = None

        # Internal state
        self._client: Optional[mqtt.Client] = None
        self._authenticated = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cross_sum(self, n: int) -> int:
        return sum(int(d) for d in str(n))

    def _string_to_hash(self, s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest().upper()

    def _random_mac_address(self) -> str:
        mac = [random.randint(0x00, 0xFF) for _ in range(6)]
        return ":".join(f"{o:02x}" for o in mac)

    def _topic_paths(self):
        """Return topic base paths for the current client ID."""
        cid = self.client_id
        return {
            "tv_ui": f"/remoteapp/tv/ui_service/{cid}/",
            "tv_ps": f"/remoteapp/tv/platform_service/{cid}/",
            "mobi":  f"/remoteapp/mobile/{cid}/",
            "brcs":  f"/remoteapp/mobile/broadcast/",
            "remo":  f"/remoteapp/tv/remote_service/{cid}/",
        }

    # ------------------------------------------------------------------
    # MQTT setup
    # ------------------------------------------------------------------

    def _create_client(self, username: str, password: str) -> mqtt.Client:
        """Create a preconfigured MQTT client using embedded certs."""
        client = mqtt.Client(
            client_id=self.client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
            transport="tcp",
        )

        import ssl
        import tempfile

        # Write cert/key strings into temporary files for paho
        cert_tmp = tempfile.NamedTemporaryFile(delete=False)
        key_tmp = tempfile.NamedTemporaryFile(delete=False)
        cert_tmp.write(hisense_cert.encode("utf-8"))
        key_tmp.write(hisense_key.encode("utf-8"))
        cert_tmp.flush()
        key_tmp.flush()

        client.tls_set(
            ca_certs=None,
            certfile=cert_tmp.name,
            keyfile=key_tmp.name,
            cert_reqs=ssl.CERT_NONE,
            tls_version=ssl.PROTOCOL_TLS,
        )
        client.tls_insecure_set(True)
        client.username_pw_set(username=username, password=password)
        client.connected_flag = False
        return client

    async def _connect(self, username: str, password: str) -> mqtt.Client:
        """Connect the MQTT client asynchronously."""
        client = self._create_client(username, password)

        def on_connect(c, _u, _f, rc):
            c.connected_flag = (rc == 0)
            if rc == 0:
                _LOGGER.debug("Connected to MQTT on %s", self.tv_ip)
            else:
                _LOGGER.error("MQTT connect failed rc=%s", rc)

        client.on_connect = on_connect
        self._client = client
        client.connect_async(self.tv_ip, 36669, 60)
        client.loop_start()

        for _ in range(30):  # ~15s timeout
            if client.connected_flag:
                return client
            await asyncio.sleep(0.5)

        await self.disconnect()
        raise ConnectionError(f"Failed to connect to {self.tv_ip}")

    async def disconnect(self):
        """Disconnect and stop MQTT loop."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            _LOGGER.debug("Disconnected from MQTT.")
            self._client = None

    # ------------------------------------------------------------------
    # Credentials handling
    # ------------------------------------------------------------------

    def apply_credentials(self, credentials: dict):
        """Store credentials in memory."""
        self.client_id = credentials.get("client_id")
        self.username = credentials.get("username")
        self.password = credentials.get("password")
        self.accesstoken = credentials.get("accesstoken")
        self.accesstoken_time = credentials.get("accesstoken_time")
        self.accesstoken_duration_day = credentials.get("accesstoken_duration_day")
        self.refreshtoken = credentials.get("refreshtoken")
        self.refreshtoken_time = credentials.get("refreshtoken_time")
        self.refreshtoken_duration_day = credentials.get("refreshtoken_duration_day")
        self._authenticated = True
        _LOGGER.debug("Credentials applied in memory for %s", self.client_id)

    def _token_valid(self) -> bool:
        try:
            now = time.time()
            exp = int(self.accesstoken_time) + int(self.accesstoken_duration_day) * 86400
            return now <= exp
        except Exception:
            return False

    async def async_ensure_token(self):
        """Ensure we have a valid token (refresh not implemented yet)."""
        if self._token_valid():
            return
        _LOGGER.warning("Access token invalid or expired. Re-authentication required.")

    # ------------------------------------------------------------------
    # Public API methods (for HA)
    # ------------------------------------------------------------------

    async def async_get_state(self) -> Optional[dict]:
        """Retrieve current TV state."""
        if not self._authenticated:
            _LOGGER.warning("Not authenticated, cannot get state.")
            return None

        await self.async_ensure_token()
        await self._connect(self.username, self.accesstoken)

        paths = self._topic_paths()
        topic_sub = paths["brcs"] + "ui_service/state"
        topic_pub = paths["tv_ui"] + "actions/gettvstate"

        payload_box = {"data": None}

        def on_state(_c, _u, msg):
            try:
                payload_box["data"] = json.loads(msg.payload.decode("utf-8"))
            except Exception as e:
                _LOGGER.error("Malformed state payload: %s", e)

        self._client.message_callback_add(topic_sub, on_state)
        self._client.subscribe(topic_sub)
        self._client.publish(topic_pub, None)

        for _ in range(20):  # 10s max
            if payload_box["data"] is not None:
                break
            await asyncio.sleep(0.5)

        await self.disconnect()
        return payload_box["data"]

    async def async_send_key(self, key: str) -> None:
        """Send remote key to TV."""
        await self.async_ensure_token()
        await self._connect(self.username, self.accesstoken)

        topic = self._topic_paths()["remo"] + "actions/sendkey"
        _LOGGER.debug("Sending key %s", key)
        self._client.publish(topic, key)
        await asyncio.sleep(0.2)
        await self.disconnect()

    async def async_set_volume(self, volume: int) -> None:
        """Change TV volume (0–100)."""
        await self.async_ensure_token()
        await self._connect(self.username, self.accesstoken)

        topic = self._topic_paths()["tv_ps"] + "actions/changevolume"
        _LOGGER.debug("Setting volume to %s", volume)
        self._client.publish(topic, str(volume))
        await asyncio.sleep(0.2)
        await self.disconnect()

    async def async_turn_on(self) -> None:
        """Power on TV (if off)."""
        state = await self.async_get_state()
        if not state or state.get("statetype") == "fake_sleep_0":
            _LOGGER.debug("TV appears off; sending POWER key to turn on.")
            await self.async_send_key("KEY_POWER")
        else:
            _LOGGER.debug("TV already on; skipping power on.")

    async def async_turn_off(self) -> None:
        """Power off TV (if on)."""
        state = await self.async_get_state()
        if state and state.get("statetype") != "fake_sleep_0":
            _LOGGER.debug("TV appears on; sending POWER key to turn off.")
            await self.async_send_key("KEY_POWER")
        else:
            _LOGGER.debug("TV already off; skipping power off.")

    async def async_change_source(self, source_id: str) -> None:
        """Switch input source."""
        state = await self.async_get_state()
        if not state or state.get("statetype") == "fake_sleep_0":
            _LOGGER.info("TV off; cannot change source.")
            return

        await self.async_ensure_token()
        await self._connect(self.username, self.accesstoken)
        topic = self._topic_paths()["tv_ui"] + "actions/changesource"
        self._client.publish(topic, json.dumps({"sourceid": source_id}))
        _LOGGER.debug("Changed source to %s", source_id)
        await asyncio.sleep(0.2)
        await self.disconnect()

    async def async_launch_app(self, app_id: str, app_name: str, url: str) -> None:
        """Launch app on TV."""
        state = await self.async_get_state()
        if not state or state.get("statetype") == "fake_sleep_0":
            _LOGGER.info("TV off; cannot launch app.")
            return

        await self.async_ensure_token()
        await self._connect(self.username, self.accesstoken)
        topic = self._topic_paths()["tv_ui"] + "actions/launchapp"
        payload = json.dumps({"appId": app_id, "name": app_name, "url": url})
        self._client.publish(topic, payload)
        _LOGGER.debug("Launched app %s", app_name)
        await asyncio.sleep(0.2)
        await self.disconnect()

    async def async_start_pairing(self) -> bool:
        """
        Start pairing process:
        - connect via MQTT
        - send app_connect message
        - wait for TV to show auth code
        """
        # basically: everything up to where your old generate_creds() waited for auth code
        # subscribe to 'authentication' and 'authenticationcode'
        # send 'vidaa_app_connect' message
        # wait until TV responds asking for code
        _LOGGER.info("Starting pairing flow, please check your TV for a 4-digit code...")
        # store internal state so async_finish_pairing() can continue
        self._pairing_context = {...}
        return True  # means code is now shown on TV


    async def async_finish_pairing(self, auth_code: str) -> dict:
        """
        Finish pairing:
        - send auth code to TV
        - receive tokenissuance
        - return credentials dict
        """
        # corresponds to second part of your generate_creds()
        credentials = {...}  # dict from tokenissuance payload
        self.apply_credentials(credentials)
        return credentials