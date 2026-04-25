"""MQTT provisioning helpers.

Phase 1 (detection): probes Supervisor / Mosquitto availability.
Phase 2/3 (this module): orchestrates the full onboarding sequence — generate
credentials, register the user with the Mosquitto add-on via Supervisor,
restart Mosquitto, wait for HA's MQTT client to reconnect, then POST the
credentials to the ESP32 /provision endpoint.

Passwords are generated with `secrets.token_urlsafe`, kept in local variables
only for the duration of the flow, never logged, never stored in any config
entry, never published over MQTT.
"""

import asyncio
import logging
import os
import secrets
import socket

import aiohttp

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_TOKEN_ENV = "SUPERVISOR_TOKEN"
SUPERVISOR_BASE = "http://supervisor"
MOSQUITTO_INFO_URL = f"{SUPERVISOR_BASE}/addons/core_mosquitto/info"
MOSQUITTO_OPTIONS_URL = f"{SUPERVISOR_BASE}/addons/core_mosquitto/options"
MOSQUITTO_RESTART_URL = f"{SUPERVISOR_BASE}/addons/core_mosquitto/restart"

REQUEST_TIMEOUT_SECONDS = 5
SUPERVISOR_WRITE_TIMEOUT_SECONDS = 30
PROVISION_PORT = 80
PROVISION_TIMEOUT_SECONDS = 10
MQTT_RECONNECT_TIMEOUT_SECONDS = 15
PUBLISH_READY_TIMEOUT_SECONDS = 30
PUBLISH_READY_INTERVAL_SECONDS = 1
DEFAULT_BROKER_HOST = "homeassistant.local"
DEFAULT_BROKER_PORT = 1883

# Hostnames that resolve only inside the Supervisor's Docker network and are
# therefore unusable from a LAN device like the ESP32.
_SUPERVISOR_INTERNAL_HOSTS = frozenset(
    {
        "core-mosquitto",
        "core_mosquitto",
        "homeassistant",
        "supervisor",
        "hassio",
        "localhost",
        "127.0.0.1",
        "::1",
    }
)


async def async_check_provisioning_support(hass: HomeAssistant) -> dict:
    """Probe Supervisor for Mosquitto add-on availability.

    Returns a dict: {"supervisor": bool, "mosquitto": bool, "supported": bool}.
    Logs at debug level. Never raises.
    """
    result = {"supervisor": False, "mosquitto": False, "supported": False}

    token = os.environ.get(SUPERVISOR_TOKEN_ENV)
    if not token:
        _LOGGER.debug("NUBLY HA: supervisor detected = false")
        return result

    result["supervisor"] = True
    _LOGGER.debug("NUBLY HA: supervisor detected = true")

    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)

    try:
        async with session.get(
            MOSQUITTO_INFO_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        ) as resp:
            if resp.status == 200:
                body = await resp.json()
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data.get("version"):
                    result["mosquitto"] = True
            elif resp.status == 404:
                result["mosquitto"] = False
            else:
                _LOGGER.warning(
                    "NUBLY HA: supervisor returned HTTP %s for mosquitto info",
                    resp.status,
                )
    except Exception:
        _LOGGER.exception("NUBLY HA: supervisor probe failed")
        return result

    _LOGGER.debug(
        "NUBLY HA: mosquitto add-on detected = %s", result["mosquitto"]
    )

    if result["mosquitto"]:
        result["supported"] = True

    return result


async def async_provision_device(
    hass: HomeAssistant, host: str, device_id: str
) -> str | None:
    """Run the full onboarding provisioning flow.

    Returns None on success, or a translation key for the failing step.
    """
    token = os.environ.get(SUPERVISOR_TOKEN_ENV)
    if not token:
        _LOGGER.warning(
            "NUBLY HA: supervisor not available — cannot provision automatically"
        )
        return "supervisor_unavailable"

    username = device_id if device_id.startswith("nubly_") else f"nubly_{device_id}"
    password = secrets.token_urlsafe(32)
    _LOGGER.debug("NUBLY HA: generated MQTT username = %s", username)

    if not await _async_add_mosquitto_user(hass, token, username, password):
        return "mosquitto_user_add_failed"

    _LOGGER.info("NUBLY HA: restarting Mosquitto for credential provisioning")
    if not await _async_restart_mosquitto(hass, token):
        return "mosquitto_restart_failed"

    _LOGGER.debug("NUBLY HA: waiting for MQTT reconnect")
    if not await _async_wait_for_mqtt(hass):
        return "mqtt_reconnect_timeout"
    _LOGGER.debug("NUBLY HA: MQTT reconnect signal received")

    if not await _async_wait_for_publish_ready(hass, device_id):
        return "mqtt_publish_not_ready"

    if not await _async_post_provision(hass, host, device_id, username, password):
        return "provisioning_failed"

    return None


