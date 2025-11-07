"""
tvcontroller.py — VIDAa/Hisense TV MQTT Controller (async, persistent client)
FIXED VERSION
"""

import asyncio
import hashlib
import json
import logging
import random
import re
import ssl
import time
import uuid
from typing import Callable, Awaitable, Optional, Dict, Any

import paho.mqtt.client as mqtt

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("tvcontroller")


def cross_sum(n: int) -> int:
    return sum(int(d) for d in str(n))


def string_to_hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()


def random_mac_address() -> str:
    return ":".join(f"{random.randint(0, 255):02x}" for _ in range(6))


class HisenseTVController:
    """
    Persistenter MQTT-Client für VIDAa/Hisense TVs inkl. Auth-Flow, Token-Refresh
    und bequemen Methoden (get_tv_state, send_key, change_source, etc.).
    """

    def __init__(
        self,
        tv_ip: str,
        certfile: str,
        keyfile: str,
        *,
        random_mac: bool = True,
        check_interval: float = 0.1,
        timeout: float = 60.0,
        debug: bool = False,
    ) -> None:
        self.tv_ip = tv_ip
        self.certfile = certfile
        self.keyfile = keyfile
        self.random_mac = random_mac
        self.check_interval = check_interval
        self.timeout = timeout
        self.debug = debug

        self.client: Optional[mqtt.Client] = None
        self._connected_evt = asyncio.Event()
        self._lock = asyncio.Lock()
        self._topic_waiters: Dict[str, asyncio.Future] = {}
        self._subscriptions: set[str] = set()
        self.is_connected: bool = False

        self.reply = None
        self.authentication_payload = None
        self.authentication_code_payload = None
        self.tokenissuance = None
        self.info: Optional[str] = None

        self.accesstoken: Optional[str] = None
        self.accesstoken_time: Optional[int] = None
        self.accesstoken_duration_day: Optional[int] = None

        self.refreshtoken: Optional[str] = None
        self.refreshtoken_time: Optional[int] = None
        self.refreshtoken_duration_day: Optional[int] = None

        self.client_id: Optional[str] = None
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.timestamp: Optional[int] = None
        self.authenticated: bool = False

        self.topicTVUIBasepath: Optional[str] = None
        self.topicTVPSBasepath: Optional[str] = None
        self.topicMobiBasepath: Optional[str] = None
        self.topicBrcsBasepath: Optional[str] = None
        self.topicRemoBasepath: Optional[str] = None

    def _build_client(self, client_id: str, username: str, password: str) -> mqtt.Client:
        client = mqtt.Client(client_id=client_id, clean_session=True, protocol=mqtt.MQTTv311, transport="tcp")
        client.tls_set(
            ca_certs=None,
            certfile=self.certfile,
            keyfile=self.keyfile,
            cert_reqs=ssl.CERT_NONE,
            tls_version=ssl.PROTOCOL_TLS,
        )
        client.tls_insecure_set(True)
        client.username_pw_set(username=username, password=password)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.on_subscribe = self._on_subscribe
        client.on_publish = self._on_publish

        if self.debug:
            client.enable_logger(logger)

        client.connected_flag = False
        client.cancel_loop = False
        return client

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.connected_flag = True
            self.is_connected = True
            self._connected_evt.set()
            logger.info("Connected to MQTT broker")
        else:
            self.is_connected = False
            logger.error(f"Bad connection. Returned code: {rc}")
            client.cancel_loop = True

    def _on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        logger.info(f"Disconnected. Reason: {rc}")
        self._connected_evt.clear()

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        logger.debug(f"Subscribed: {mid} {granted_qos}")

    def _on_publish(self, client, userdata, mid):
        logger.debug(f"Published message {mid}")

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8") if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload)
        logger.debug(f"[MQTT] {msg.topic} -> {payload}")

        fut = self._topic_waiters.get(msg.topic)
        if fut and not fut.done():
            fut.set_result(payload)

    async def ensure_connected(self, username: str, password: str, client_id: str) -> None:
        if self.client is None or not self.is_connected:
            self.client = self._build_client(client_id=client_id, username=username, password=password)
            self.client.loop_start()
            self.client.connect_async(self.tv_ip, 36669, 60)

        if not self._connected_evt.is_set():
            try:
                await asyncio.wait_for(self._connected_evt.wait(), timeout=self.timeout)
                self.is_connected = True
            except asyncio.TimeoutError:
                self.is_connected = False
                raise RuntimeError("Timeout while connecting to MQTT broker")

    async def _subscribe(self, topic: str, qos: int = 0) -> None:
        async with self._lock:
            if topic in self._subscriptions:
                return
            assert self.client is not None
            res = self.client.subscribe(topic, qos)
            if res[0] != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"Failed to subscribe {topic}: code {res[0]}")
            self._subscriptions.add(topic)

    async def _publish(self, topic: str, payload: Optional[str]) -> None:
        async with self._lock:
            assert self.client is not None
            res = self.client.publish(topic, payload)
            if res.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"Failed to publish to {topic}: code {res.rc}")

    async def _await_topic_once(self, topic: str, *, timeout: Optional[float] = None) -> str:
        """
        Wartet auf die nächste Nachricht zu `topic` und liefert deren (decoded) Payload zurück.
        """
        if topic in self._topic_waiters and not self._topic_waiters[topic].done():
            self._topic_waiters[topic].cancel()

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._topic_waiters[topic] = fut

        await self._subscribe(topic)
        try:
            payload = await asyncio.wait_for(fut, timeout=timeout or self.timeout)
            return payload
        finally:
            self._topic_waiters.pop(topic, None)

    def _define_hashes(self, *, new_auth: bool = False) -> None:
        self.timestamp = int(time.time())

        if self.random_mac:
            mac = random_mac_address()
        else:
            mac = ":".join(re.findall("..", f"{uuid.getnode():012x}")).upper()

        logger.info(f"MAC Address: {mac}")

        first_hash = string_to_hash("&vidaa#^app")
        second_hash = string_to_hash(f"38D65DC30F45109A369A86FCE866A85B${mac}")
        last_digit_of_cross = cross_sum(self.timestamp) % 10
        third_hash = string_to_hash(f"his{last_digit_of_cross}h*i&s%e!r^v0i1c9")
        fourth_hash = string_to_hash(f"{self.timestamp}${third_hash[:6]}")

        if new_auth:
            self.username = f"his${self.timestamp ^ 6239759785777146216}"
        else:
            self.username = f"his${self.timestamp}"

        self.password = fourth_hash
        self.client_id = f"{mac}$his${second_hash[:6]}_vidaacommon_001"

        if self.debug:
            logger.debug(f"Client ID: {self.client_id}")

    def _define_topic_paths(self) -> None:
        assert self.client_id is not None
        self.topicTVUIBasepath = f"/remoteapp/tv/ui_service/{self.client_id}/"
        self.topicTVPSBasepath = f"/remoteapp/tv/platform_service/{self.client_id}/"
        self.topicMobiBasepath = f"/remoteapp/mobile/{self.client_id}/"
        self.topicBrcsBasepath = "/remoteapp/mobile/broadcast/"
        self.topicRemoBasepath = f"/remoteapp/tv/remote_service/{self.client_id}/"

    def _apply_credentials(self, credentials: dict) -> None:
        """Helper method to apply credentials"""
        self.accesstoken = credentials["accesstoken"]
        self.accesstoken_time = credentials["accesstoken_time"]
        self.accesstoken_duration_day = credentials["accesstoken_duration_day"]
        self.refreshtoken = credentials["refreshtoken"]
        self.refreshtoken_time = credentials["refreshtoken_time"]
        self.refreshtoken_duration_day = credentials["refreshtoken_duration_day"]

    async def request_auth_code(self, *, new_auth: bool = False) -> None:
        """
        WICHTIG: Diese Methode allein reicht NICHT für den Auth-Flow!
        Verwende stattdessen generate_creds() für den kompletten Flow.
        """
        self._define_hashes(new_auth=new_auth)
        self._define_topic_paths()
        assert self.username and self.password and self.client_id

        await self.ensure_connected(self.username, self.password, self.client_id)

        # Subscribe zu ALLEN notwendigen Topics VOR dem Senden
        await self._subscribe(f"{self.topicBrcsBasepath}ui_service/state")
        await self._subscribe(f"{self.topicMobiBasepath}ui_service/data/authentication")
        await self._subscribe(f"{self.topicMobiBasepath}ui_service/data/authenticationcode")
        await self._subscribe(f"{self.topicBrcsBasepath}ui_service/data/hotelmodechange")
        await self._subscribe(f"{self.topicMobiBasepath}platform_service/data/tokenissuance")

        auth_topic = f"{self.topicMobiBasepath}ui_service/data/authentication"
        await self._publish(self.topicTVUIBasepath + "actions/vidaa_app_connect",
                            '{"app_version":2,"connect_result":0,"device_type":"Mobile App"}')

        payload = await self._await_topic_once(auth_topic)
        if payload.strip() != '""':
            raise RuntimeError(f"Unexpected authentication payload: {payload}")

        logger.info("Authentication request sent. The TV should now display a 4-digit code.")

    async def verify_auth_code(self, auth_code: str) -> str:
        """
        WICHTIG: Muss auf demselben Client wie request_auth_code laufen!
        Die Subscriptions müssen bereits aktiv sein.
        """
        assert self.client_id and self.username and self.password
        assert self.client is not None, "Client must be connected via request_auth_code first"

        auth_code_topic = f"{self.topicMobiBasepath}ui_service/data/authenticationcode"
        token_topic = f"{self.topicMobiBasepath}platform_service/data/tokenissuance"

        code = str(auth_code).strip()
        await self._publish(self.topicTVUIBasepath + "actions/authenticationcode", f'{{"authNum":{code}}}')

        msg = await self._await_topic_once(auth_code_topic)
        try:
            obj = json.loads(msg)
        except json.JSONDecodeError:
            obj = {}

        if obj.get("result") != 1:
            raise RuntimeError(f"Authentication failed: {msg}")

        logger.info("Authentication code verified. Requesting access token...")

        await self._publish(self.topicTVPSBasepath + "data/gettoken", '{"refreshtoken": ""}')
        await self._publish(self.topicTVUIBasepath + "actions/authenticationcodeclose", None)

        token_payload = await self._await_topic_once(token_topic)
        credentials = json.loads(token_payload)
        credentials.update({"client_id": self.client_id, "username": self.username, "password": self.password})

        self._apply_credentials(credentials)
        self.authenticated = True
        logger.info("Token issued successfully")

        return self.accesstoken

    async def generate_creds(
        self,
        *,
        auth_code_provider: Optional[Callable[[], Awaitable[str] | str]] = None,
        new_auth: bool = False,
    ) -> str:
        """
        Komfortfunktion: führt request_auth_code() + verify_auth_code() in einem Schritt aus.
        EMPFOHLENE METHODE für die Authentifizierung!
        """
        await self.request_auth_code(new_auth=new_auth)

        if auth_code_provider is None:
            def _sync_input():
                return input("Enter the four digits displayed on your TV: ").strip()
            auth_code_provider = _sync_input

        code = auth_code_provider()
        if asyncio.iscoroutine(code):
            code = await code

        return await self.verify_auth_code(str(code))

    async def refresh_token(self) -> str:
        """Token-Refresh via refreshtoken (als MQTT-Passwort)."""
        assert self.client_id and self.username and self.refreshtoken
        
        # Disconnect old client if exists
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self._connected_evt.clear()
            self._subscriptions.clear()
        
        await self.ensure_connected(self.username, self.refreshtoken, self.client_id)

        token_topic = f"{self.topicMobiBasepath}platform_service/data/tokenissuance"
        await self._subscribe(token_topic)
        
        await self._publish(f"/remoteapp/tv/platform_service/{self.client_id}/data/gettoken",
                            json.dumps({"refreshtoken": self.refreshtoken}))

        payload = await self._await_topic_once(token_topic)
        credentials = json.loads(payload)
        credentials.update({"client_id": self.client_id, "username": self.username, "password": self.password})
        logger.info("Token refreshed successfully")

        self._apply_credentials(credentials)
        self.authenticated = True
        return self.accesstoken


    async def check_and_refresh_token(self) -> str:
        """Prüft Gültigkeit des Access Tokens und refreshed falls nötig."""
        assert self.accesstoken and self.accesstoken_time and self.accesstoken_duration_day
        now = time.time()
        exp = int(self.accesstoken_time) + (self.accesstoken_duration_day * 24 * 60 * 60)

        if now <= exp:
            if self.debug:
                left = int(exp - now)
                days = left // 86400
                hours = (left % 86400) // 3600
                minutes = (left % 3600) // 60
                seconds = left % 60
                logger.debug(f"Access token valid for {days}d {hours}h {minutes}m {seconds}s")
            return self.accesstoken
        logger.info("Access token expired, refreshing...")
        return await self.refresh_token()

    async def connect_with_access_token(self) -> None:
        assert self.username and self.client_id and self.accesstoken

        # Nur neu verbinden, wenn nicht schon verbunden
        if self.is_connected and self.client is not None:
            return

        # Disconnect old client if exists
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self._connected_evt.clear()
            self._subscriptions.clear()
            self.is_connected = False

        try:
            await self.ensure_connected(self.username, self.accesstoken, self.client_id)
            self.is_connected = True
        except Exception:
            self.is_connected = False
            raise

    async def _get_info(self, *, callback_topic: str, subscribe_topic: str, publish_topic: str) -> Optional[dict]:
        if self.accesstoken:
            await self.check_and_refresh_token()
            await self.connect_with_access_token()
        else:
            raise RuntimeError("Not authenticated. Call generate_creds() first.")

        await self._subscribe(subscribe_topic)
        await self._publish(publish_topic, None)
        payload = await self._await_topic_once(callback_topic)
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse info payload from {callback_topic}: {payload}")
            return None

    async def _send_command(self, *, publish_topic: str, command: Optional[str]) -> None:
        if self.accesstoken:
            await self.check_and_refresh_token()
            await self.connect_with_access_token()
        else:
            raise RuntimeError("Not authenticated. Call generate_creds() first.")
        await self._publish(publish_topic, command)

    async def get_tv_state(self) -> Optional[dict]:
        callback = f"{self.topicBrcsBasepath}ui_service/state"
        subscribe = callback
        publish = f"{self.topicTVUIBasepath}actions/gettvstate"
        return await self._get_info(callback_topic=callback, subscribe_topic=subscribe, publish_topic=publish)

    async def get_source_list(self) -> Optional[list]:
        callback = f"{self.topicMobiBasepath}ui_service/data/sourcelist"
        subscribe = callback
        publish = f"{self.topicTVUIBasepath}actions/sourcelist"
        return await self._get_info(callback_topic=callback, subscribe_topic=subscribe, publish_topic=publish)

    async def get_volume(self) -> Optional[dict]:
        callback = f"{self.topicBrcsBasepath}platform_service/actions/volumechange"
        subscribe = callback
        publish = f"{self.topicTVPSBasepath}actions/getvolume"
        return await self._get_info(callback_topic=callback, subscribe_topic=subscribe, publish_topic=publish)

    async def get_app_list(self) -> Optional[list]:
        callback = f"{self.topicMobiBasepath}ui_service/data/applist"
        subscribe = callback
        publish = f"{self.topicTVUIBasepath}actions/applist"
        return await self._get_info(callback_topic=callback, subscribe_topic=subscribe, publish_topic=publish)

    async def power_cycle_tv(self) -> None:
        publish = f"{self.topicRemoBasepath}actions/sendkey"
        await self._send_command(publish_topic=publish, command="KEY_POWER")

    async def send_key(self, key: str) -> bool:
        state = await self.get_tv_state()
        if not state:
            logger.error("Failed to get TV state.")
            return False
        if state.get("statetype") == "fake_sleep_0":
            logger.info("TV is off. Not sending key...")
            return False
        publish = f"{self.topicRemoBasepath}actions/sendkey"
        await self._send_command(publish_topic=publish, command=key)
        return True

    async def change_source(self, source_id: str | int) -> bool:
        state = await self.get_tv_state()
        if not state:
            logger.error("Failed to get TV state.")
            return False
        if state.get("statetype") == "fake_sleep_0":
            logger.info("TV is off. Not changing source...")
            return False
        publish = f"{self.topicTVUIBasepath}actions/changesource"
        cmd = json.dumps({"sourceid": source_id})
        await self._send_command(publish_topic=publish, command=cmd)
        return True

    async def change_volume(self, volume: int) -> bool:
        state = await self.get_tv_state()
        if not state:
            logger.error("Failed to get TV state.")
            return False
        if state.get("statetype") == "fake_sleep_0":
            logger.info("TV is off. Not changing volume...")
            return False
        publish = f"{self.topicTVPSBasepath}actions/changevolume"
        await self._send_command(publish_topic=publish, command=str(volume))
        return True

    async def launch_app(self, app_name: str, app_list: Optional[list] = None) -> bool:
        if not app_list:
            app_list = await self.get_app_list()
            if not app_list:
                logger.error("Failed to get app list.")
                return False

        app_id = None
        app_url = None
        resolved_name = app_name
        for app in app_list:
            if app.get("name", "").upper() == app_name.upper():
                app_id = app.get("appId")
                app_url = app.get("url")
                resolved_name = app.get("name", app_name)
                break

        if not app_id or not app_url:
            logger.error("Failed to find app in app list.")
            return False

        state = await self.get_tv_state()
        if not state:
            logger.error("Failed to get TV state.")
            return False
        if state.get("statetype") == "fake_sleep_0":
            logger.info("TV is off. Not launching app...")
            return False

        publish = f"{self.topicTVUIBasepath}actions/launchapp"
        cmd = json.dumps({"appId": app_id, "name": resolved_name, "url": app_url})
        await self._send_command(publish_topic=publish, command=cmd)
        return True

    async def turn_on(self):
        tv_state = await self.get_tv_state()
        if tv_state:
            if "statetype" in tv_state and tv_state["statetype"] == "fake_sleep_0":
                await self.power_cycle_tv()
                logger.info("Power cycle command sent.")
            else:
                logger.info("TV is already on.")
        else:
            logger.error("Failed to get TV state.")

    async def turn_off(self):
        tv_state = await self.get_tv_state()
        if tv_state:
            if "statetype" in tv_state and tv_state["statetype"] != "fake_sleep_0":
                await self.power_cycle_tv()
                logger.info("Power cycle command sent.")
            else:
                logger.info("TV is already off.")
        else:
            logger.error("Failed to get TV state.")

    def credentials_summary(self) -> dict:
        return {
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
            "accesstoken": self.accesstoken,
            "accesstoken_time": self.accesstoken_time,
            "accesstoken_duration_day": self.accesstoken_duration_day,
            "refreshtoken": self.refreshtoken,
            "refreshtoken_time": self.refreshtoken_time,
            "refreshtoken_duration_day": self.refreshtoken_duration_day,
        }