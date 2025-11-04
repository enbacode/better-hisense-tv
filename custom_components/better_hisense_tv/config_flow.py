from __future__ import annotations

import logging
import os
import voluptuous as vol
import tempfile

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

CONF_IP = "ip"

from .const import DOMAIN
from .tv_controller import HisenseTVController

_LOGGER = logging.getLogger(__name__)


class BetterHisenseTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Better Hisense TV (automatic pairing)."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        self._ip: str | None = None
        self._controller: HisenseTVController | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: ask for IP address."""
        errors = {}
        if user_input is not None:
            ip = user_input[CONF_IP]
            self._ip = ip
            certfile = os.path.join(os.path.dirname(__file__), "../certchain_pem.cer")
            keyfile = os.path.join(os.path.dirname(__file__), "../rcm_pem_privkey.pkcs8")
            _LOGGER.warning("Cert Paths: %s, %s", certfile, keyfile)


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
-----END CERTIFICATE-----
"""

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
-----END PRIVATE KEY-----
"""

            with tempfile.NamedTemporaryFile(delete=False) as certfile:
                certfile.write(CERT_DATA.encode())
                certfile.flush()

            with tempfile.NamedTemporaryFile(delete=False) as keyfile:
                keyfile.write(KEY_DATA.encode())
                keyfile.flush()

            controller = HisenseTVController(ip, certfile=certfile.name, keyfile=keyfile.name)

            # initialize controller
            self._controller = controller

            try:
                _LOGGER.debug("Starting pairing with Hisense TV at %s", ip)
                await controller.request_auth_code()
                return await self.async_step_authcode()
            except Exception as e:
                _LOGGER.error("Failed to connect to TV at %s: %s", ip, e)
                errors["base"] = "connection_failed"

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default="Hisense TV"): str,
            vol.Required(CONF_IP): str,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_authcode(self, user_input=None):
        """Step 2: user enters the 4-digit code from the TV screen."""
        errors = {}
        if user_input is not None:
            auth_code = user_input["auth_code"]

            try:
                await self._controller.verify_auth_code(auth_code)
                return self.async_create_entry(
                        title=f"Hisense TV ({self._ip})",
                        data={
                            "ip": self._ip,
                            "credentials": {
                                "client_id": self._controller.client_id,
                                "username": self._controller.username,
                                "password": self._controller.password
                            },
                        },
                    )
            except Exception as e:
                _LOGGER.error("Authentication failed: %s", e)
                errors["base"] = "auth_failed"

        schema = vol.Schema({
            vol.Required("auth_code", description="Code shown on your TV"): str,
        })
        return self.async_show_form(step_id="authcode", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BetterHisenseTVOptionsFlow(config_entry)


class BetterHisenseTVOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow (edit existing entry)."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Allow changing only the IP address."""
        if user_input is not None:
            data = self.config_entry.data.copy()
            data["ip"] = user_input["ip"]
            return self.async_create_entry(title="", data=data)
            
        schema = vol.Schema({
            vol.Required("ip", default=self.config_entry.data.get("ip", "")): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema)
