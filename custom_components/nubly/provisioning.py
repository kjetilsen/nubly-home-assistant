"""MQTT provisioning helpers.

Phase 1 (detection): probes Supervisor / Mosquitto availability.
Phase 2 (this module also): generates per-device MQTT credentials and POSTs
them to the ESP32's local /provision endpoint. The MQTT broker side is NOT
modified yet — the broker won't accept the new credentials until the firmware
falls back to its existing secrets, or until phase 3 (Mosquitto add-on
provisioning) is implemented.
"""

import asyncio
import logging
import os
import secrets

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_TOKEN_ENV = "SUPERVISOR_TOKEN"
MOSQUITTO_INFO_URL = "http://supervisor/addons/core_mosquitto/info"
REQUEST_TIMEOUT_SECONDS = 5

PROVISION_PORT = 80
PROVISION_TIMEOUT_SECONDS = 10
DEFAULT_BROKER_HOST = "homeassistant.local"
DEFAULT_BROKER_PORT = 1883


async def async_check_provisioning_support(hass: HomeAssistant) -> dict:
    """Probe Supervisor for Mosquitto add-on availability.

    Returns a dict: {"supervisor": bool, "mosquitto": bool, "supported": bool}.
    Logs the conclusion. Never raises.
    """
    result = {"supervisor": False, "mosquitto": False, "supported": False}

    token = os.environ.get(SUPERVISOR_TOKEN_ENV)
    if not token:
        _LOGGER.warning("NUBLY HA: supervisor detected = false")
        _LOGGER.warning("NUBLY HA: mosquitto add-on detected = false")
        _LOGGER.warning(
            "NUBLY HA: Automatic MQTT provisioning is not supported yet"
        )
        return result

    result["supervisor"] = True
    _LOGGER.warning("NUBLY HA: supervisor detected = true")

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
                # Supervisor returns data.version when the add-on is installed,
                # regardless of whether it's currently running.
                if isinstance(data, dict) and data.get("version"):
                    result["mosquitto"] = True
            elif resp.status == 404:
                # Add-on slug exists but isn't installed on this host.
                result["mosquitto"] = False
            else:
                _LOGGER.warning(
                    "NUBLY HA: supervisor returned HTTP %s for mosquitto info",
                    resp.status,
                )
    except Exception:
        _LOGGER.exception("NUBLY HA: supervisor probe failed")
        _LOGGER.warning(
            "NUBLY HA: Automatic MQTT provisioning is not supported yet"
        )
        return result

    _LOGGER.warning(
        "NUBLY HA: mosquitto add-on detected = %s", result["mosquitto"]
    )

    if result["mosquitto"]:
        result["supported"] = True
        _LOGGER.warning(
            "NUBLY HA: automatic MQTT provisioning will be supported (phase 2 not implemented)"
        )
    else:
        _LOGGER.warning(
            "NUBLY HA: Automatic MQTT provisioning is not supported yet"
        )

    return result


async def async_provision_device(
    hass: HomeAssistant, host: str, device_id: str
) -> bool:
    """POST MQTT credentials to the ESP32's /provision endpoint.

    Returns True on HTTP 200, False on any failure. Never logs the password.
    """
    url = f"http://{host}:{PROVISION_PORT}/provision"
    _LOGGER.warning("NUBLY HA: provisioning device at %s", url)

    broker_host = _get_broker_host(hass)
    broker_port = _get_broker_port(hass)

    payload = {
        "mqtt_host": broker_host,
        "mqtt_port": broker_port,
        "mqtt_username": f"nubly_{device_id}",
        "mqtt_password": secrets.token_urlsafe(32),
        "device_id": device_id,
    }
    _LOGGER.warning(
        "NUBLY HA: provisioning payload prepared for device_id = %s", device_id
    )

    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=PROVISION_TIMEOUT_SECONDS)

    try:
        async with session.post(url, json=payload, timeout=timeout) as resp:
            _LOGGER.warning(
                "NUBLY HA: provisioning response status = %s", resp.status
            )
            if resp.status == 200:
                _LOGGER.warning("NUBLY HA: provisioning succeeded")
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
    """Extract the broker host from HA's MQTT integration config entry."""
    entries = hass.config_entries.async_entries("mqtt")
    if entries:
        return entries[0].data.get("broker") or DEFAULT_BROKER_HOST
    return DEFAULT_BROKER_HOST


def _get_broker_port(hass: HomeAssistant) -> int:
    """Extract the broker port from HA's MQTT integration config entry."""
    entries = hass.config_entries.async_entries("mqtt")
    if entries:
        try:
            return int(entries[0].data.get("port") or DEFAULT_BROKER_PORT)
        except (TypeError, ValueError):
            return DEFAULT_BROKER_PORT
    return DEFAULT_BROKER_PORT