async def _async_wait_for_publish_ready(
    hass: HomeAssistant, device_id: str
) -> bool:
    """Confirm the MQTT client can actually publish, not just that it claims
    to be connected. Loop a small test publish until it succeeds or the
    timeout expires.
    """
    _LOGGER.debug("NUBLY HA: testing MQTT publish readiness")
    topic = f"nubly/internal/{device_id}/mqtt_ready"
    deadline = asyncio.get_event_loop().time() + PUBLISH_READY_TIMEOUT_SECONDS

    while True:
        try:
            await hass.services.async_call(
                "mqtt",
                "publish",
                {
                    "topic": topic,
                    "payload": "1",
                    "qos": 0,
                    "retain": False,
                },
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.debug(
                "NUBLY HA: publish readiness check not ready: %s", err
            )
        except Exception:
            _LOGGER.exception(
                "NUBLY HA: unexpected error during publish readiness check"
            )
        else:
            _LOGGER.debug("NUBLY HA: MQTT publish readiness ok")
            return True

        if asyncio.get_event_loop().time() >= deadline:
            _LOGGER.error(
                "NUBLY HA: MQTT publish readiness timed out after %ss",
                PUBLISH_READY_TIMEOUT_SECONDS,
            )
            return False

        await asyncio.sleep(PUBLISH_READY_INTERVAL_SECONDS)


async def _async_add_mosquitto_user(
    hass: HomeAssistant, token: str, username: str, password: str
) -> bool:
    """Append (or replace) a login in Mosquitto add-on options."""
    session = async_get_clientsession(hass)
    headers = {"Authorization": f"Bearer {token}"}
    read_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    write_timeout = aiohttp.ClientTimeout(total=SUPERVISOR_WRITE_TIMEOUT_SECONDS)

    try:
        async with session.get(
            MOSQUITTO_INFO_URL, headers=headers, timeout=read_timeout
        ) as resp:
            if resp.status != 200:
                _LOGGER.warning(
                    "NUBLY HA: mosquitto info returned HTTP %s", resp.status
                )
                return False
            body = await resp.json()
    except Exception:
        _LOGGER.exception("NUBLY HA: failed to fetch mosquitto info")
        return False

    data = body.get("data") if isinstance(body, dict) else None
    options = dict((data or {}).get("options") or {})
    logins = [
        login
        for login in (options.get("logins") or [])
        if isinstance(login, dict) and login.get("username") != username
    ]
    logins.append({"username": username, "password": password})
    options["logins"] = logins

    try:
        async with session.post(
            MOSQUITTO_OPTIONS_URL,
            headers=headers,
            json={"options": options},
            timeout=write_timeout,
        ) as resp:
            if resp.status != 200:
                _LOGGER.warning(
                    "NUBLY HA: mosquitto options POST returned HTTP %s",
                    resp.status,
                )
                return False
    except Exception:
        _LOGGER.exception("NUBLY HA: failed to update mosquitto options")
        return False

    _LOGGER.info("NUBLY HA: added MQTT user to Mosquitto")
    return True


async def _async_restart_mosquitto(hass: HomeAssistant, token: str) -> bool:
    session = async_get_clientsession(hass)
    headers = {"Authorization": f"Bearer {token}"}
    timeout = aiohttp.ClientTimeout(total=SUPERVISOR_WRITE_TIMEOUT_SECONDS)

    try:
        async with session.post(
            MOSQUITTO_RESTART_URL, headers=headers, timeout=timeout
        ) as resp:
            if resp.status != 200:
                _LOGGER.warning(
                    "NUBLY HA: mosquitto restart returned HTTP %s", resp.status
                )
                return False
    except Exception:
        _LOGGER.exception("NUBLY HA: failed to restart mosquitto")
        return False
    return True


async def _async_wait_for_mqtt(hass: HomeAssistant) -> bool:
    wait_fn = getattr(mqtt, "async_wait_for_mqtt_client", None)
    if wait_fn is None:
        _LOGGER.debug(
            "NUBLY HA: async_wait_for_mqtt_client not available; sleeping briefly"
        )
        await asyncio.sleep(5)
        return True

    try:
        await asyncio.wait_for(
            wait_fn(hass), timeout=MQTT_RECONNECT_TIMEOUT_SECONDS
        )
        return True
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "NUBLY HA: MQTT did not reconnect within %ss",
            MQTT_RECONNECT_TIMEOUT_SECONDS,
        )
        return False
    except Exception:
        _LOGGER.exception("NUBLY HA: MQTT wait raised unexpectedly")
        return False


