"""HTTP views for the Nubly integration."""

import hashlib
import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_MEDIA_ENTITY, DOMAIN

_LOGGER = logging.getLogger(__name__)


class NublyCoverArtView(HomeAssistantView):
    """Serve the current media artwork for a Nubly device.

    This endpoint does not require auth. It is scoped by the device's
    hardware id, which the ESP32 already knows. HA performs the actual
    authenticated media_player lookup in-process, so no HA token ever
    leaves Home Assistant.
    """

    url = "/api/nubly/{device_id}/cover_art"
    name = "api:nubly:cover_art"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request, device_id: str) -> web.Response:
        _LOGGER.warning(
            "NUBLY HA: cover art requested for device_id = %s", device_id
        )

        entry = _find_entry_by_device_id(self.hass, device_id)
        if entry is None:
            return web.Response(status=404, text="unknown device")

        media_entity = entry.data.get(CONF_MEDIA_ENTITY)
        if not media_entity:
            return web.Response(status=404, text="no media entity configured")

        _LOGGER.warning(
            "NUBLY HA: fetching media artwork for entity = %s", media_entity
        )

        state = self.hass.states.get(media_entity)
        etag_source = ""
        if state is not None:
            etag_source = "|".join(
                str(state.attributes.get(k, ""))
                for k in ("entity_picture", "media_title", "media_content_id")
            )
        etag = (
            hashlib.sha1(etag_source.encode("utf-8")).hexdigest()[:16]
            if etag_source
            else ""
        )

        if etag and request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})

        component = self.hass.data.get("media_player")
        if component is None:
            _LOGGER.warning("NUBLY HA: cover art response failed (no media_player)")
            return web.Response(status=503, text="media_player unavailable")

        player = component.get_entity(media_entity)
        if player is None:
            _LOGGER.warning(
                "NUBLY HA: cover art response failed (entity %s not found)",
                media_entity,
            )
            return web.Response(status=404, text="entity not found")

        try:
            image = await player.async_get_media_image()
        except Exception:
            _LOGGER.exception("NUBLY HA: cover art response failed")
            return web.Response(status=502, text="fetch failed")

        if not image or not image[0]:
            _LOGGER.warning("NUBLY HA: cover art response failed (no image)")
            return web.Response(status=404, text="no image")

        image_bytes, content_type = image
        _LOGGER.warning(
            "NUBLY HA: cover art response ok (%d bytes)", len(image_bytes)
        )

        headers = {"Cache-Control": "no-cache, max-age=0"}
        if etag:
            headers["ETag"] = etag

        return web.Response(
            body=image_bytes,
            content_type=content_type or "image/jpeg",
            headers=headers,
        )


def _find_entry_by_device_id(hass: HomeAssistant, device_id: str):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_DEVICE_ID) == device_id:
            return entry
    return None
