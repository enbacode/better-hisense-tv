from __future__ import annotations

import logging
import tempfile
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .tv_controller import HisenseTVController
from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Better Hisense TV (manual credentials mode)."""

    ip = entry.data["ip"]

    # Direkt gespeicherte Credentials
    credentials = entry.data

    CERT_DATA = """-----BEGIN CERTIFICATE-----
MIIDvTCCAqWgAwIBAgIBAjANBgkqhkiG9w0BAQsFADBnMQswCQYDVQQGEwJDTjER
MA8GA1UECAwIc2hhbmRvbmcxEDAOBgNVBAcMB3FpbmdkYW8xCzAJBgNVBAoMAmho
MRMwEQYDVQQLDAptdWx0aW1lZGlhMREwDwYDVQQDDAhSZW1vdGVDQTAeFw0xODA0
MTkwMjAxMTdaFw00MzA0MTMwMjAxMTdaMGAxCzAJBgNVBAYTAkNOMREwDwYDVQQI
DAhzaGFuZG9uZzELMAkGA1UECgwCaGgxFDASBgNVBAsMC211bHRpc2NyZWVuMRsw
GQYDVQQDDBJyZW1vdGVjbGllbnRtb2JpbGUwggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQDu/o3p42CAraBA19IrYteEt8N8dyAvUmEyTVZMwHobwzNUABra
zUXhmFvduh02q/1y2TblB8dHSf53WKV+5O+sRpD7dc1lbhgoYLmHp3yVxrVDDKTo
z22fH54LrLm3t2k3j3ShXMbJIBEQqFJxW0P0I4Kj7wktKWBQ1rJjK3gFgHxaRugC
0oGZuv16M9Dn7tKpg+VX9SQ5Uj6nFjHv5scFUOBC7rPPlcFNQhkZT4Mdg/fcCFlJ
0hF5R6BDniRkRLEmsyNWhFSUf6UKDcNIDuPlcjYEmZNB5p4OGVWt0c/A5q057ZVO
RsSq9dwUgkSjj4Zz8nGK1lf3P5KVFMdocvzDAgMBAAGjezB5MAkGA1UdEwQCMAAw
LAYJYIZIAYb4QgENBB8WHU9wZW5TU0wgR2VuZXJhdGVkIENlcnRpZmljYXRlMB0G
A1UdDgQWBBSoDVzwztBO4zBMk73za2OMYSa+3DAfBgNVHSMEGDAWgBQjQIKRqSQG
hzF4k4+glDyqSfz8OzANBgkqhkiG9w0BAQsFAAOCAQEAgrk7ZK0/eGlY8uqAql25
R+cm17C+3MAvAj7yuU889CewPDPTtZmM05/1i0bV1oo2Pp9fLf0dxLovTwBpvAN8
lcxYNPxbZ824+sSncwx2AujmTJk7eIUoHczhluiU6rapK8apkU/iN4GNcBZkbccn
1FghvHaAKmUefzOwbY2LOAd7Z1KhKmf6MyL7RqN8LAgx3i2uiW1GM4C8KeFxZ090
9+e4R6eufW/V+58/HJtF9jECeNikLvJpxveCC6Q/N49s72hHZC0L0NeJ7GNKzoOi
8lXL5QgNGCg/bawsx9q5YvWLsDOVJIEhWv3MxmnC/reIeDf7iMEK3BP5E4u8uTzJ
Hg==
-----END CERTIFICATE-----"""

    KEY_DATA = """-----BEGIN PRIVATE KEY-----
MIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQDu/o3p42CAraBA
19IrYteEt8N8dyAvUmEyTVZMwHobwzNUABrazUXhmFvduh02q/1y2TblB8dHSf53
WKV+5O+sRpD7dc1lbhgoYLmHp3yVxrVDDKToz22fH54LrLm3t2k3j3ShXMbJIBEQ
qFJxW0P0I4Kj7wktKWBQ1rJjK3gFgHxaRugC0oGZuv16M9Dn7tKpg+VX9SQ5Uj6n
FjHv5scFUOBC7rPPlcFNQhkZT4Mdg/fcCFlJ0hF5R6BDniRkRLEmsyNWhFSUf6UK
DcNIDuPlcjYEmZNB5p4OGVWt0c/A5q057ZVORsSq9dwUgkSjj4Zz8nGK1lf3P5KV
FMdocvzDAgMBAAECggEBAIwImx5wHBtJoJxd2MeTIrSg9+n14uXXXxwaNHbEUMfz
mB+f8BxEKq4El89TPcrK+7ZPj9qitCEROgiz6ERx3/0RW+H7JF5KI92EzzCs8lLQ
G2UuA3JmF9UksXYlvqvmy7/CTpQ9yDwQje80sRm6YBast99WMApGNCkpo1x4G9sc
S994P5wQwE+aC4encNDfrbPmDco2vjTIhVmcFJ9hxfPvkZbecxlMnKnh1eQtLYzB
DxWTTtpKzCg+EDhp67aE9MlB/HJ06hCHyrt/QaUGfrAa0lGOOJq2tHK+D7ZCi1BW
Y7FXHwrkgO+PiEtjCex6d4I7gZKoZuO8oIhRbaWvMAECgYEA+d6kCnOk7z+AJFzm
MuITuASBxTZovguGuQ2hKX479pKLw+ehs0J/srR35SPHeLaAzsuG8Xi5tKNpbnY9
c/aHfEdj+CYP8k5aWvhuGO3dZYyGTHlDcex4Tmx1ytOeC74RWJxHRPWg21l29Nfd
MmlW2+UW8+TEDPY/if6AGMW4Pd8CgYEA9Nub1OP5wX8sllRuGBnMm14Mx+p6bEnp
AEB81Nj8DwYKMaWlrq+l6R0RB/jsnaSRe0KfdL1MKN5VSOfevd2gwgET0vJCRhPk
rlBG8BVyG9ma1Fd+K00CQ2iOMVSIqW6OKDDiXVif2/U51mrc0oz3JXXFR14ck3TR
El5auO9WVZ0CgYBNxy/o0PaWQn3w07oUPKtGrKB4cudHwO6+y69O6yxfJF69LGz5
D8oQJnzrpqeAu858kH4AzEOCJxu6drPKVQL3fIFxzOdJ1Xnqt0oOGHzCD2v+ggCs
hZ8tSjWgXR7lKNTdcEf+/zaDEOYmcMs51fBjonvyj1M3da9xlPbqvyEKoQKBgQDm
comHI8i7w+VC1tOG+0EGOM3umU/++tC/2/GgoVcZDKYrc6srbUTI0QJmbnDDLU9+
ooVQaZh0HkxGAXQxXZUfAcSWlEqria2AIS2iZ4ytiW+eyXmFZ0TqDE1HQDgevl4s
lVV2ZSKO8Y0tsAWEZAd2yhCRypE6docOsp7PzvGCQQKBgQCinwRjA6qjSEUcXwR1
F7ep46RNe8JGpJ2ZMffneFct8P4fyKYMSY5zZBc9kYSxpgJPZc5Y+V5Tq+vWc4SX
/QNCZLcC5wMVs2jp8LYruoR0QoQdizpvlKQC2s4UD7Lp12lntJsCDULN9G9lzKUI
LgVhEy5cFTsByGHGWF6LAKrpHA==
-----END PRIVATE KEY-----"""

    # Temporäre Zertifikatsdateien anlegen
    with tempfile.NamedTemporaryFile(delete=False) as certfile:
        certfile.write(CERT_DATA.encode())
        certfile.flush()

    with tempfile.NamedTemporaryFile(delete=False) as keyfile:
        keyfile.write(KEY_DATA.encode())
        keyfile.flush()

    controller = HisenseTVController(ip, certfile=certfile.name, keyfile=keyfile.name)

    # Manuelle Credentials zuweisen
    controller.client_id = credentials.get("client_id")
    controller.username = credentials.get("username")
    controller.password = credentials.get("password")
    controller.accesstoken = credentials.get("accesstoken")
    controller.accesstoken_time = credentials.get("accesstoken_time")
    controller.accesstoken_duration_day = credentials.get("accesstoken_duration_day")
    controller.refreshtoken = credentials.get("refreshtoken")
    controller.refreshtoken_time = credentials.get("refreshtoken_time")
    controller.refreshtoken_duration_day = credentials.get("refreshtoken_duration_day")
    _LOGGER.warning({"client_id": controller.client_id, "username": controller.username, "password": controller.password,
                     "accesstoken": controller.accesstoken, "accesstoken_time": controller.accesstoken_time,
                     "accesstoken_duration_day": controller.accesstoken_duration_day,
                     "refreshtoken": controller.refreshtoken, "refreshtoken_time": controller.refreshtoken_time,
                     "refreshtoken_duration_day": controller.refreshtoken_duration_day})
    controller._define_topic_paths()

    # Verbindung mit Access Token aufbauen
    try:
        await controller.connect_with_access_token()
        _LOGGER.info("Connected to Hisense TV at %s", ip)
    except Exception as err:
        _LOGGER.error("Failed to connect to Hisense TV at %s: %s", ip, err)
        return False

    async def async_update_data():
        """Periodisch TV-Status abrufen."""
        try:
            # Automatisch Token-Refresh prüfen
            await controller.check_and_refresh_token()
            state = await controller.get_tv_state()
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
    """Unload integration and clean up."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