async def _async_post_provision(
    hass: HomeAssistant,
    host: str,
    device_id: str,
    username: str,
    password: str,
) -> bool:
    url = f"http://{host}:{PROVISION_PORT}/provision"
    _LOGGER.info("NUBLY HA: provisioning device at %s", url)

    broker_host = await _async_resolve_provision_broker_host(hass)
    payload = {
        "mqtt_host": broker_host,
        "mqtt_port": _get_broker_port(hass),
        "mqtt_username": username,
        "mqtt_password": password,
        "device_id": device_id,
    }
    _LOGGER.debug(
        "NUBLY HA: provisioning payload prepared for device_id = %s", device_id
    )

    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=PROVISION_TIMEOUT_SECONDS)

    try:
        async with session.post(url, json=payload, timeout=timeout) as resp:
            _LOGGER.debug(
                "NUBLY HA: provisioning response status = %s", resp.status
            )
            if resp.status == 200:
                _LOGGER.info("NUBLY HA: provisioning succeeded")
                return True
            _LOGGER.warning(
                "NUBLY HA: provisioning failed (HTTP %s)", resp.status
            )
            return False
    except asyncio.TimeoutError:
        _LOGGER.warning("NUBLY HA: provisioning failed (timeout)")
        return False
    except aiohttp.ClientError:
        _LOGGER.warning("NUBLY HA: provisioning failed (connection error)")
        return False
    except Exception:
        _LOGGER.exception("NUBLY HA: provisioning failed (unexpected error)")
        return False


def _get_broker_host(hass: HomeAssistant) -> str:
    entries = hass.config_entries.async_entries("mqtt")
    if entries:
        return entries[0].data.get("broker") or DEFAULT_BROKER_HOST
    return DEFAULT_BROKER_HOST


async def _async_resolve_provision_broker_host(hass: HomeAssistant) -> str:
    """Return a broker host the ESP32 can actually reach over the LAN."""
    internal = _get_broker_host(hass)
    _LOGGER.debug("NUBLY HA: MQTT broker internal host = %s", internal)

    if internal.lower() not in _SUPERVISOR_INTERNAL_HOSTS:
        _LOGGER.info("NUBLY HA: MQTT broker provision host = %s", internal)
        return internal

    lan_ip = await _async_detect_lan_ip(hass)
    resolved = lan_ip or internal
    _LOGGER.info("NUBLY HA: MQTT broker provision host = %s", resolved)
    return resolved


async def _async_detect_lan_ip(hass: HomeAssistant) -> str | None:
    """Find the IP of the interface HA would use for outbound traffic."""

    def _sync() -> str | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("1.1.1.1", 80))
            return sock.getsockname()[0]
        except OSError:
            return None
        finally:
            sock.close()

    try:
        return await hass.async_add_executor_job(_sync)
    except Exception:
        _LOGGER.exception("NUBLY HA: LAN IP detection failed")
        return None


def _get_broker_port(hass: HomeAssistant) -> int:
    entries = hass.config_entries.async_entries("mqtt")
    if entries:
        try:
            return int(entries[0].data.get("port") or DEFAULT_BROKER_PORT)
        except (TypeError, ValueError):
            return DEFAULT_BROKER_PORT
    return DEFAULT_BROKER_PORT
