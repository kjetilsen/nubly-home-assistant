"""MQTT-based discovery of Nubly devices."""

import asyncio
import logging

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .const import DISCOVERY_SUB_TOPIC, DISCOVERY_TIMEOUT

_LOGGER = logging.getLogger(__name__)


async def async_discover_devices(hass: HomeAssistant) -> set[str]:
    """Listen briefly on MQTT and return the set of Nubly device_ids seen."""
    found: set[str] = set()

    @callback
    def on_message(msg) -> None:
        parts = msg.topic.split("/")
        if len(parts) >= 3 and parts[0] == "nubly" and parts[1] == "devices":
            device_id = parts[2]
            if device_id.startswith("nubly_") and device_id not in found:
                _LOGGER.info("NUBLY HA: discovered device_id = %s", device_id)
                found.add(device_id)

    try:
        unsub = await mqtt.async_subscribe(hass, DISCOVERY_SUB_TOPIC, on_message)
    except Exception:
        _LOGGER.exception("NUBLY HA: MQTT discovery subscribe failed")
        return found

    try:
        await asyncio.sleep(DISCOVERY_TIMEOUT)
    finally:
        unsub()

    return found
